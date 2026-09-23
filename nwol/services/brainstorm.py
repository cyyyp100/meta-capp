# services/brainstorm.py — Cœur UI-agnostique de la page Brainstorming.
#
# Chat libre avec Gemma, avec mémoire par discussion ET accès à la base de
# l'utilisateur. Le flux d'un message (non bloquant, à callbacks, comme
# services/assistant.py) :
#   1. décision LLM : faut-il chercher dans la base + mots-clés ?
#   2. si oui : recherche multi-tables -> extraits (sources)
#   3. réponse LLM (texte libre) avec résumé + historique récent + sources
#   4. persistance best-effort (message user puis assistant)
#   5. résumé glissant régénéré quand l'historique s'allonge
#
# Portée : une discussion liée à un dossier de la bibliothèque ne cherche que
# dans les documents de ce dossier et de ses sous-dossiers (`_scope`), relue à
# chaque message — changer de dossier vaut dès le message suivant. C'est aussi
# ici que se décident le plafond d'épinglage et la validité du dossier : le
# routeur ne fait que traduire les ValueError en 400.
#
# Garde-fous : une seule page blanche par utilisateur (`create_discussion`) et
# une seule question à la fois par discussion (`_claim`).
from __future__ import annotations

import logging
import threading
from typing import Callable

from config.settings import BRAINSTORM_MAX_PINNED, BRAINSTORM_SCOPE_TITLES_MAX
from db import brainstorm as store
from db import folders as folders_store
from i18n import t
from llm.ollama_client import (
    answer_brainstorm_async,
    decide_brainstorm_search_async,
    summarize_brainstorm_async,
)
from services import brainstorm_search

logger = logging.getLogger("services.brainstorm")

# Nombre de messages récents passés au LLM (le résumé couvre le reste).
HISTORY_TURNS = 10
# Extraits de base injectés au maximum dans une réponse.
MAX_SOURCES = 6
# On régénère le résumé glissant tous les N nouveaux messages non couverts.
SUMMARY_EVERY = 8
_DEFAULT_TITLES = {"", *store.BLANK_TITLES}
# Longueur maximale du titre tiré du 1er message.
_TITLE_MAX = 60

# Discussions dont une question est en cours, avec le jeton de celle-ci. Une à
# la fois par discussion : deux questions croisées (second onglet, client qui
# insiste) entrelaçaient leurs messages en base, et chaque réponse partait d'un
# historique qui ignorait l'autre. Libéré par la réponse ou l'erreur — le client
# Ollama garantit que l'une des deux arrive, annulation et délai compris.
_answering: dict[int, object] = {}
_answering_lock = threading.Lock()


# ── Gestion des discussions ─────────────────────────────────────────────────


def create_discussion(title: str = "", folder_id: int | None = None) -> dict:
    """Crée une discussion, liée d'emblée à un dossier si ``folder_id`` est donné.

    Sans titre (ou avec le titre par défaut), c'est une page blanche : si
    l'utilisateur en a déjà une, elle est rouverte au lieu d'en empiler une
    autre (`db/brainstorm.create_blank_discussion`). Un vrai titre crée toujours.
    """
    _check_folder(folder_id)
    title = (title or "").strip()
    if title in _DEFAULT_TITLES:
        discussion_id = store.create_blank_discussion(folder_id=folder_id)
    else:
        discussion_id = store.create_discussion(title, folder_id=folder_id)
    return store.get_discussion(discussion_id) or {"id": discussion_id}


def set_pinned(discussion_id: int, pinned: bool) -> dict:
    """Épingle / désépingle. Au-delà de ``BRAINSTORM_MAX_PINNED`` -> ValueError."""
    _require(discussion_id)
    if not pinned:
        store.unpin_discussion(discussion_id)
    elif not store.pin_discussion(discussion_id, BRAINSTORM_MAX_PINNED):
        raise ValueError(t("brainstorm.pin_limit", n=BRAINSTORM_MAX_PINNED))
    return store.get_discussion(discussion_id) or {"id": discussion_id}


def set_folder(discussion_id: int, folder_id: int | None) -> dict:
    """Lie la discussion à un dossier (``None`` = toute la base)."""
    _require(discussion_id)
    _check_folder(folder_id)
    store.set_discussion_folder(discussion_id, folder_id)
    return store.get_discussion(discussion_id) or {"id": discussion_id}


def _require(discussion_id: int) -> dict:
    discussion = store.get_discussion(discussion_id)
    if discussion is None:
        raise ValueError(t("brainstorm.missing"))
    return discussion


def _check_folder(folder_id: int | None) -> None:
    if folder_id is not None and folders_store.get_folder(folder_id) is None:
        raise ValueError(t("brainstorm.folder_missing"))


