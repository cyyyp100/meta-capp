# server/routers/reading.py — Canal temps réel du lecteur (WebSocket).
#
# client -> serveur : {"type":"ask","question","page"} | {"type":"rephrase","page"}
#                     {"type":"recap","page"} | {"type":"hook","page"}
#                     {"type":"viewport","page"} | {"type":"mode","mode"} | {"type":"focus"}
# serveur -> client : {"type":"loading"} | {"type":"answer","answer","highlights"}
#                     {"type":"error","message"} | {"type":"intervention",...}
#                     {"type":"system","message"}
#                     {"type":"scanning","active":bool}  # Gemma inspecte la page (décide
#                       d'intervenir ou non) -> l'UI tourne la bulle vers le PDF
from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from db.answers import save_answer
from db.documents import get_document, update_last_page
from db.flashcards import save_flashcard
from db.page_dwell import save_page_dwell
from db.questions import save_assistant_exchange, save_question
from db.user import DEFAULT_USER_ID
from llm.ollama_client import decide_intervention_async
from server.events import push_threadsafe
from services import assistant, library, session

logger = logging.getLogger("server.reading")

router = APIRouter(tags=["reading"])

_TICK_SECONDS = 5
_FOCUS_DURATION_S = 30 * 60
# Bornage des entrées client (S4) : longueurs maximales acceptées.
_MAX_QUESTION_CHARS = 4000
_MAX_SNIPPET_CHARS = 1000
# Cadence d'intervention par mode : (dwell avant déclenchement, cooldown global).
_MODE_POLICY = {
    "discret": (float("inf"), float("inf")),
    "normal": (60.0, 120.0),
    "coach": (35.0, 80.0),
}
# Warm-up : délai d'entrée dans le document pendant lequel Gemma se tait, quel que
# soit le dwell. Sans lui, le mode par défaut (normal) déclenche dès 60 s, avant que
# le lecteur ait pu lire quoi que ce soit. Passé ce délai la première intervention
# part, puis _MODE_POLICY reprend la main. Compté depuis l'ouverture du lecteur.
_MODE_WARMUP_S = {
    "discret": float("inf"),
    "normal": 180.0,
    "coach": 90.0,
}


class ReaderMessage(BaseModel):
    """Validation S4 des messages WS entrants : types stricts, textes tronqués,
    listes bornées. Un message qui ne valide pas est ignoré (pas de fermeture)."""

    model_config = ConfigDict(extra="ignore")

    type: Literal[
        "viewport", "mode", "focus", "ask", "rephrase", "recap", "hook",
        "start_qa", "qa_answer",
    ]
    page: int | None = None
    session_id: int | None = None
    mode: str | None = None
    question: str | None = None
    answer: str | None = None
    selected_snippets: list[str] = []

    @field_validator("page", mode="before")
    @classmethod
    def _tolerant_page(cls, value):
        # Une page invalide ne doit pas jeter tout le message : None -> page courante.
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @field_validator("session_id", mode="before")
    @classmethod
    def _positive_session(cls, value):
        try:
            sid = int(value)
        except (TypeError, ValueError):
            return None
        return sid if sid > 0 else None

    @field_validator("question", "answer", mode="before")
    @classmethod
    def _bounded_text(cls, value):
        if value is None:
            return None
        return str(value)[:_MAX_QUESTION_CHARS]

    @field_validator("selected_snippets", mode="before")
    @classmethod
    def _bounded_snippets(cls, value):
        if not isinstance(value, list):
            return []
        cleaned = [str(s).strip()[:_MAX_SNIPPET_CHARS] for s in value if str(s).strip()]
        return cleaned[:5]


