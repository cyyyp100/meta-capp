# server/routers/reading.py — Canal temps réel du lecteur (WebSocket).
#
# client -> serveur : {"type":"ask","question","page"} | {"type":"rephrase","page"}
#                     {"type":"recap","page"} | {"type":"hook","page"}
#                     {"type":"viewport","page"} | {"type":"mode","mode"} | {"type":"focus"}
#                     {"type":"activity","hidden":bool,"engaged":bool}  # fenêtre
#                       masquée / app au second plan, ou (engaged) défilement /
#                       souris / clavier -> alimentent la dérive passive d'attention
#                     {"type":"engage","action":"highlight"|"note"}  # l'élève a
#                       surligné / annoté -> crédit d'attention (une question
#                       posée ou une réponse écrite sont comptées ici même)
#                     {"type":"pause","source":"manual"|"suggested","minutes":int|null}
#                       # pause OUVERTE (bouton de l'élève, ou carte de Clikoda
#                       acceptée : minutes = durée conseillée) -> tout est figé :
#                       ni observation, ni intervention, ni horloge (services/pause)
#                     {"type":"resume"}  # fin de la pause -> enregistrée en base
#                     {"type":"start_reading","session_id","page",
#                      "warmup":[{"card_id","front_ms","back_ms"}]}  # sas d'entrée
#                       franchi -> départ du warm-up de la première question
#                       (aucune intervention avant) ; `warmup` = temps passés sur
#                       chaque face de la révision éclair (services/warmup)
# serveur -> client : {"type":"loading","estimate_s":int|null}  # attente annoncée
#                       (« au plus ~N min », services/llm_models.wait_estimate_s) ;
#                       republié quand la tâche sort de la file avec un budget
#                       différent. null = rien à annoncer (machine rapide).
#                     {"type":"answer","answer","highlights"}
#                     {"type":"error","message","cancelled":bool} | {"type":"intervention",...}
#                     {"type":"system","message"}
#                     {"type":"scanning","active":bool}  # Clikoda inspecte la page (décide
#                       d'intervenir ou non) -> l'UI tourne la bulle vers le PDF
#                     {"type":"qa_question"|"gated_question","question","choices",
#                      "question_type","mask","zone","page","session_hint"}  # mask =
#                       {"quote","placeholder"} du passage à cacher dans la page
#                       (rappel libre), sinon null ; zone = {"quote"} du passage
#                       précis sur lequel porte la question (le lecteur le
#                       cadre à l'écran), sinon null ; session_hint = conseil de
#                       régulation de séance (pause courte…), vide la plupart
#                       du temps
from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator, Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from config.settings import (
    ASSISTANT_DEFAULT_MODE,
    ASSISTANT_MODES,
    ATTENTION_ENGAGEMENT_CREDIT,
    FOCUS_DEFAULT_MIN,
    PAUSE_DEFAULT_MIN,
    PAUSE_MAX_MIN,
    SESSION_HEARTBEAT_S,
    WARMUP_MAX_CARDS,
)
from db.answers import save_answer
from db.documents import get_document, update_last_page
from db.flashcards import get_due_flashcards
from db.page_dwell import save_page_dwell
from db.questions import (
    get_recent_assistant_exchanges,
    save_assistant_exchange,
    save_question,
)
from db.session_pauses import save_pause
from db.sessions import get_session, update_session_progress
from db.user import DEFAULT_USER_ID
from i18n import t
from llm.ollama_client import (
    cancel_pending_generations,
    close_caller_slot,
    decide_intervention_async,
    is_cancelled_error,
    open_caller_slot,
)
from metacog.reflection import augment_evaluation_with_response_signals
from server.events import push_threadsafe
from services import (
    assistant,
    flashcards as flashcards_service,
    library,
    llm_models,
    pdf_rag,
    session,
    session_memory,
    warmup,
)
from services.intervention import AssistantInterventionPolicy
from services.pause import PAUSE_SOURCES, PauseTracker, attention_credit
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
# Temps d'une face de la révision éclair : au-delà d'une heure, ce n'est plus
# une mesure (onglet oublié, machine en veille) — et c'est déjà « drifted ».
_MAX_WARMUP_FACE_MS = 3_600_000
# Demandes de l'élève sans objet pendant une pause (le lecteur est masqué).
_PAUSED_ACTIONS = frozenset({"ask", "rephrase", "recap", "hook", "start_qa", "qa_answer"})


class ReaderMessage(BaseModel):
    """Validation S4 des messages WS entrants : types stricts, textes tronqués,
    listes bornées. Un message qui ne valide pas est ignoré (pas de fermeture)."""

    model_config = ConfigDict(extra="ignore")

    type: Literal[
        "viewport", "mode", "focus", "ask", "rephrase", "recap", "hook",
        "start_qa", "qa_answer", "activity", "engage", "pause", "resume", "start_reading",
    ]
    page: int | None = None
    hidden: bool = False
    engaged: bool = False
    action: str | None = None
    minutes: int | None = None
    source: str = "manual"
    session_id: int | None = None
    mode: str | None = None
    question: str | None = None
    answer: str | None = None
    selected_snippets: list[str] = []
    warmup: list[dict] = []

    @field_validator("page", mode="before")
    @classmethod
    def _tolerant_page(cls, value):
        # Une page invalide ne doit pas jeter tout le message : None -> page courante.
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @field_validator("minutes", mode="before")
    @classmethod
    def _bounded_minutes(cls, value):
        # Durée bornée côté serveur (S4) : un client ne décide pas d'un silence
        # d'une heure. None -> durée par défaut, décidée à la lecture.
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            return None
        return max(0, min(minutes, PAUSE_MAX_MIN))

    @field_validator("source", mode="before")
    @classmethod
    def _known_source(cls, value):
        # Une source inconnue ne jette pas la pause : elle compte comme manuelle.
        return value if value in PAUSE_SOURCES else "manual"

    @field_validator("action", mode="before")
    @classmethod
    def _known_action(cls, value):
        # Un geste inconnu ne crédite rien (le message reste valide, sans effet).
        return value if value in ATTENTION_ENGAGEMENT_CREDIT else None

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

    @field_validator("warmup", mode="before")
    @classmethod
    def _bounded_warmup(cls, value):
        # Temps de la révision éclair : entiers bornés, nombre de cartes borné.
        # Une carte malformée est écartée, pas le message.
        if not isinstance(value, list):
            return []
        cleaned: list[dict] = []
        for item in value[:WARMUP_MAX_CARDS]:
            try:
                card = {
                    "card_id": int(item["card_id"]),
                    "front_ms": max(0, min(int(item["front_ms"]), _MAX_WARMUP_FACE_MS)),
                    "back_ms": max(0, min(int(item["back_ms"]), _MAX_WARMUP_FACE_MS)),
                }
            except (KeyError, TypeError, ValueError):
                continue
            cleaned.append(card)
        return cleaned