def is_answering(discussion_id: int) -> bool:
    """Une question de cette discussion est-elle en cours de traitement ?"""
    with _answering_lock:
        return discussion_id in _answering


def _claim(discussion_id: int) -> object | None:
    """Réserve la discussion pour une question ; ``None`` si elle est déjà prise."""
    token = object()
    with _answering_lock:
        if discussion_id in _answering:
            return None
        _answering[discussion_id] = token
    return token


def _release(discussion_id: int, token: object) -> bool:
    """Libère la réservation — seulement la sienne, jamais celle d'une question
    suivante. ``True`` la première fois seulement : c'est ce qui garantit un seul
    callback final par question."""
    with _answering_lock:
        if _answering.get(discussion_id) is not token:
            return False
        del _answering[discussion_id]
        return True


# ── Conversation ────────────────────────────────────────────────────────────


def handle_message(
    discussion_id: int,
    user_message: str,
    on_answer: Callable[[dict], None],
    on_error: Callable[[str], None],
    on_scanning: Callable[[bool], None] | None = None,
    on_title: Callable[[str], None] | None = None,
) -> None:
    """Traite un message utilisateur. Résultat livré via ``on_answer`` / ``on_error``.

    ``on_title`` reçoit le titre tiré du 1er message, AVANT tout travail LLM :
    la liste des discussions le montre dès l'envoi, pas à l'arrivée de la réponse.

    Une question déjà en cours dans la discussion -> ``on_error`` immédiat, rien
    n'est persisté. Exactement un des deux callbacks finaux est appelé, et la
    discussion est libérée juste avant.
    """
    user_message = (user_message or "").strip()
    if not user_message:
        return
    discussion = store.get_discussion(discussion_id)
    if discussion is None:
        on_error(t("brainstorm.missing"))
        return
    token = _claim(discussion_id)
    if token is None:
        on_error(t("brainstorm.busy"))
        return

    def _finish_answer(result: dict) -> None:
        if _release(discussion_id, token):
            on_answer(result)

    def _finish_error(message: str) -> None:
        if _release(discussion_id, token):
            on_error(message)

    try:
        _handle_claimed(
            discussion, user_message, _finish_answer, _finish_error, on_scanning, on_title,
        )
    except Exception:
        # Une panne AVANT la mise en file (DB, construction du prompt…) ne doit
        # pas laisser la discussion réservée pour toujours.
        logger.warning("Traitement du message de brainstorming impossible", exc_info=True)
        _finish_error(t("brainstorm.failed"))


def _handle_claimed(
    discussion: dict,
    user_message: str,
    on_answer: Callable[[dict], None],
    on_error: Callable[[str], None],
    on_scanning: Callable[[bool], None] | None,
    on_title: Callable[[str], None] | None,
) -> None:
    """Le flux d'une question, une fois la discussion réservée (cf. `handle_message`)."""
    discussion_id = int(discussion["id"])
    summary = discussion.get("summary") or ""
    history = store.get_messages(discussion_id, limit=HISTORY_TURNS)
    scope = _scope(discussion)

    # Auto-titre façon Claude : la 1re question nomme la discussion encore vierge.
    if (discussion.get("title") or "").strip() in _DEFAULT_TITLES and not history:
        title = _title_from_message(user_message)
        try:
            store.rename_discussion(discussion_id, title)
            if on_title:
                on_title(title)
        except Exception:  # best-effort : un titre raté ne casse pas la réponse
            logger.debug("Auto-titre de discussion ignoré", exc_info=True)

    # Persistance immédiate du message user (réapparaît même si le LLM échoue ensuite).
    try:
        store.add_message(discussion_id, "user", user_message)
    except Exception:  # best-effort : la réponse prime sur son archivage
        logger.debug("Persistance du message utilisateur ignorée", exc_info=True)

    def _answer(sources: list[dict]) -> None:
        context = {
            "summary": summary,
            "history": history,
            "user_message": user_message,
            "sources": sources,
            "scope": scope,
        }

        def _on_text(text: str) -> None:
            text = (text or "").strip()
            try:
                store.add_message(discussion_id, "assistant", text, sources=sources)
            except Exception:  # best-effort : la réponse prime sur son archivage
                logger.debug("Persistance de la réponse assistant ignorée", exc_info=True)
            _maybe_summarize(discussion_id)
            on_answer({"answer": text, "sources": sources})

        try:
            answer_brainstorm_async(context, _on_text, on_error)
        except Exception:  # file LLM inutilisable : on le dit plutôt que de se taire
            logger.warning("Mise en file de la réponse de brainstorming impossible", exc_info=True)
            on_error(t("brainstorm.failed"))

    def _on_decision(decision: dict) -> None:
        queries = (decision or {}).get("queries") or []
        if not ((decision or {}).get("search") and queries):
            _answer([])
            return
        if on_scanning:
            on_scanning(True)
        sources: list[dict] = []
        try:
            # Extraits DÉJÀ CITÉS dans cette discussion : amortis, pas exclus. Sans
            # cela, la même poignée de surlignages revenait tour après tour, et
            # deux fois la même question rendait la même réponse aux mêmes sources.
            already_cited = _cited_keys(discussion_id)
            seen: set = set()
            for q in queries:
                remaining = MAX_SOURCES - len(sources)
                if remaining <= 0:
                    break
                for item in brainstorm_search.search_user_db(
                    q, limit=remaining, damp_keys=already_cited | seen,
                    folder_ids=scope["folder_ids"] if scope else None,
                ):
                    key = brainstorm_search.source_key(item)
                    if key in seen:
                        continue
                    seen.add(key)
                    sources.append(item)
                    if len(sources) >= MAX_SOURCES:
                        break
        except Exception as exc:  # pragma: no cover - best-effort
            logger.debug("Recherche base échouée : %s", exc)
        finally:
            if on_scanning:
                on_scanning(False)
        _answer(sources)

    def _on_decide_error(msg: str) -> None:
        # La décision de recherche a échoué : on répond quand même, sans RAG.
        logger.debug("Décision de recherche échouée (%s) -> réponse sans recherche", msg)
        _answer([])

    decide_brainstorm_search_async(
        history, user_message, _on_decision, _on_decide_error, scope=scope,
    )


