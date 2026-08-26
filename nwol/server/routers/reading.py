# server/routers/reading.py — Canal temps réel du lecteur (WebSocket).
#
# client -> serveur : {"type":"ask","question","page"} | {"type":"rephrase","page"}
#                     {"type":"recap","page"} | {"type":"hook","page"}
#                     {"type":"viewport","page"} | {"type":"mode","mode"} | {"type":"focus"}
#                     {"type":"activity","hidden":bool}  # fenêtre masquée / app au
#                       second plan -> alimente la dérive passive d'attention
# serveur -> client : {"type":"loading"} | {"type":"answer","answer","highlights"}
#                     {"type":"error","message"} | {"type":"intervention",...}
#                     {"type":"system","message"}
#                     {"type":"scanning","active":bool}  # Gemma inspecte la page (décide
#                       d'intervenir ou non) -> l'UI tourne la bulle vers le PDF
#                     {"type":"qa_question"|"gated_question","question","choices",
#                      "question_type","mask"}  # mask = {"quote","placeholder"} du
#                       passage à cacher dans la page (rappel libre), sinon null
from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from config.settings import ASSISTANT_MODES, FOCUS_DEFAULT_MIN
from db.answers import save_answer
from db.documents import get_document, update_last_page
from db.flashcards import get_due_flashcards, save_flashcard
from db.page_dwell import save_page_dwell
from db.questions import save_assistant_exchange, save_question
from db.user import DEFAULT_USER_ID
from llm.ollama_client import cancel_pending_generations, decide_intervention_async
from metacog.reflection import augment_evaluation_with_response_signals
from server.events import push_threadsafe
from services import assistant, library, session
from services.intervention import AssistantInterventionPolicy
from services.session_memory import SessionMemory

logger = logging.getLogger("server.reading")

router = APIRouter(tags=["reading"])

_TICK_SECONDS = 5
_FOCUS_DURATION_S = FOCUS_DEFAULT_MIN * 60
# Q&R de la session relayées au LLM (génération ET évaluation) : assez pour qu'il
# se réfère à ce qui vient d'être travaillé, assez peu pour ne pas gonfler le prompt.
_MAX_HISTORY = 5
_MAX_HISTORY_TEXT_CHARS = 240
# Bornage des entrées client (S4) : longueurs maximales acceptées.
_MAX_QUESTION_CHARS = 4000
_MAX_SNIPPET_CHARS = 1000


