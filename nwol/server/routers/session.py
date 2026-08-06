# server/routers/session.py — Cycle de vie d'une session de lecture.
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from db.user import record_login_and_get_streak
from services.session import (
    end_session,
    finalize_session,
    session_analysis,
    session_metrics,
    start_session,
)

router = APIRouter(prefix="/session", tags=["session"])


class StartBody(BaseModel):
    doc_id: int


class EndBody(BaseModel):
    pages_read: int | None = None
    duration_s: int | None = None


class FinalizeBody(BaseModel):
    responses: list[str] = []


@router.post("/start")
def start(body: StartBody) -> dict:
    return start_session(body.doc_id)


@router.post("/{session_id}/end")
def end(session_id: int, body: EndBody) -> dict:
    return end_session(session_id, pages_read=body.pages_read, duration_s=body.duration_s)


@router.get("/{session_id}/metrics")
def metrics(session_id: int) -> dict:
    return session_metrics(session_id)


@router.get("/{session_id}/analysis")
def analysis(session_id: int) -> dict:
    """Analyse LLM de la session (best-effort) pour le sas de sortie."""
    return session_analysis(session_id)


@router.post("/{session_id}/finalize")
def finalize(session_id: int, body: FinalizeBody) -> dict:
    return finalize_session(session_id, body.responses)


# Streak (séries de jours consécutifs), affiché sur l'accueil.
streak_router = APIRouter(tags=["home"])


@streak_router.get("/streak")
def streak() -> dict:
    return {"streak": record_login_and_get_streak()}
