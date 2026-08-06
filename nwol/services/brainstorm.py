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
from __future__ import annotations

import logging
from typing import Callable

from db import brainstorm as store
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
_DEFAULT_TITLES = {"", "Nouvelle discussion", "New discussion"}


def handle_message(
    discussion_id: int,
    user_message: str,
    on_answer: Callable[[dict], None],
    on_error: Callable[[str], None],
    on_scanning: Callable[[bool], None] | None = None,
) -> None:
    """Traite un message utilisateur. Résultat livré via ``on_answer`` / ``on_error``."""
    user_message = (user_message or "").strip()
    if not user_message:
        return
    discussion = store.get_discussion(discussion_id)
    if discussion is None:
        on_error("Discussion introuvable")
        return

    summary = discussion.get("summary") or ""
    history = store.get_messages(discussion_id, limit=HISTORY_TURNS)

    # Auto-titre façon Claude : la 1re question nomme la discussion encore vierge.
    if (discussion.get("title") or "").strip() in _DEFAULT_TITLES and not history:
        try:
            store.rename_discussion(discussion_id, user_message[:60])
        except Exception:  # pragma: no cover - best-effort
            pass

    # Persistance immédiate du message user (réapparaît même si le LLM échoue ensuite).
    try:
        store.add_message(discussion_id, "user", user_message)
    except Exception:  # pragma: no cover - best-effort
        pass

    def _answer(sources: list[dict]) -> None:
        context = {
            "summary": summary,
            "history": history,
            "user_message": user_message,
            "sources": sources,
        }

        def _on_text(text: str) -> None:
            text = (text or "").strip()
            try:
                store.add_message(discussion_id, "assistant", text, sources=sources)
            except Exception:  # pragma: no cover - best-effort
                pass
            _maybe_summarize(discussion_id)
            on_answer({"answer": text, "sources": sources})

        answer_brainstorm_async(context, _on_text, on_error)

    def _on_decision(decision: dict) -> None:
        queries = (decision or {}).get("queries") or []
        if not ((decision or {}).get("search") and queries):
            _answer([])
            return
        if on_scanning:
            on_scanning(True)
        sources: list[dict] = []
        try:
            seen: set = set()
            for q in queries:
                for item in brainstorm_search.search_user_db(q):
                    key = (item.get("source_type"), item.get("snippet"))
                    if key in seen:
                        continue
                    seen.add(key)
                    sources.append(item)
                    if len(sources) >= MAX_SOURCES:
                        break
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

    decide_brainstorm_search_async(history, user_message, _on_decision, _on_decide_error)


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
            except Exception:  # pragma: no cover - best-effort
                pass

        def _on_err(_msg: str) -> None:  # pragma: no cover - best-effort
            pass

        summarize_brainstorm_async(discussion.get("summary") or "", pending, _on_summary, _on_err)
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Résumé glissant impossible : %s", exc)
