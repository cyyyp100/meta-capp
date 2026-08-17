# server/routers/quiz.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from services.quiz import analyze_session, build_quiz, list_subjects, submit_answer

router = APIRouter(prefix="/quiz", tags=["quiz"])


class AnswerBody(BaseModel):
    category: str | None = None
    correct: bool = False
    session_id: int | None = None


class AnalysisBody(BaseModel):
    answers: list[dict[str, Any]] = []


@router.get("/subjects")
def subjects() -> list[dict]:
    """Matières disponibles (avec effectif) pour le sélecteur de thème."""
    return list_subjects()


@router.get("/questions")
def questions(subject: str | None = None, n: int = 10) -> list[dict]:
    """Construit une session de QCM (un seul appel LLM batch pour les distracteurs)."""
    return build_quiz(subject, n)


@router.post("/answer")
def answer(body: AnswerBody) -> dict:
    """Enregistre une réponse : maîtrise de la matière + rétention du profil."""
    return submit_answer(body.category, body.correct, session_id=body.session_id)


@router.post("/analysis")
def analysis(body: AnalysisBody) -> dict:
    """Analyse de fin de session + conseil de cours à renforcer."""
    return analyze_session(body.answers)
