# services/lang_hook.py — L'accroche du sas d'entrée d'une séance de langue.
#
# Comme avant un PDF, le sas d'entrée d'une séance du feuilleton montre une
# phrase de Clikoda qui donne envie d'entrer : ici, sur l'épisode que la séance
# va faire découvrir. Elle s'écrit PENDANT le sas, à sa demande ; le sas ne
# l'attend pas (il l'affiche quand elle arrive) et la séance non plus :
# `lang_runs` n'appelle jamais Clikoda, il dit seulement de quel épisode il
# s'agit (`coming_episode`). Pas d'épisode neuf (relecture, reprise, bilan),
# Clikoda injoignable ou phrase inutilisable : pas d'accroche — rien d'écrit
# d'avance à sa place, et rien n'est stocké.
from __future__ import annotations

import logging

from config.settings import LANG_HOOK_MAX_CHARS, LANG_HOOK_OPENING_LINES
from db import lang_episode_db as store
from llm import ollama_client as llm
from services import lang_episodes as episodes
from services import lang_runs
from services.llm_bridge import run_llm_sync

logger = logging.getLogger("services.lang_hook")


def hook_params(profile: dict, language: str, episode: dict) -> dict:
    """Ce que Clikoda voit de l'épisode, dans la langue d'explication du
    profil : titre, résumé, les premières répliques traduites (le début, pas la
    fin), le résumé de l'épisode précédent et les personnages."""
    lang = episodes.explain_lang_of(profile)
    n = int(episode["episode_n"])
    prev = store.get_episode_by_n(profile["id"], n - 1) if n > 1 else None
    return {
        "language_label": episodes.prompt_params(language, lang)["language_label"],
        "episode_n": n, "title": episode.get("title") or "", "summary": episode.get("summary") or "",
        "previous": (prev.get("summary") or "") if prev and prev["status"] == "played" else "",
        "opening": [(ln.get("speaker") or "", ln.get("translation") or "")
                    for ln in (episode.get("lines") or [])[:LANG_HOOK_OPENING_LINES]],
        "characters": (store.get_latest_bible(profile["id"]) or {}).get("characters") or [],
        "max_chars": LANG_HOOK_MAX_CHARS, "explain_lang": lang,
    }


def validate_hook(language: str, result: dict | None, explain_lang: str) -> str:
    """La phrase, ou "" quand elle manque, dépasse LANG_HOOK_MAX_CHARS ou est
    écrite dans l'autre langue d'explication. Pas de seconde tentative : le
    sas ne dure qu'une minute."""
    text = " ".join(((result or {}).get("curiosity_hook") or "").split())
    if not text or len(text) > LANG_HOOK_MAX_CHARS:
        return ""
    if episodes._written_in_other_language(explain_lang, text, language):
        return ""
    return text


def entry_hook(language: str) -> str:
    """L'accroche du sas d'entrée de `language`, ou "" : une panne de Clikoda
    ne fait jamais d'erreur, le sas s'en passe. Une langue hors pilote lève
    `RunError`, comme les autres routes du feuilleton."""
    profile = lang_runs.ensure_feuilleton(language)
    episode = lang_runs.coming_episode(profile, language)
    if not episode:
        return ""
    params = hook_params(profile, language, episode)
    try:
        # L'apprenant est devant le sas : l'attente en file compte dans le budget.
        result = run_llm_sync(lambda ok, err: llm.generate_lang_episode_hook_async(params, ok, err))
    except Exception as exc:  # Ollama éteint, budget dépassé, JSON inexploitable
        logger.info("Accroche du sas indisponible (%s, épisode %s) : %s", language, params["episode_n"], exc)
        return ""
    hook = validate_hook(language, result, params["explain_lang"])
    if not hook:
        logger.info("Accroche du sas refusée (%s, épisode %s) : %r", language, params["episode_n"], result)
    return hook
