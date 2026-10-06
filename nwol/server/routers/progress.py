# server/routers/progress.py — « Ma progression » (historique de l'apprenant).
#
# Des lectures, zéro logique : la timeline, le détail d'une séance de lecture et
# celui d'une séance de pratique (quiz, langue). Tout ce qui ressemble à une
# décision vit dans `services/progress.py` (cf. CLAUDE.md).
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services.progress import (
    DEFAULT_TIMELINE_LIMIT,
    get_practice_progress,
    get_session_progress,
    get_weekly_recap,
    list_progress_sessions,
)

router = APIRouter(prefix="/progress", tags=["progress"])


@router.get("/sessions")
def sessions(limit: int = DEFAULT_TIMELINE_LIMIT, kind: str | None = None) -> dict:
    """Frise des séances ; `kind` (reading | quiz | lang) n'en garde qu'une catégorie."""
    return list_progress_sessions(limit=limit, kind=kind)


@router.get("/session/{session_id}")
def session_detail(session_id: int) -> dict:
    detail = get_session_progress(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session introuvable")
    return detail


@router.get("/practice/{session_id}")
def practice_detail(session_id: int) -> dict:
    """Détail d'une séance de quiz ou de langue."""
    detail = get_practice_progress(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Séance introuvable")
    return detail


@router.get("/weekly")
def weekly() -> dict:
    """Bilan des sept derniers jours — le rendez-vous, pas un cumul depuis toujours."""
    return get_weekly_recap()