class ReaderMessage(BaseModel):
    """Validation S4 des messages WS entrants : types stricts, textes tronqués,
    listes bornées. Un message qui ne valide pas est ignoré (pas de fermeture)."""

    model_config = ConfigDict(extra="ignore")

    type: Literal[
        "viewport", "mode", "focus", "ask", "rephrase", "recap", "hook",
        "start_qa", "qa_answer", "activity",
    ]
    page: int | None = None
    hidden: bool = False
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
        "mode": "normal",
        "focus_until": 0.0,
        "qa_qid": None,
        "qa_question_type": None,  # type de la question Q&R courante (jauges type-aware)
        "qa_text": "",  # énoncé de la question Q&R courante (historique de session)
        "session_id": None,
        "exchanges": [],  # historique [{question, answer}] (6 derniers)
        "recent_qtypes": [],  # types de questions Q&R récents (anti-répétition, 5 max)
        "gated": False,  # question automatique bloquante en cours (scroll verrouillé côté UI)
        "live_gauges": None,  # jauges métacognitives live (services.session.LiveGauges)
        "generating": False,  # une génération LLM est en vol (Gemma est occupée)
        "away": False,  # fenêtre masquée / application au second plan
        "qa_sent_at": 0.0,  # émission de la question courante -> temps de réponse
        "consecutive_incorrect": 0,  # série d'erreurs en cours (modèle d'attention)
        "qa_history": [],  # Q&R de la session relayées au LLM (5 dernières)
        "pages_seen": 0,  # pages distinctes vues au dernier tick (progression)
    }
    state["live_gauges"] = await loop.run_in_executor(None, session.LiveGauges)
    # Dwell / visites / questions par page : mémoire de session partagée, qui
    # alimente aussi la politique d'intervention (services/intervention.py).
    memory = SessionMemory()
    memory.on_page_view(1)
    state["pages_seen"] = len(memory.pages_seen())
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

    def refresh_busy() -> None:
        """La politique se tait tant que Gemma travaille OU qu'une réponse est due.

        Deux raisons distinctes, un seul drapeau : une génération en vol (réponse,
        reformulation, question…) et une question bloquante en attente. Avant, seule
        la seconde comptait — une décision d'intervention pouvait donc partir
        pendant que l'étudiant attendait sa réponse."""
        policy.set_busy(bool(state["generating"] or state["gated"]))

    def start_generation() -> None:
        state["generating"] = True
        refresh_busy()

    def end_generation() -> None:
        state["generating"] = False
        refresh_busy()

    def make_callbacks():
        def on_success(result: dict) -> None:
            end_generation()
            push_threadsafe(loop, out, {
                "type": "answer",
                "answer": result.get("answer", ""),
                "highlights": result.get("highlights", []),
            })

        def on_error(message: str) -> None:
            end_generation()
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
        state["qa_text"] = result.get("question", "")
        # Départ du chronomètre de réponse : il alimente le modèle d'attention
        # (`response_time_ms`), qui l'attendait sans jamais le recevoir.
        state["qa_sent_at"] = time.monotonic()
        state["recent_qtypes"].append(qtype)
        del state["recent_qtypes"][:-5]
        state["generating"] = False
        event = {
            "type": "gated_question" if gated else "qa_question",
            "question": result.get("question", ""),
            "choices": result.get("choices"),
            "question_type": qtype,
            # Passage à masquer dans la page (rappel libre) : citation + texte de
            # remplacement, résolus par le service. None quand il n'y a rien à cacher.
            "mask": assistant.resolve_paragraph_mask(
                doc_id, page, result.get("paragraph_mask")
            ),
        }
        if gated:
            # La politique se tait tant que l'étudiant doit répondre.
            state["gated"] = True
            event["page"] = page
        # Un seul point de bascule : la génération est finie, le verrou est posé.
        refresh_busy()
        push_threadsafe(loop, out, event)

    async def _sender() -> None:
        while True:
            event = await out.get()
            if event is None:
                return
            await ws.send_json(event)

    def request_decision(ctx: dict, on_done) -> None:
        """Habille le signal détecté par la politique puis interroge le LLM.

        Appelé depuis un thread d'exécuteur (`policy.tick`) : les lectures DB et le
        texte de page sont synchrones, et la réponse revient par `push_threadsafe`."""
        # Gemma inspecte la page : l'UI tourne la bulle vers le PDF.
        push_threadsafe(loop, out, {"type": "scanning", "active": True})

        def _finish(decision: dict | None) -> None:
            # Fin de l'inspection : la bulle revient face à l'utilisateur.
            push_threadsafe(loop, out, {"type": "scanning", "active": False})
            on_done(decision)

        try:
            full = assistant.build_intervention_context(
                doc_id, int(ctx["page"]),
                trigger=str(ctx["trigger"]),
                dwell_s=float(ctx["dwell_s"]),
                visits=int(ctx["visits"]),
                questions_on_page=int(ctx["user_questions_on_page"]),
                mode=str(ctx["mode"]),
                gauges=ctx.get("gauges") or {},
                due_flashcard_front=str(ctx.get("due_flashcard_front") or ""),
            )
            decide_intervention_async(full, _finish, lambda _m: _finish(None))
        except Exception as exc:  # pragma: no cover - le LLM reste un bonus
            logger.debug("Intervention impossible : %s", exc)
            _finish(None)

    def on_intervention(payload: dict) -> None:
        """La politique a retenu une intervention : la router vers le client."""
        page = int(payload.get("page") or state["page"])
        # Question automatique -> Q&R structurée et BLOQUANTE : on régénère une vraie
        # question évaluable (réponse attendue) plutôt que la question libre de
        # l'intervention, et l'UI verrouille le scroll.
        if payload.get("kind") == "ask_question":
            gauges = state["live_gauges"].snapshot() if state["live_gauges"] else {}
            start_generation()
            assistant.generate_page_question(
                doc_id, page,
                lambda result, p=page, s=state["session_id"]: emit_question(result, p, s, gated=True),
                lambda _m: end_generation(),
                session_gauges=gauges,
                recent_question_types=list(state["recent_qtypes"]),
                history=list(state["qa_history"]),
            )
            return
        push_threadsafe(loop, out, {
            "type": "intervention",
            "message": payload.get("message", ""),
            "question": payload.get("question", ""),
            "kind": payload.get("kind", "offer_help"),
            "highlights": payload.get("highlights", []),
            # Carte à réviser (kind == "review_flashcard") : le client l'affiche
            # directement au lieu d'un simple message.
            "flashcard": payload.get("flashcard"),
        })

    policy = AssistantInterventionPolicy(
        memory=memory,
        get_mode=lambda: state["mode"],
        get_gauges=lambda: state["live_gauges"].snapshot() if state["live_gauges"] else {},
        get_current_page=lambda: int(state["page"]),
        get_page_text=lambda page: library.page_text(doc_id, page) or "",
        request_decision=request_decision,
        on_intervention=on_intervention,
        get_due_flashcard=lambda: next(iter(get_due_flashcards(doc_id=doc_id, limit=1) or []), None),
    )

    def passive_attention(elapsed_s: float, now: float) -> None:
        """Fait vivre la jauge d'attention à partir du COMPORTEMENT de lecture.

        Sans elle, `attention` ne bougeait qu'au retour d'une évaluation LLM :
        elle mesurait la performance, jamais l'attention, et le déclencheur
        `low_attention` ne pouvait s'armer qu'après une série de mauvaises
        réponses. Tourne à chaque tick, y compris en mode focus ou discret :
        ces modes silencient les interventions, pas l'observation."""
        gauges = state["live_gauges"]
        if gauges is None:
            return
        seen = len(memory.pages_seen())
        progressed = max(0, seen - int(state["pages_seen"]))
        state["pages_seen"] = seen
        gauges.apply_reading_behaviour(
            elapsed_s=elapsed_s,
            stagnant_s=memory.current_dwell(now),
            pages_progressed=progressed,
            away=bool(state["away"]),
        )

    async def _ticker() -> None:
        last_tick = time.monotonic()
        while True:
            await asyncio.sleep(_TICK_SECONDS)
            now = time.monotonic()
            elapsed, last_tick = now - last_tick, now
            # Écrit (au plus une fois par minute) dans session_gauges : executor.
            await loop.run_in_executor(None, passive_attention, elapsed, now)
            if state["gated"] or now < state["focus_until"]:
                # Question bloquante en cours ou mode focus : Gemma se tait.
                continue
            # `tick` lit le texte de page et la DB : jamais dans la boucle asyncio.
            await loop.run_in_executor(None, policy.tick)

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
                        # Fige l'amorce de la session en base : la finalisation
                        # s'en sert pour ne remonter que les jauges exercées.
                        state["live_gauges"].attach_session(sid)
                if page != state["page"]:
                    state["page"] = page
                    memory.on_page_view(page)
                continue

            if kind == "activity":
                # Fenêtre masquée ou application au second plan : l'étudiant n'est
                # pas devant sa page. Seul signal d'absence dont on dispose.
                state["away"] = bool(msg.hidden)
                continue

            if kind == "mode":
                mode = str(msg.mode or "normal")
                state["mode"] = mode if mode in ASSISTANT_MODES else "normal"
                await out.put({"type": "system", "message": f"Mode : {state['mode']}"})
                continue

            if kind == "focus":
                now = time.monotonic()
                if now < state["focus_until"]:
                    state["focus_until"] = 0.0
                    await out.put({"type": "system", "message": "Mode focus désactivé."})
                else:
                    state["focus_until"] = now + _FOCUS_DURATION_S
                    await out.put({
                        "type": "system",
                        "message": f"Mode focus activé ({FOCUS_DEFAULT_MIN} min sans interruption).",
                    })
                continue

            on_success, on_error = make_callbacks()

            if kind == "ask":
                question = (msg.question or "").strip()
                if not question:
                    continue
                memory.on_user_question(page, question)
                recent_exchanges = list(state["exchanges"])
                session_gauges = state["live_gauges"].snapshot() if state["live_gauges"] else {}
                selected_snippets = msg.selected_snippets
                await out.put({"type": "loading"})

                def on_ask_success(result: dict, _q=question, _page=page, _sid=state["session_id"]) -> None:
                    end_generation()
                    if state["live_gauges"] is not None:
                        state["live_gauges"].apply(result)
                    answer = result.get("answer", "")
                    state["exchanges"].append({"question": _q, "answer": answer})
                    del state["exchanges"][:-6]  # ne garder que les 6 derniers échanges
                    if answer:
                        try:
                            save_assistant_exchange(doc_id, _page, _q, answer, session_id=_sid)
                        except Exception:  # persistance best-effort
                            logger.debug("Persistance de l'échange assistant ignorée", exc_info=True)
                    on_success(result)

                start_generation()
                assistant.answer_question(
                    doc_id, page, question, on_ask_success, on_error,
                    recent_exchanges=recent_exchanges,
                    session_gauges=session_gauges,
                    selected_snippets=selected_snippets,
                )
            elif kind == "rephrase":
                await out.put({"type": "loading"})
                start_generation()
                assistant.rephrase_page(doc_id, page, on_success, on_error)
            elif kind == "recap":
                await out.put({"type": "loading"})
                start_generation()
                assistant.chapter_recap(doc_id, page, on_success, on_error)
            elif kind == "hook":
                await out.put({"type": "loading"})
                start_generation()
                assistant.curiosity_hook(doc_id, page, on_success, on_error)
            elif kind == "start_qa":
                sid = msg.session_id
                await out.put({"type": "loading"})
                qa_gauges = state["live_gauges"].snapshot() if state["live_gauges"] else {}
                start_generation()
                assistant.generate_page_question(
                    doc_id, page,
                    lambda result, _page=page, _sid=sid: emit_question(result, _page, _sid, gated=False),
                    on_error,
                    session_gauges=qa_gauges,
                    recent_question_types=list(state["recent_qtypes"]),
                    history=list(state["qa_history"]),
                )
            elif kind == "qa_answer":
                sid = msg.session_id
                question = msg.question or ""
                answer = (msg.answer or "").strip()
                if not answer:
                    continue
                qid = state.get("qa_qid")
                await out.put({"type": "loading"})

                def on_eval(ev: dict, _sid=sid, _qid=qid, _answer=answer, _page=page, _q=question) -> None:
                    end_generation()
                    # Signaux dérivés de la FORME de la réponse (longueur, questions
                    # posées, connecteurs, analogies) : ils enrichissent curiosité et
                    # créativité que le LLM seul sous-estime.
                    ev = augment_evaluation_with_response_signals(ev, _answer)
                    # Type de la question -> jauges type-aware (curiosité ≠ contexte).
                    ev["question_type"] = state.get("qa_question_type")
                    verdict = ev.get("verdict")
                    # Deux signaux comportementaux que le modèle d'attention attend
                    # depuis toujours et que personne ne lui donnait : le temps mis à
                    # répondre, et la série d'erreurs en cours.
                    sent_at = float(state.get("qa_sent_at") or 0.0)
                    response_time_ms = (
                        int(max(0.0, time.monotonic() - sent_at) * 1000) if sent_at else None
                    )
                    state["consecutive_incorrect"] = (
                        int(state["consecutive_incorrect"]) + 1 if verdict == "incorrect" else 0
                    )
                    if state["live_gauges"] is not None:
                        state["live_gauges"].apply(
                            ev,
                            response_time_ms=response_time_ms,
                            consecutive_incorrect=int(state["consecutive_incorrect"]),
                        )
                    memory.on_answer(_page, verdict)
                    # Q&R de la session : relayée aux prochains prompts (génération
                    # comme évaluation), qui la citaient sans jamais la recevoir.
                    state["qa_history"].append({
                        "question": str(_q or state.get("qa_text") or "")[:_MAX_HISTORY_TEXT_CHARS],
                        "question_type": ev.get("question_type") or "",
                        "answer": _answer[:_MAX_HISTORY_TEXT_CHARS],
                        "verdict": verdict or "",
                    })
                    del state["qa_history"][:-_MAX_HISTORY]
                    try:
                        save_answer(
                            question_id=_qid, user_id=DEFAULT_USER_ID, answer_text=_answer,
                            verdict=verdict, feedback=ev.get("feedback"), session_id=_sid,
                            response_time_ms=response_time_ms,
                        )
                    except Exception:  # persistance best-effort
                        logger.debug("Persistance de la réponse ignorée", exc_info=True)
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
                        except Exception:  # persistance best-effort
                            logger.debug("Création de la flashcard automatique ignorée", exc_info=True)
                    # Idée principale présente (correct/partial) -> fin du verrouillage.
                    if verdict in ("correct", "partial"):
                        state["gated"] = False
                        refresh_busy()
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

                start_generation()
                assistant.evaluate_page_answer(
                    doc_id, page, question, answer, on_eval, on_error,
                    question_type=state.get("qa_question_type") or "",
                    # La question persistée porte sa réponse canonique et ses
                    # propositions : le service s'en sert pour corriger.
                    question_id=qid,
                    history=list(state["qa_history"]),
                )
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        logger.warning("WebSocket reader erreur : %s", exc)
    finally:
        ticker_task.cancel()
        # Le lecteur est fermé : purger la file LLM. Sans cela, les générations
        # lancées pour ce document continuent d'occuper l'unique worker et
        # retardent la première réponse du document suivant.
        try:
            cancel_pending_generations()
        except Exception:  # pragma: no cover - best-effort
            logger.debug("Annulation des générations en attente ignorée", exc_info=True)
        # Flush du dwell de la page courante + persistance fine par page.
        try:
            memory.flush()
            if state["session_id"] and memory.dwell_by_page:
                save_page_dwell(
                    int(state["session_id"]),
                    {int(k): round(v, 1) for k, v in memory.dwell_by_page.items()},
                    {int(k): int(v) for k, v in memory.visits_by_page.items()},
                )
        except Exception:  # pragma: no cover - persistance best-effort
            logger.debug("Persistance du dwell ignorée", exc_info=True)
        # Marque-page : mémorise la dernière page vue pour la signaler à la réouverture.
        try:
            update_last_page(doc_id, int(state["page"]))
        except Exception:  # persistance best-effort
            logger.debug("Persistance du marque-page ignorée", exc_info=True)
        # Stockage borné : ne garder que la vignette, jeter les pages de la session.
        try:
            library.clear_reader_cache(doc_id)
        except Exception:  # best-effort : le cache sera purgé au prochain passage
            logger.debug("Purge du cache lecteur ignorée", exc_info=True)
        await out.put(None)
        await sender_task
