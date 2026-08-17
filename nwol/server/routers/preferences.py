# server/routers/preferences.py — Préférences d'interface persistées.
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

from db.user import DEFAULT_USER_ID, get_user_lang, set_user_lang
from i18n import STRINGS, current_lang, set_lang

logger = logging.getLogger("server.preferences")

router = APIRouter(prefix="/preferences", tags=["preferences"])

SUPPORTED_LANGS = tuple(STRINGS)


class LangBody(BaseModel):
    lang: str


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