@router.post("/reader/cancel")
def cancel_generations() -> dict:
    """Coupe TOUTE génération LLM (en file et en vol). Aucune entrée.

    « ← Bibliothèque » depuis le sas d'entrée : l'accroche de curiosité et la
    fiche du document sont peut-être en vol, et Ollama occupe la machine. La
    fermeture du WebSocket déclenche déjà cette coupure (cf. le `finally` de
    `reader_stream`), mais elle n'arrive qu'APRÈS la navigation, quand le
    serveur constate la déconnexion — le clic, lui, doit couper tout de suite.
    Un seul mécanisme derrière les deux chemins : `cancel_pending_generations`."""
    cancel_pending_generations()
    return {"cancelled": True}


@router.websocket("/reader/{doc_id}/stream")
async def reader_stream(ws: WebSocket, doc_id: int) -> None:
    await ws.accept()
    loop = asyncio.get_running_loop()
    out: asyncio.Queue = asyncio.Queue()
    state = {
        "page": 1,
        "mode": ASSISTANT_DEFAULT_MODE,
        "focus_until": 0.0,
        "qa_qid": None,
        "qa_question_type": None,  # type de la question Q&R courante (jauges type-aware)
        "qa_text": "",  # énoncé de la question Q&R courante (historique de session)
        "session_id": None,
        # Historique [{question, answer}] (6 derniers), RÉHYDRATÉ depuis la base
        # plus bas : ces échanges étaient déjà persistés et jamais relus, si bien
        # que rouvrir un document repartait d'une mémoire vide et que reposer la
        # même question sur la même page rendait la même réponse.
        "exchanges": [],
        "recent_qtypes": [],  # types de questions Q&R récents (anti-répétition, 5 max)
        "gated": False,  # question automatique bloquante en cours (scroll verrouillé côté UI)
        "live_gauges": None,  # jauges métacognitives live (services.session.LiveGauges)
        # Générations LLM en vol (Clikoda est occupée). Un COMPTEUR : une
        # question de l'élève et une question automatique peuvent se chevaucher,
        # et la fin de l'une ne doit pas déclarer Clikoda libre.
        "generating": 0,
        # Une question est posée et attend sa réponse (de son émission à
        # l'évaluation de la réponse), bloquante ou non (« Quiz-moi »).
        "qa_pending": False,
        # Demandes de l'élève (ask, reformuler, résumer, curiosité, Quiz-moi,
        # réponse) : une question automatique en génération le compare à sa
        # valeur de départ, et s'efface si l'élève a pris la main entre-temps.
        "user_turn": 0,
        # Dernier échange de CETTE séance — {"kind", "lines": [(qui, texte)]} —,
        # relayé à la réponse libre : une question de suivi (« développe »)
        # renvoie souvent à la question de Clikoda ou à sa correction, que les
        # `exchanges` (questions posées dans la barre) ne contiennent pas.
        # Jamais réhydraté depuis la base : un suivi parle de ce qui vient
        # d'être dit.
        "last_turn": None,
        "away": False,  # fenêtre masquée / application au second plan
        "qa_sent_at": 0.0,  # émission de la question courante -> temps de réponse
        "consecutive_incorrect": 0,  # série d'erreurs en cours (modèle d'attention)
        "qa_history": [],  # Q&R de la session relayées au LLM (5 dernières)
        "pages_read": 0,  # pages LUES au dernier tick (bonus de progression)
        "pages_read_saved": 0,  # dernier compte écrit en base (reading_sessions)
        "heartbeat_at": 0.0,  # dernier temps de lecture écrit en base (save_heartbeat)
        "pending_warmup": None,  # temps de la révision éclair, en attente du session_id
        "closed_session": None,  # séance close qu'un message a voulu rattacher (refusée)
    }
    # Pause en cours (bouton de l'élève ou carte de Clikoda acceptée) et dernière
    # recommandation du LLM. Tant qu'elle dure, tout est figé (cf. end_pause).
    pause = PauseTracker()
    state["live_gauges"] = await loop.run_in_executor(None, session.LiveGauges)
    # Mémoire de conversation d'une session à l'autre. Best-effort : un document
    # sans historique, ou une lecture qui échoue, laisse simplement la liste vide.
    try:
        state["exchanges"] = await loop.run_in_executor(
            None, get_recent_assistant_exchanges, doc_id, 6,
        )
    except Exception:  # pragma: no cover - best-effort
        logger.debug("Réhydratation de l'historique d'échanges ignorée", exc_info=True)
    # Dwell / visites / questions par page : mémoire de session partagée, qui
    # alimente aussi la politique d'intervention (services/intervention.py).
    memory = SessionMemory()
    memory.on_page_view(1)
    # Nombre de pages du document (si connu) pour borner les entrées client (S4).
    doc_row = await loop.run_in_executor(None, get_document, doc_id)
    page_count = int(doc_row["page_count"] or 0) if doc_row else 0
    # Index de recherche plein-document (services/pdf_rag) construit en tâche de
    # fond dès l'ouverture : la première question ne paie pas l'extraction du
    # texte. Fire-and-forget, best-effort (warm_index avale ses erreurs).
    asyncio.ensure_future(loop.run_in_executor(None, pdf_rag.warm_index, doc_id))

    def clamp_page(raw) -> int:
        try:
            page = int(raw if raw is not None else state["page"])
        except (TypeError, ValueError):
            page = state["page"]
        page = max(1, page)
        return min(page, page_count) if page_count else page

    def refresh_busy() -> None:
        """La politique se tait tant que Clikoda travaille OU qu'une réponse est due.

        Trois raisons, un seul drapeau : une génération en vol (réponse,
        reformulation, question…), une question bloquante, et une question —
        bloquante ou non — qui attend sa réponse. Avant, seule la bloquante
        comptait : une question automatique pouvait tomber par-dessus celle
        d'un « Quiz-moi » encore sans réponse."""
        policy.set_busy(bool(state["generating"] > 0 or state["gated"] or state["qa_pending"]))

    def remember_turn(kind: str, *lines: tuple[str, str]) -> None:
        """Retient le dernier échange de la séance (cf. state["last_turn"]) ;
        `lines` : (« student » | « clikoda », texte), les vides écartés."""
        kept = [(who, str(text or "").strip()) for who, text in lines if str(text or "").strip()]
        if kept:
            state["last_turn"] = {"kind": kind, "lines": kept}

    def reply(result: dict) -> None:
        """La réponse d'une demande de l'élève (question, reformulation, résumé…)."""
        push_threadsafe(loop, out, {
            "type": "answer",
            "answer": result.get("answer", ""),
            "highlights": result.get("highlights", []),
        })

    def report_error(message: str) -> None:
        """L'échec d'une demande de l'élève. Une demande annulée (bouton
        « Annuler » du panneau, ou lecteur quitté) n'est pas une panne : le
        panneau, qui a déjà rendu la main, ne la redit pas avec un « ⚠️ »."""
        cancelled = is_cancelled_error(message)
        push_threadsafe(loop, out, {
            "type": "error",
            "message": t("assistant.cancelled") if cancelled else str(message),
            "cancelled": cancelled,
        })

    def loading(task: str) -> dict:
        """Le `loading` d'une demande, avec l'attente à annoncer (ou null).

        Le chiffre vient du service (le budget TOTAL de la tâche) et nulle part
        ailleurs : l'interface l'affiche, elle n'en recalcule aucun."""
        return {"type": "loading", "estimate_s": llm_models.wait_estimate_s(task)}

    @contextmanager
    def announced(task: str) -> Iterator[None]:
        """Enfile la génération dans un CallerSlot : quand la tâche sort de la
        file, son budget est recalculé (`ollama_client._start_task_clock` — le
        calibrage du démarrage a pu révéler une machine lente entre-temps), et
        l'attente annoncée suit si elle a changé."""
        first = llm_models.wait_estimate_s(task)
        slot = open_caller_slot()

        def on_start(_budget_s: float) -> None:
            estimate = llm_models.wait_estimate_s(task)
            if estimate is not None and estimate != first:
                push_threadsafe(loop, out, {"type": "loading", "estimate_s": estimate})

        slot.on_start = on_start
        try:
            yield
        finally:
            close_caller_slot()

    def launch(
        task: str,
        start: Callable[[Callable, Callable], None],
        on_success: Callable[[dict], None],
        on_error: Callable[[str], None],
        *,
        announce: bool = True,
    ) -> None:
        """LE chemin de toute génération du lecteur.

        `start(ok, err)` enfile la tâche (un service de `services/assistant`).
        La génération est comptée en vol — la politique d'intervention se tait —
        puis décomptée UNE fois, quoi qu'il arrive : service qui lève avant
        d'enfiler, rappel en double, résultat dont le traitement lève. `busy`
        n'est recalculé qu'après le traitement : une question émise passe de
        « en génération » à « attend sa réponse » sans fenêtre où Clikoda
        paraîtrait libre.

        Avant, chaque demande tenait ce compte à la main : une réponse libre le
        décomptait deux fois (Clikoda « libre » pendant qu'une question
        automatique se préparait), et un service qui levait avant la mise en
        file le laissait à 1 — plus aucune intervention de la séance, quand ce
        n'était pas le socket lui-même qui se fermait.

        `announce` : l'attente est annoncée au client (`announced`). Pas pour
        une question automatique, que personne n'a demandée."""
        lock = threading.Lock()
        settled = False

        def settle(handler: Callable, value) -> None:
            nonlocal settled
            with lock:
                if settled:
                    return
                settled = True
            state["generating"] = max(0, state["generating"] - 1)
            try:
                handler(value)
            except Exception:
                logger.exception("Lecteur : traitement du résultat %s en échec", task)
                if handler is not on_error:
                    try:
                        on_error(t("assistant.failed"))
                    except Exception:  # pragma: no cover - le décompte est fait
                        logger.exception("Lecteur : signalement de l'échec %s impossible", task)
            finally:
                refresh_busy()

        state["generating"] += 1
        refresh_busy()
        try:
            if announce:
                with announced(task):
                    start(lambda result: settle(on_success, result), lambda message: settle(on_error, message))
            else:
                start(lambda result: settle(on_success, result), lambda message: settle(on_error, message))
        except Exception:
            logger.exception("Lecteur : génération %s impossible à lancer", task)
            settle(on_error, t("assistant.failed"))

    def emit_question(result: dict, page: int, sid, gated: bool) -> None:
        """Persiste une question Q&R générée et l'émet vers le client.

        `gated=True` -> question automatique bloquante (l'UI verrouille le scroll
        sur la page-contexte jusqu'à la bonne réponse). Appelée par `launch`,
        qui décompte la génération et recalcule `busy` après elle.

        L'événement est construit AVANT que la question soit marquée en attente :
        une question « attendue » que le client n'a jamais reçue faisait taire
        Clikoda jusqu'à la fin de la séance."""
        qtype = result.get("question_type") or "open"
        session_hint = str(result.get("session_hint") or "").strip()
        event = {
            "type": "gated_question" if gated else "qa_question",
            "question": result.get("question", ""),
            "choices": result.get("choices"),
            "question_type": qtype,
            # Conseil de régulation de séance (« ton attention est basse, fais une
            # pause courte ») : le prompt le demande sous le seuil d'attention,
            # le repli hors ligne le remplit aussi, le schéma le valide — et il
            # s'arrêtait ici, à un dict près du client. Vide la plupart du temps.
            "session_hint": session_hint,
            # Passage à masquer dans la page (rappel libre) : citation + texte de
            # remplacement, résolus par le service. None quand il n'y a rien à cacher.
            "mask": _safe_mask(result, page),
            # Zone précise visée par la question : citation que le lecteur
            # retrouve sur la page pour la cadrer entière à l'écran. Entre la
            # décision d'intervenir et l'arrivée de la question, l'étudiant a pu
            # zoomer ou défiler : c'est cette citation, pas la page, qui dit où
            # revenir. Best-effort : None -> le lecteur cadre le haut de page.
            "zone": _safe_zone(result, page),
            # Page-contexte de la question : le client y cadre la zone. Elle a
            # pu changer entre « Quiz-moi » et l'arrivée de la question.
            "page": page,
        }
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
        state["qa_pending"] = True
        remember_turn("question", ("clikoda", result.get("question", "")))
        if session_hint:
            # Conseil de régulation du LLM : une pause prise juste après le suit.
            pause.note_recommendation("session_hint")
        if gated:
            # Question bloquante : le lecteur se verrouille jusqu'à la bonne réponse.
            state["gated"] = True
        push_threadsafe(loop, out, event)

    def _safe_mask(result: dict, page: int) -> dict | None:
        try:
            return assistant.resolve_paragraph_mask(
                doc_id, page, result.get("paragraph_mask"), str(result.get("source_excerpt") or ""),
            )
        except Exception:  # le masque est un confort : sans lui, la question reste posée
            logger.warning("Masque de question non résolu", exc_info=True)
            return None

    def _safe_zone(result: dict, page: int) -> dict | None:
        try:
            return assistant.resolve_question_zone(doc_id, page, result)
        except Exception:  # pragma: no cover - la zone est un confort, jamais bloquant
            logger.debug("Zone de question non résolue", exc_info=True)
            return None

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
        # Clikoda inspecte la page : l'UI tourne la bulle vers le PDF.
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
                next_page_text=str(ctx.get("next_page_text") or ""),
                answer_lengths=list(ctx.get("answer_lengths") or []),
            )
            decide_intervention_async(full, _finish, lambda _m: _finish(None))
        except Exception as exc:  # pragma: no cover - le LLM reste un bonus
            logger.debug("Intervention impossible : %s", exc)
            _finish(None)

    def on_intervention(payload: dict) -> None:
        """La politique a retenu une intervention : la router vers le client.

        Jamais pendant une pause : la politique abandonne elle-même une décision
        revenue pendant ce temps (cf. AssistantInterventionPolicy.set_paused)."""
        pause.note_recommendation(str(payload.get("kind") or "offer_help"))
        page = int(payload.get("page") or state["page"])
        # Question automatique -> Q&R structurée et BLOQUANTE : on régénère une vraie
        # question évaluable (réponse attendue) plutôt que la question libre de
        # l'intervention, et l'UI verrouille le scroll.
        if payload.get("kind") == "ask_question":
            gauges = state["live_gauges"].snapshot() if state["live_gauges"] else {}
            turn = state["user_turn"]

            def on_auto_question(result: dict, p=page, s=state["session_id"]) -> None:
                # L'élève a pris la main pendant la génération (question posée,
                # « Quiz-moi », réponse), ou une question attend déjà sa réponse :
                # celle-ci tomberait par-dessus. Ni persistée, ni émise.
                if state["user_turn"] != turn or state["qa_pending"]:
                    logger.info("Question automatique abandonnée : l'élève a pris la main entre-temps")
                    return
                emit_question(result, p, s, gated=True)

            launch(
                "question",
                lambda ok, err: assistant.generate_page_question(
                    doc_id, page, ok, err,
                    session_gauges=gauges,
                    recent_question_types=list(state["recent_qtypes"]),
                    history=list(state["qa_history"]),
                ),
                on_auto_question,
                # Personne ne l'a demandée : son échec ne s'affiche pas.
                lambda message: logger.info("Question automatique non générée : %s", message),
                announce=False,
            )
            return
        kind = str(payload.get("kind") or "offer_help")
        remember_turn("intervention", ("clikoda", "\n".join(
            text for text in (str(payload.get("message") or ""), str(payload.get("question") or "")) if text.strip()
        )))
        push_threadsafe(loop, out, {
            "type": "intervention",
            "message": payload.get("message", ""),
            "question": payload.get("question", ""),
            "kind": kind,
            # Durée proposée par la carte de pause. Elle vient du serveur : la
            # cadence de Clikoda se règle dans config/settings.py, pas dans l'UI.
            "pause_minutes": PAUSE_DEFAULT_MIN if kind == "suggest_pause" else 0,
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

    def save_pages_read(count: int) -> None:
        """Écrit le nombre de pages LUES de la séance quand il augmente.

        Le serveur, qui mesure le temps par page (pauses exclues), est le seul
        auteur de `reading_sessions.pages_read` (services/session_memory.
        pages_read) : le tick l'écrit, `/end` y lit le compte exact de cette
        mémoire (`session_memory.track`), la fermeture du socket écrit la valeur
        finale. L'écriture ne fait que croître (`update_session_progress`) : un
        tick resté en vol dans l'exécuteur n'efface pas une valeur plus récente."""
        sid = state["session_id"]
        if not sid or count <= state["pages_read_saved"]:
            return
        try:
            update_session_progress(int(sid), pages_read=count)
            state["pages_read_saved"] = count
        except Exception:  # persistance best-effort : le prochain tick réessaie
            logger.debug("Persistance des pages lues ignorée", exc_info=True)

    def save_heartbeat(now: float, force: bool = False) -> None:
        """Écrit le temps de lecture de la séance ouverte, au plus une fois par
        SESSION_HEARTBEAT_S. Fermer le logiciel sans « Terminer » ne laisse que
        lui pour dater la clôture de la séance au démarrage suivant
        (services/session.close_abandoned_sessions). Une séance déjà close
        garde la durée que `/end` y a posée (db.sessions.update_session_progress)."""
        sid = state["session_id"]
        gauges = state["live_gauges"]
        if not sid or gauges is None:
            return
        if not force and now - state["heartbeat_at"] < SESSION_HEARTBEAT_S:
            return
        state["heartbeat_at"] = now
        try:
            update_session_progress(int(sid), duration_s=int(gauges.elapsed_s()))
        except Exception:  # persistance best-effort : le prochain battement réessaie
            logger.debug("Persistance du temps de lecture ignorée", exc_info=True)

    def passive_attention(elapsed_s: float, now: float, read: int) -> None:
        """Fait vivre la jauge d'attention à partir du COMPORTEMENT de lecture.

        Sans elle, `attention` ne bougeait qu'au retour d'une évaluation LLM :
        elle mesurait la performance, jamais l'attention, et le déclencheur
        `low_attention` ne pouvait s'armer qu'après une série de mauvaises
        réponses. Tourne à chaque tick, y compris en mode focus ou discret :
        ces modes silencient les interventions, pas l'observation.

        `read` : pages LUES à ce tick (au moins PAGE_READ_MIN_DWELL_S) — une page
        traversée en défilant n'est pas une progression."""
        progressed = max(0, read - int(state["pages_read"]))
        state["pages_read"] = read
        save_pages_read(read)
        save_heartbeat(now)
        gauges = state["live_gauges"]
        if gauges is None:
            return
        gauges.apply_reading_behaviour(
            elapsed_s=elapsed_s,
            stagnant_s=memory.stagnant_since(now),
            pages_progressed=progressed,
            away=bool(state["away"]),
        )

    def end_pause(now: float, ended_by: str):
        """Ferme la pause en cours et rend son temps à toutes les horloges.

        Dwell et stagnation (`memory`), warm-up et cooldowns (`policy`), axe des
        jauges, mode focus, chronomètre de réponse reculent de la durée de la
        pause : la lecture repart exactement d'où elle s'était arrêtée. Renvoie
        la pause terminée (services/pause), ou None s'il n'y en avait pas.

        Synchrone et appelé depuis la boucle asyncio (mono-thread) : une reprise
        répétée ne peut ni créditer ni enregistrer deux fois."""
        record = pause.stop(now, ended_by=ended_by)
        if record is None:
            return None
        paused_s = record.duration_s
        started = now - paused_s
        memory.skip(paused_s)
        policy.skip(paused_s)
        policy.set_paused(False)
        if state["live_gauges"] is not None:
            state["live_gauges"].skip(paused_s)
        if state["focus_until"] > started:
            state["focus_until"] += paused_s
        if state["qa_sent_at"]:
            # Question émise avant la pause : la pause ne compte pas dans le
            # temps de réponse. Émise PENDANT (génération déjà en vol) : le
            # chronomètre part de la reprise, quand l'élève la découvre.
            state["qa_sent_at"] = min(float(state["qa_sent_at"]) + paused_s, now)
        return record

    def persist_pause(record) -> None:
        if not state["session_id"]:
            return
        try:
            save_pause(int(state["session_id"]), record.as_row())
        except Exception:  # persistance best-effort : la lecture reprend quoi qu'il arrive
            logger.debug("Persistance de la pause ignorée", exc_info=True)

    async def credit_engagement(action: str, now: float) -> None:
        """Verse le crédit d'attention d'un geste (décidé par LiveGauges, qui
        écrit en base : exécuteur)."""
        gauges = state["live_gauges"]
        if gauges is not None:
            await loop.run_in_executor(None, gauges.credit_engagement, action, now)

    async def resume_reading(now: float) -> None:
        """Reprise : fin de pause, crédit d'attention éventuel, enregistrement.

        Le crédit (au prorata du temps pris sur la durée conseillée) est décidé par
        services/pause ; ici on ne fait que le verser. Les écritures partent en
        exécuteur."""
        record = end_pause(now, "resume")
        if record is None:
            return
        credit = attention_credit(record)
        gauges = state["live_gauges"]
        if gauges is not None and credit > 0.0:
            await loop.run_in_executor(None, gauges.recover_attention, credit)
        await loop.run_in_executor(None, persist_pause, record)

    async def attach_session(sid: int | None) -> None:
        """Rattache la séance (premier `viewport` ou `start_reading` qui la porte).

        Jamais une séance CLOSE (ou effacée) : un lecteur rouvert après
        « Terminer » — le sas de repos le remontait — se rattachait à la séance
        finie, comptait le repos comme une lecture de la page 1 et, à sa
        fermeture, écrasait le temps par page de toute la séance (« Où tu as
        ralenti ») et ajoutait ses points aux courbes de jauges. Le refus est
        retenu : le socket ne redemande pas à chaque message."""
        if not sid or sid == state["closed_session"]:
            return
        if sid != state["session_id"]:
            row = await loop.run_in_executor(None, get_session, int(sid))
            if not row or row.get("ended_at"):
                state["closed_session"] = sid
                logger.info("Lecteur : séance %s close, socket non rattaché", sid)
                return
            state["session_id"] = sid
        # `/end` lira ici le compte exact des pages lues (session_memory.track).
        session_memory.track(int(sid), memory)
        if state["live_gauges"] is not None:
            # Fige l'amorce de la session en base : la finalisation
            # s'en sert pour ne remonter que les jauges exercées.
            state["live_gauges"].attach_session(sid)

    async def flush_warmup() -> None:
        """Juge et verse la révision éclair dès que la séance est connue.

        Elle arrive avec `start_reading`, qui peut précéder l'identifiant de
        séance (création encore en vol) : elle attend alors le `viewport` qui le
        porte. Versée APRÈS l'amorce, pour compter comme une mesure de la séance."""
        cards, sid = state["pending_warmup"], state["session_id"]
        if not cards or not sid:
            return
        state["pending_warmup"] = None
        try:
            deltas = await loop.run_in_executor(None, warmup.record, int(sid), cards)
        except Exception:  # best-effort : la lecture démarre quoi qu'il arrive
            logger.debug("Révision éclair non enregistrée", exc_info=True)
            return
        if deltas and state["live_gauges"] is not None:
            await loop.run_in_executor(None, state["live_gauges"].apply_warmup, deltas)

    tick_failures: set[str] = set()

    def tick_failed(step: str) -> None:
        """Un pas du ticker a levé : journalisé (avec sa trace la première fois),
        et le ticker continue. Une exception tuait la tâche en silence — plus
        d'observation, plus de battement, plus AUCUNE intervention jusqu'à la
        fin de la séance, alors que les questions de l'élève marchaient encore."""
        first = step not in tick_failures
        tick_failures.add(step)
        logger.warning("Lecteur : pas « %s » du ticker en échec", step, exc_info=first)

    async def _ticker() -> None:
        last_tick = time.monotonic()
        while True:
            await asyncio.sleep(_TICK_SECONDS)
            now = time.monotonic()
            elapsed, last_tick = now - last_tick, now
            # Pause en cours : ni observation, ni intervention. Sans cette porte,
            # la dérive passive punirait (fenêtre masquée, page qui ne bouge plus)
            # un repos que l'élève a choisi ou que Clikoda a elle-même conseillé.
            if pause.active:
                continue
            # Écrit (au plus une fois par minute) dans session_gauges : executor.
            # Le compte des pages lues se lit ici, dans la boucle qui fait vivre
            # la mémoire de séance. Sans `now` : le temps passé sur une page est
            # mesuré par la mémoire de séance, qui a son horloge — le ticker lui
            # en imposait une seconde, pour la même mesure (la fermeture, elle,
            # appelle déjà `pages_read()` sans argument).
            try:
                read = len(memory.pages_read())
                await loop.run_in_executor(None, passive_attention, elapsed, now, read)
            except Exception:
                tick_failed("observation")
            if state["gated"] or now < state["focus_until"]:
                # Question bloquante en cours ou mode focus : Clikoda se tait.
                continue
            # `tick` lit le texte de page et la DB : jamais dans la boucle asyncio.
            try:
                await loop.run_in_executor(None, policy.tick)
            except Exception:
                tick_failed("décision")

    async def handle(msg: ReaderMessage) -> None:
        """Traite UN message du client. Une exception n'y ferme plus le canal
        (cf. la boucle plus bas) : le lecteur gardait sa page, mais plus de
        Clikoda — ni réponse, ni intervention — jusqu'à sa réouverture."""
        kind = msg.type
        page = clamp_page(msg.page)

        if kind == "viewport":
            await attach_session(msg.session_id)
            await flush_warmup()
            # En pause, la page ne bouge pas (le lecteur est masqué) : un
            # viewport tardif ne doit pas ouvrir de dwell sur une autre page.
            if page != state["page"] and not pause.active:
                state["page"] = page
                memory.on_page_view(page)
            return

        if kind == "activity":
            # Deux signaux de présence : la fenêtre (masquée / second plan =
            # absent) et le geste (scroll, souris, clavier = présent, même si
            # la page dominante ne change pas — deuxième colonne, retour sur
            # un schéma). Le second remet la stagnation à zéro.
            if pause.active:
                return  # l'élève est parti : on ne l'observe plus
            state["away"] = bool(msg.hidden)
            if msg.engaged and not msg.hidden:
                memory.on_interaction(time.monotonic())
            return

        if kind == "engage":
            # Surligner, annoter : un geste de lecture active, donc aussi
            # une présence. En pause, l'élève n'est pas là (le lecteur est
            # masqué) : rien n'est compté.
            if pause.active or msg.action is None:
                return
            now = time.monotonic()
            memory.on_interaction(now)
            await credit_engagement(msg.action, now)
            return

        if kind == "pause":
            # Bouton « Pause » de l'élève, ou carte de Clikoda acceptée (la
            # durée conseillée sert au crédit). La pause dure jusqu'à `resume`.
            minutes = PAUSE_DEFAULT_MIN if msg.minutes is None else int(msg.minutes)
            attention = (state["live_gauges"].snapshot() if state["live_gauges"] else {}).get("attention")
            now = time.monotonic()
            if pause.start(
                now,
                source=msg.source,
                planned_s=minutes * 60.0,
                page=state["page"],
                attention=attention,
            ):
                state["away"] = False
                policy.set_paused(True)
                memory.pause(now)
            return

        if kind == "resume":
            await resume_reading(time.monotonic())
            return

        if pause.active and kind in _PAUSED_ACTIONS:
            # L'écran de pause couvre déjà le panneau : défense en profondeur,
            # rien ne se génère ni ne s'évalue tant que l'élève n'est pas revenu.
            return
        if kind in _PAUSED_ACTIONS:
            # L'élève prend la main : une question automatique en génération
            # n'a plus sa place (cf. on_intervention).
            state["user_turn"] += 1
        if kind == "ask" and (msg.question or "").strip():
            # Questionner, répondre : l'engagement est le geste lui-même,
            # crédité qu'Ollama réponde ou non.
            await credit_engagement("ask", time.monotonic())
        elif kind == "qa_answer" and (msg.answer or "").strip():
            await credit_engagement("answer", time.monotonic())

        if kind == "start_reading":
            # Sas d'entrée franchi : le warm-up de la première question part
            # d'ici, pas de l'ouverture du socket (cf. policy.start_reading),
            # et la lecture aussi — le temps du sas n'est pas une lecture de
            # la page 1 (memory.start_reading).
            # Le message porte la page à l'écran : ouvert sur le marque-page,
            # le lecteur n'y est pas en page 1, et un `viewport` perdu
            # pendant l'ouverture du socket compterait la lecture sur la
            # page 1. Posée AVANT `start_reading`, qui repart de la page
            # courante.
            if msg.page is not None and page != state["page"]:
                state["page"] = page
                memory.on_page_view(page)
            policy.start_reading()
            memory.start_reading(time.monotonic())
            await attach_session(msg.session_id)
            if msg.warmup:
                state["pending_warmup"] = msg.warmup
            await flush_warmup()
            return

        if kind == "mode":
            mode = str(msg.mode or ASSISTANT_DEFAULT_MODE)
            state["mode"] = mode if mode in ASSISTANT_MODES else ASSISTANT_DEFAULT_MODE
            await out.put({
                "type": "system",
                "message": t("assistant.mode_changed", mode=t(f"assistant.mode_{state['mode']}")),
            })
            return

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
            return

        if kind == "ask":
            question = (msg.question or "").strip()
            if not question:
                return
            memory.on_user_question(page, question)
            recent_exchanges = list(state["exchanges"])
            session_gauges = state["live_gauges"].snapshot() if state["live_gauges"] else {}
            selected_snippets = msg.selected_snippets
            await out.put(loading("assistant_answer"))

            def on_ask_success(result: dict, _q=question, _page=page, _sid=state["session_id"]) -> None:
                if state["live_gauges"] is not None:
                    state["live_gauges"].apply_question(result)
                answer = result.get("answer", "")
                remember_turn("ask", ("student", _q), ("clikoda", answer))
                state["exchanges"].append({"question": _q, "answer": answer})
                del state["exchanges"][:-6]  # ne garder que les 6 derniers échanges
                if answer:
                    try:
                        save_assistant_exchange(doc_id, _page, _q, answer, session_id=_sid)
                    except Exception:  # persistance best-effort
                        logger.debug("Persistance de l'échange assistant ignorée", exc_info=True)
                reply(result)

            launch(
                "assistant_answer",
                lambda ok, err, _q=question, _page=page, _turn=state["last_turn"]: assistant.answer_question(
                    doc_id, _page, _q, ok, err,
                    recent_exchanges=recent_exchanges,
                    session_gauges=session_gauges,
                    selected_snippets=selected_snippets,
                    previous_turn=_turn,
                ),
                on_ask_success,
                report_error,
            )
        elif kind in ("rephrase", "recap", "hook"):
            # Reformuler, résumer, curiosité : ce que Clikoda en dit devient
            # le dernier échange (« redis-le plus simplement » y renvoie).
            def on_command_success(result: dict) -> None:
                remember_turn("command", ("clikoda", result.get("answer", "")))
                reply(result)

            task, run = {
                "rephrase": ("rephrasing", assistant.rephrase_page),
                "recap": ("chapter_summary", assistant.chapter_recap),
                "hook": ("curiosity_hook", assistant.curiosity_hook),
            }[kind]
            await out.put(loading(task))
            launch(task, lambda ok, err, _page=page: run(doc_id, _page, ok, err), on_command_success, report_error)
        elif kind == "start_qa":
            sid = msg.session_id
            await out.put(loading("question"))
            qa_gauges = state["live_gauges"].snapshot() if state["live_gauges"] else {}
            launch(
                "question",
                lambda ok, err, _page=page: assistant.generate_page_question(
                    doc_id, _page, ok, err,
                    session_gauges=qa_gauges,
                    recent_question_types=list(state["recent_qtypes"]),
                    history=list(state["qa_history"]),
                ),
                lambda result, _page=page, _sid=sid: emit_question(result, _page, _sid, gated=False),
                report_error,
            )
        elif kind == "qa_answer":
            sid = msg.session_id
            question = msg.question or ""
            answer = (msg.answer or "").strip()
            if not answer:
                return
            qid = state.get("qa_qid")
            await out.put(loading("evaluation"))

            def on_eval(ev: dict, _sid=sid, _qid=qid, _answer=answer, _page=page, _q=question) -> None:
                # La question a sa réponse : elle n'attend plus (la politique
                # peut reparler, sauf verrou maintenu par une réponse fausse).
                state["qa_pending"] = False
                # Signaux dérivés de la FORME de la réponse (longueur, questions
                # posées, connecteurs, analogies) : ils enrichissent curiosité et
                # créativité que le LLM seul sous-estime.
                ev = augment_evaluation_with_response_signals(ev, _answer)
                # Type de la question -> jauges type-aware (curiosité ≠ contexte).
                ev["question_type"] = state.get("qa_question_type")
                verdict = ev.get("verdict")
                # Le temps mis à répondre (fatigue, persistance) et la série
                # d'erreurs en cours (attention). Le temps ne coûte rien à
                # l'attention ici : la dérive passive l'observe déjà
                # (cf. LiveGauges.apply).
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
                        consecutive_incorrect=int(state["consecutive_incorrect"]),
                    )
                # Verdict ET forme : la longueur de ce qui vient d'être écrit
                # est la matière du signal de fatigue (`answer_fatigue`).
                memory.on_answer(
                    _page, verdict,
                    chars=len(_answer.strip()),
                    response_time_ms=response_time_ms,
                )
                # Q&R de la session : relayée aux prochains prompts (génération
                # comme évaluation), qui la citaient sans jamais la recevoir.
                state["qa_history"].append({
                    "question": str(_q or state.get("qa_text") or "")[:_MAX_HISTORY_TEXT_CHARS],
                    "question_type": ev.get("question_type") or "",
                    "answer": _answer[:_MAX_HISTORY_TEXT_CHARS],
                    "verdict": verdict or "",
                })
                del state["qa_history"][:-_MAX_HISTORY]
                remember_turn(
                    "answer",
                    ("clikoda", _q or state.get("qa_text") or ""),
                    ("student", _answer),
                    ("clikoda", ev.get("feedback", "")),
                )
                try:
                    save_answer(
                        question_id=_qid, user_id=DEFAULT_USER_ID, answer_text=_answer,
                        verdict=verdict, feedback=ev.get("feedback"), session_id=_sid,
                        response_time_ms=response_time_ms,
                    )
                except Exception:  # persistance best-effort
                    logger.debug("Persistance de la réponse ignorée", exc_info=True)
                # Flashcard auto-portante proposée à la bonne réponse : la
                # politique (verdict, doublon, renvoi au document) est celle
                # du service. Seule une carte neuve est annoncée.
                flashcard_created = False
                try:
                    flashcard_created = flashcards_service.create_auto_flashcard(
                        ev.get("flashcard"),
                        verdict=verdict,
                        question_id=_qid,
                        document_id=doc_id,
                        session_id=_sid,
                    )
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
                    # Question réflexive : pas de bonne ni de mauvaise réponse,
                    # l'UI referme la carte et dit « réflexion notée ».
                    "no_wrong_answer": bool(ev.get("no_wrong_answer")),
                })

            launch(
                "evaluation",
                lambda ok, err, _page=page, _q=question, _answer=answer, _qid=qid: assistant.evaluate_page_answer(
                    doc_id, _page, _q, _answer, ok, err,
                    question_type=state.get("qa_question_type") or "",
                    # La question persistée porte sa réponse canonique et ses
                    # propositions : le service s'en sert pour corriger.
                    question_id=_qid,
                    history=list(state["qa_history"]),
                ),
                on_eval,
                report_error,
            )

    sender_task = asyncio.create_task(_sender())
    ticker_task = asyncio.create_task(_ticker())

    try:
        while True:
            raw = await ws.receive_json()
            try:
                msg = ReaderMessage.model_validate(raw)
            except ValidationError:
                continue  # message inconnu/malformé : ignoré, le canal reste ouvert
            try:
                await handle(msg)
            except Exception:
                # Un message qui échoue (base indisponible, service qui lève…)
                # est perdu, pas le canal : la lecture et Clikoda continuent.
                logger.exception("Lecteur : message « %s » en échec", msg.type)
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
        # Séance close pendant une pause : la pause est enregistrée (sans crédit)
        # et retirée du dwell AVANT qu'il soit figé ci-dessous. Synchrone, comme
        # le reste de ce bloc : rien ne doit dépendre d'un await après la coupure.
        try:
            record = end_pause(time.monotonic(), "disconnect")
            if record is not None:
                persist_pause(record)
        except Exception:  # pragma: no cover - best-effort
            logger.debug("Clôture de la pause ignorée", exc_info=True)
        # Flush du dwell de la page courante + persistance fine par page, et le
        # compte EXACT des pages lues (le dernier tick peut avoir 5 s de retard).
        # Quitté depuis le sas, rien n'a été lu : sans cette garde, la mise en
        # condition s'écrivait comme une lecture de la page 1 (et faussait
        # l'allure de services/reading_pace), et le marque-page revenait à 1.
        # La séance elle-même est effacée par `abandonSession`.
        try:
            memory.flush()
            if state["session_id"] and memory.reading_started and memory.dwell_by_page:
                save_page_dwell(
                    int(state["session_id"]),
                    {int(k): round(v, 1) for k, v in memory.dwell_by_page.items()},
                    {int(k): int(v) for k, v in memory.visits_by_page.items()},
                )
            save_pages_read(len(memory.pages_read()))
            if memory.reading_started:
                save_heartbeat(time.monotonic(), force=True)
        except Exception:  # pragma: no cover - persistance best-effort
            logger.debug("Persistance du dwell ignorée", exc_info=True)
        if state["session_id"]:
            session_memory.untrack(int(state["session_id"]), memory)
        # Marque-page : mémorise la dernière page vue pour la signaler à la réouverture.
        try:
            if memory.reading_started:
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