def _title_from_message(text: str) -> str:
    """Titre lisible tiré du 1er message : espaces compactés, coupe au mot près."""
    clean = " ".join((text or "").split())
    if len(clean) <= _TITLE_MAX:
        return clean
    cut = clean[: _TITLE_MAX - 1]
    head, _, _ = cut.rpartition(" ")
    # Un seul mot démesuré : on le coupe plutôt que de rendre un titre vide.
    return (head if len(head) >= _TITLE_MAX // 2 else cut).rstrip(" ,;:.-") + "…"


def _scope(discussion: dict) -> dict | None:
    """Portée de la discussion : ``None`` = toute la base.

    Liée à un dossier : ``{"folder_ids", "name", "titles", "total"}``, le dossier
    ET ses sous-dossiers. Un dossier supprimé a déjà remis `folder_id` à NULL
    (ON DELETE SET NULL) ; un sous-arbre vide donne ``folder_ids`` vide, ce qui
    veut dire « aucun document », jamais « toute la base ».
    """
    folder_id = discussion.get("folder_id")
    if folder_id is None:
        return None
    folder_ids = folders_store.descendant_ids(int(folder_id))
    titles, total = folders_store.document_titles_in_folders(
        folder_ids, BRAINSTORM_SCOPE_TITLES_MAX,
    )
    return {
        "folder_ids": folder_ids,
        "name": discussion.get("folder_name") or "",
        "titles": titles,
        "total": total,
    }


def _cited_keys(discussion_id: int) -> set:
    """Clés des extraits déjà cités dans la discussion (cf. `brainstorm_search.source_key`).

    Les sources sont archivées avec chaque message assistant (`sources_json`), il
    n'y a donc rien de nouveau à persister : elles n'étaient simplement jamais
    relues. Best-effort — une recherche sans amortissement vaut mieux qu'une
    réponse en erreur.
    """
    try:
        return {
            brainstorm_search.source_key(src)
            for message in store.get_messages(discussion_id)
            for src in (message.get("sources") or [])
        }
    except Exception:  # pragma: no cover - best-effort
        logger.debug("Relecture des sources déjà citées ignorée", exc_info=True)
        return set()


def _maybe_summarize(discussion_id: int) -> None:
    """Régénère le résumé glissant si assez de messages ne sont pas encore couverts."""
    try:
        discussion = store.get_discussion(discussion_id)
        if discussion is None:
            return
        upto = int(discussion.get("summary_upto_msg_id") or 0)
        pending = [m for m in store.get_messages(discussion_id) if int(m["id"]) > upto]
        if len(pending) < SUMMARY_EVERY:
            return
        max_id = max(int(m["id"]) for m in pending)

        def _on_summary(text: str) -> None:
            try:
                store.update_summary(discussion_id, text, max_id)
            except Exception:  # best-effort : le résumé glissant se rattrape au tour suivant
                logger.debug("Mise à jour du résumé de discussion ignorée", exc_info=True)

        def _on_err(msg: str) -> None:  # best-effort : pas de résumé ce tour-ci
            logger.debug("Résumé glissant abandonné : %s", msg)

        summarize_brainstorm_async(discussion.get("summary") or "", pending, _on_summary, _on_err)
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Résumé glissant impossible : %s", exc)
