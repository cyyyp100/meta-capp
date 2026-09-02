# server/routers/preferences.py — Préférences d'interface persistées.
#
# Deux familles, un seul routeur :
#   * GET/POST /api/preferences      — réglages d'application (thème, densité,
#     taille du texte, mises à jour, visite guidée), stockés dans `app_settings`
#     et déclarés par `services/preferences.py`. Le routeur ne connaît aucun nom
#     de réglage : il passe le patch au service et remonte ses refus en 400.
#   * GET/POST /api/preferences/lang — la langue, à part pour la raison ci-dessous.
#
# La langue n'est PAS qu'une affaire de frontend : `nwol/i18n.py` pilote aussi la
# langue des prompts LLM (`llm/prompts.py` branche sur `current_lang()`). Sans cet
# endpoint, basculer l'UI en anglais donnait une interface anglaise et un Gemma qui
# répond en français. On persiste donc le choix côté serveur et on l'applique au
# process (rechargé au démarrage par le lifespan de `server/app.py`).
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.user import (
    DEFAULT_USER_ID,
    get_default_user,
    get_user_lang,
    set_user_lang,
    update_user_name,
)
from i18n import STRINGS, current_lang, set_lang
from services.preferences import PREFERENCES, get_preferences, update_preferences

logger = logging.getLogger("server.preferences")

router = APIRouter(prefix="/preferences", tags=["preferences"])

SUPPORTED_LANGS = tuple(STRINGS)


class LangBody(BaseModel):
    lang: str


class NameBody(BaseModel):
    name: str


@router.get("")
def read_preferences() -> dict:
    """Tous les réglages d'application + le profil affiché à côté d'eux.

    Le nom et la langue voyagent avec : l'écran Réglages les montre dans la même
    colonne, et une seconde requête pour deux champs n'apporterait rien."""
    return {
        "preferences": get_preferences(),
        "choices": {
            key: list(pref.choices) if pref.kind == "enum" else ["true", "false"]
            for key, pref in PREFERENCES.items()
        },
        "lang": current_lang(),
        "supported_langs": list(SUPPORTED_LANGS),
        "user": _user_payload(),
    }


@router.post("")
def write_preferences(patch: dict) -> dict:
    """Patch partiel : seules les clés présentes sont écrites.

    Une clé inconnue ou une valeur hors domaine est un 400 — `services.preferences`
    est l'autorité, ce routeur ne connaît aucun nom de réglage."""
    try:
        preferences = update_preferences(patch or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"preferences": preferences}


@router.post("/name")
def post_name(body: NameBody) -> dict:
    """Nom affiché de l'apprenant (bloc profil de la barre latérale)."""
    try:
        update_user_name(DEFAULT_USER_ID, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"user": _user_payload()}


def _user_payload() -> dict:
    user = get_default_user()
    return {"id": user["id"], "name": user["name"]}


@router.get("/lang")
def get_lang() -> dict:
    """Langue effective du backend (et donc des prompts LLM)."""
    return {"lang": current_lang(), "supported": list(SUPPORTED_LANGS)}


@router.post("/lang")
def post_lang(body: LangBody) -> dict:
    """Change la langue de l'interface ET des générations LLM."""
    lang = (body.lang or "").strip().lower()
    if lang not in SUPPORTED_LANGS:
        raise HTTPException(status_code=400, detail="Langue non prise en charge")
    set_user_lang(DEFAULT_USER_ID, lang)
    set_lang(lang)
    logger.info("Langue de l'interface et des prompts : %s", lang)
    return {"lang": current_lang(), "supported": list(SUPPORTED_LANGS)}


def apply_stored_lang() -> None:
    """Restaure la langue choisie au démarrage du serveur (best-effort)."""
    try:
        set_lang(get_user_lang(DEFAULT_USER_ID))
    except Exception:  # pragma: no cover - une base neuve reste en français
        logger.debug("Langue utilisateur non restaurée", exc_info=True)
