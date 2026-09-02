# server/routers/progress.py — « Ma progression » (historique de l'apprenant).
#
# Deux lectures, zéro logique : la timeline et le détail d'une session. Tout ce
# qui ressemble à une décision vit dans `services/progress.py` (cf. CLAUDE.md).
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services.progress import (
    DEFAULT_TIMELINE_LIMIT,
    get_session_progress,
    get_weekly_recap,
    list_progress_sessions,
)

router = APIRouter(prefix="/progress", tags=["progress"])


@router.get("/sessions")
def sessions(limit: int = DEFAULT_TIMELINE_LIMIT) -> dict:
    return list_progress_sessions(limit=limit)


@router.get("/session/{session_id}")
def session_detail(session_id: int) -> dict:
    detail = get_session_progress(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session introuvable")
    return detail


@router.get("/weekly")
def weekly() -> dict:
    """Bilan des sept derniers jours — le rendez-vous, pas un cumul depuis toujours."""
    return get_weekly_recap()