@router.websocket("/reader/{doc_id}/stream")
async def reader_stream(ws: WebSocket, doc_id: int) -> None:
    await ws.accept()
    loop = asyncio.get_running_loop()
    out: asyncio.Queue = asyncio.Queue()
    state = {
        "page": 1,
        "since": loop.time(),
        "opened_at": loop.time(),  # début de lecture -> warm-up (cf. _MODE_WARMUP_S)
        "last_intervention": 0.0,
        "fired": set(),
        "mode": "normal",
        "warmed_up": False,  # warm-up de début de lecture écoulé (verrou une fois posé)
        "focus_until": 0.0,
        "qa_qid": None,
        "qa_question_type": None,  # type de la question Q&R courante (jauges type-aware)
        "session_id": None,
        "dwell": {},  # page -> secondes cumulées
        "visits": {1: 1},  # page -> nb de visites
        "questions": {},  # page -> nb de questions libres posées à Gemma
        "exchanges": [],  # historique [{question, answer}] (6 derniers)
        "recent_qtypes": [],  # types de questions Q&R récents (anti-répétition, 5 max)
        "gated": False,  # question automatique bloquante en cours (scroll verrouillé côté UI)
        "live_gauges": None,  # jauges métacognitives live (services.session.LiveGauges)
    }
    state["live_gauges"] = await loop.run_in_executor(None, session.LiveGauges)
    # Nombre de pages du document (si connu) pour borner les entrées client (S4).
    doc_row = await loop.run_in_executor(None, get_document, doc_id)
    page_count = int(doc_row["page_count"] or 0) if doc_row else 0

    def clamp_page(raw) -> int:
        try:
            page = int(raw if raw is not None else state["page"])
        except (TypeError, ValueError):
            page = state["page"]
        page = max(1, page)
        return min(page, page_count) if page_count else page

    def make_callbacks():
        def on_success(result: dict) -> None:
            push_threadsafe(loop, out, {
                "type": "answer",
                "answer": result.get("answer", ""),
                "highlights": result.get("highlights", []),
            })

        def on_error(message: str) -> None:
            push_threadsafe(loop, out, {"type": "error", "message": str(message)})

        return on_success, on_error

    def emit_question(result: dict, page: int, sid, gated: bool) -> None:
        """Persiste une question Q&R générée et l'émet vers le client.

        `gated=True` -> question automatique bloquante (l'UI verrouille le scroll
        sur la page-contexte jusqu'à la bonne réponse)."""
        qtype = result.get("question_type") or "open"
        try:
            state["qa_qid"] = save_question(
                doc_id, "page", f"Page {page}", page, page,
                {
                    "question": result.get("question", ""),
                    "question_type": qtype,
                    "choices": result.get("choices"),
                    # Réponse canonique du LLM : persistée pour générer des QCM
                    # (distracteurs) lors d'une session de quiz ultérieure.
                    "answer": result.get("expected_answer", ""),
                },
                session_id=sid,
            )
        except Exception:  # pragma: no cover - persistance best-effort
            state["qa_qid"] = None
        state["qa_question_type"] = qtype
        state["recent_qtypes"].append(qtype)
        del state["recent_qtypes"][:-5]
        event = {
            "type": "gated_question" if gated else "qa_question",
            "question": result.get("question", ""),
            "choices": result.get("choices"),
            "question_type": qtype,
        }
        if gated:
            state["gated"] = True
            event["page"] = page
        push_threadsafe(loop, out, event)

    async def _sender() -> None:
        while True:
            event = await out.get()
            if event is None:
                return
            await ws.send_json(event)

    async def _ticker() -> None:
        while True:
            await asyncio.sleep(_TICK_SECONDS)
            now = loop.time()
            dwell_trigger, cooldown = _MODE_POLICY.get(state["mode"], _MODE_POLICY["normal"])
            page = state["page"]
            if state["gated"]:
                # Une question bloquante est en cours : pas de nouvelle intervention.
                continue
            if now < state["focus_until"]:
                continue
            # Warm-up : silence tant que le lecteur entre dans le document. Ne concerne
            # que le tout début de lecture — une fois le délai passé, il l'est pour la
            # session entière et la cadence par mode gouverne seule.
            if not state["warmed_up"]:
                if now - state["opened_at"] < _MODE_WARMUP_S.get(state["mode"], 180.0):
                    continue
                state["warmed_up"] = True
            if page in state["fired"]:
                continue
            if now - state["since"] < dwell_trigger:
                continue
            if now - state["last_intervention"] < cooldown:
                continue
            state["fired"].add(page)
            state["last_intervention"] = now
            # Gemma inspecte la page : l'UI tourne la bulle vers le PDF.
            push_threadsafe(loop, out, {"type": "scanning", "active": True})
            gauges = state["live_gauges"].snapshot() if state["live_gauges"] else {}
            context = await loop.run_in_executor(
                None,
                lambda: assistant.build_intervention_context(
                    doc_id, page,
                    dwell_s=now - state["since"],
                    visits=state["visits"].get(page, 1),
                    questions_on_page=state["questions"].get(page, 0),
                    mode=state["mode"],
                    gauges=gauges,
                ),
            )

            qa_gauges = state["live_gauges"].snapshot() if state["live_gauges"] else {}

            def on_ok(decision: dict | None, _page=page, _sid=state["session_id"], _gauges=qa_gauges) -> None:
                # Fin de l'inspection : la bulle revient face à l'utilisateur.
                push_threadsafe(loop, out, {"type": "scanning", "active": False})
                if not (decision and decision.get("should_intervene")):
                    return
                # Question automatique -> Q&R structurée et BLOQUANTE : on régénère
                # une vraie question évaluable (réponse attendue) plutôt que la
                # question libre de l'intervention, et l'UI verrouille le scroll.
                if decision.get("kind") == "ask_question":
                    assistant.generate_page_question(
                        doc_id, _page,
                        lambda result, p=_page, s=_sid: emit_question(result, p, s, gated=True),
                        lambda _m: None,
                        session_gauges=_gauges,
                        recent_question_types=list(state["recent_qtypes"]),
                    )
                    return
                push_threadsafe(loop, out, {
                    "type": "intervention",
                    "message": decision.get("message", ""),
                    "question": decision.get("question", ""),
                    "kind": decision.get("kind", "offer_help"),
                    "highlights": decision.get("highlights", []),
                })

            def on_decide_error(_m: str) -> None:
                push_threadsafe(loop, out, {"type": "scanning", "active": False})

            try:
                decide_intervention_async(context, on_ok, on_decide_error)
            except Exception as exc:  # pragma: no cover
                push_threadsafe(loop, out, {"type": "scanning", "active": False})
                logger.debug("Intervention impossible : %s", exc)

    sender_task = asyncio.create_task(_sender())
    ticker_task = asyncio.create_task(_ticker())

    try:
        while True:
            raw = await ws.receive_json()
            try:
                msg = ReaderMessage.model_validate(raw)
            except ValidationError:
                continue  # message inconnu/malformé : ignoré, le canal reste ouvert
            kind = msg.type
            page = clamp_page(msg.page)

            if kind == "viewport":
                sid = msg.session_id
                if sid:
                    state["session_id"] = sid
                    if state["live_gauges"] is not None:
                        state["live_gauges"].session_id = sid
                now = loop.time()
                if page != state["page"]:
                    state["dwell"][state["page"]] = state["dwell"].get(state["page"], 0.0) + (now - state["since"])
                    state["page"] = page
                    state["since"] = now
                    state["visits"][page] = state["visits"].get(page, 0) + 1
                continue

            if kind == "mode":
                mode = str(msg.mode or "normal")
                state["mode"] = mode if mode in _MODE_POLICY else "normal"
                await out.put({"type": "system", "message": f"Mode : {state['mode']}"})
                continue

            if kind == "focus":
                now = loop.time()
                if now < state["focus_until"]:
                    state["focus_until"] = 0.0
                    await out.put({"type": "system", "message": "Mode focus désactivé."})
                else:
                    state["focus_until"] = now + _FOCUS_DURATION_S
                    await out.put({"type": "system", "message": "Mode focus activé (30 min sans interruption)."})
                continue

            on_success, on_error = make_callbacks()

            if kind == "ask":
                question = (msg.question or "").strip()
                if not question:
                    continue
                state["questions"][page] = state["questions"].get(page, 0) + 1
                recent_exchanges = list(state["exchanges"])
                session_gauges = state["live_gauges"].snapshot() if state["live_gauges"] else {}
                selected_snippets = msg.selected_snippets
                await out.put({"type": "loading"})

                def on_ask_success(result: dict, _q=question, _page=page, _sid=state["session_id"]) -> None:
                    if state["live_gauges"] is not None:
                        state["live_gauges"].apply(result)
                    answer = result.get("answer", "")
                    state["exchanges"].append({"question": _q, "answer": answer})
                    del state["exchanges"][:-6]  # ne garder que les 6 derniers échanges
                    if answer:
                        try:
                            save_assistant_exchange(doc_id, _page, _q, answer, session_id=_sid)
                        except Exception:  # pragma: no cover - persistance best-effort
                            pass
                    on_success(result)

                assistant.answer_question(
                    doc_id, page, question, on_ask_success, on_error,
                    recent_exchanges=recent_exchanges,
                    session_gauges=session_gauges,
                    selected_snippets=selected_snippets,
                )
            elif kind == "rephrase":
                await out.put({"type": "loading"})
                assistant.rephrase_page(doc_id, page, on_success, on_error)
            elif kind == "recap":
                await out.put({"type": "loading"})
                assistant.chapter_recap(doc_id, page, on_success, on_error)
            elif kind == "hook":
                await out.put({"type": "loading"})
                assistant.curiosity_hook(doc_id, page, on_success, on_error)
            elif kind == "start_qa":
                sid = msg.session_id
                await out.put({"type": "loading"})
                qa_gauges = state["live_gauges"].snapshot() if state["live_gauges"] else {}
                assistant.generate_page_question(
                    doc_id, page,
                    lambda result, _page=page, _sid=sid: emit_question(result, _page, _sid, gated=False),
                    on_error,
                    session_gauges=qa_gauges,
                    recent_question_types=list(state["recent_qtypes"]),
                )
            elif kind == "qa_answer":
                sid = msg.session_id
                question = msg.question or ""
                answer = (msg.answer or "").strip()
                if not answer:
                    continue
                qid = state.get("qa_qid")
                await out.put({"type": "loading"})

                def on_eval(ev: dict, _sid=sid, _qid=qid, _answer=answer, _page=page) -> None:
                    # Type de la question -> jauges type-aware (curiosité ≠ contexte).
                    ev["question_type"] = state.get("qa_question_type")
                    if state["live_gauges"] is not None:
                        state["live_gauges"].apply(ev)
                    try:
                        save_answer(
                            question_id=_qid, user_id=DEFAULT_USER_ID, answer_text=_answer,
                            verdict=ev.get("verdict"), feedback=ev.get("feedback"), session_id=_sid,
                        )
                    except Exception:  # pragma: no cover - persistance best-effort
                        pass
                    # Flashcard auto-portante créée à la bonne réponse (le LLM exclut
                    # déjà metacognition/anticipation -> flashcard=null).
                    flashcard_created = False
                    card = ev.get("flashcard")
                    if card and ev.get("verdict") in ("correct", "partial"):
                        try:
                            save_flashcard(
                                DEFAULT_USER_ID,
                                question_id=_qid,
                                front=card.get("front", ""),
                                back=card.get("back", ""),
                                tags=card.get("tags"),
                                difficulty=card.get("difficulty") or 2,
                                source="auto",
                                document_id=doc_id,
                                session_id=_sid,
                            )
                            flashcard_created = True
                        except Exception:  # pragma: no cover - persistance best-effort
                            pass
                    # Idée principale présente (correct/partial) -> fin du verrouillage.
                    if ev.get("verdict") in ("correct", "partial"):
                        state["gated"] = False
                    push_threadsafe(loop, out, {
                        "type": "qa_feedback",
                        "verdict": ev.get("verdict", ""),
                        "feedback": ev.get("feedback", ""),
                        "hint": ev.get("hint", ""),
                        "completion": ev.get("completion", ""),
                        # Passages de la page qui justifient le verdict / corrigent
                        # l'erreur : surlignés comme pour une réponse libre.
                        "highlights": ev.get("highlights", []),
                        "flashcard_created": flashcard_created,
                    })

                assistant.evaluate_page_answer(doc_id, page, question, answer, on_eval, on_error)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        logger.warning("WebSocket reader erreur : %s", exc)
    finally:
        ticker_task.cancel()
        # Flush du dwell de la page courante + persistance fine par page.
        try:
            state["dwell"][state["page"]] = state["dwell"].get(state["page"], 0.0) + (loop.time() - state["since"])
            if state["session_id"] and state["dwell"]:
                save_page_dwell(
                    int(state["session_id"]),
                    {int(k): round(v, 1) for k, v in state["dwell"].items()},
                    {int(k): int(v) for k, v in state["visits"].items()},
                )
        except Exception:  # pragma: no cover - persistance best-effort
            pass
        # Marque-page : mémorise la dernière page vue pour la signaler à la réouverture.
        try:
            update_last_page(doc_id, int(state["page"]))
        except Exception:  # pragma: no cover - persistance best-effort
            pass
        # Stockage borné : ne garder que la vignette, jeter les pages de la session.
        try:
            library.clear_reader_cache(doc_id)
        except Exception:  # pragma: no cover - best-effort
            pass
        await out.put(None)
        await sender_task
