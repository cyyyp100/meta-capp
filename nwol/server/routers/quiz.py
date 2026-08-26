# server/routers/quiz.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from config.settings import (
    QUIZ_DEFAULT_QUESTIONS,
    QUIZ_LENGTH_CHOICES,
    QUIZ_MAX_QUESTIONS,
    QUIZ_MIN_QUESTIONS,
)
from services.quiz import (
    analyze_session,
    build_quiz,
    evaluate_quiz_answer,
    finalize_quiz_session,
    list_subjects,
    submit_answer,
)

router = APIRouter(prefix="/quiz", tags=["quiz"])


class AnswerBody(BaseModel):
    category: str | None = None
    correct: bool = False
    session_id: int | None = None
    # Verdict rendu par la correction ("correct" / "partial" / "incorrect") :
    # le booléen seul perdait le « partiel » des réponses rédigées.
    verdict: str | None = None


class EvaluateBody(BaseModel):
    """Réponse à corriger. La question de lecture persistée prime sur ce corps."""

    question_id: int | None = None
    question: str = ""
    user_answer: str = ""
    question_type: str = ""
    answer: str = ""                    # réponse attendue, telle que reçue par la session
    choices: list[str] | None = None


class AnalysisBody(BaseModel):
    answers: list[dict[str, Any]] = []


class FinalizeBody(BaseModel):
    """Clôture d'une session de quiz (sas de sortie)."""

    responses: list[str] = []
    score: float = 0.0  # taux de réussite 0–100
    questions_answered: int = 0
    correct: int = 0
    duration_s: int = 0
    subject: str | None = None
    topic: str | None = None


@router.get("/subjects")
def subjects() -> list[dict]:
    """Matières disponibles (avec effectif) pour le sélecteur de thème."""
    return list_subjects()


@router.get("/options")
def options() -> dict:
    """Longueurs de session proposées. Le serveur borne, l'UI ne devine pas."""
    return {
        "lengths": list(QUIZ_LENGTH_CHOICES),
        "default_length": QUIZ_DEFAULT_QUESTIONS,
        "min_length": QUIZ_MIN_QUESTIONS,
        "max_length": QUIZ_MAX_QUESTIONS,
    }


@router.get("/questions")
def questions(
    subject: str | None = None,
    n: int = QUIZ_DEFAULT_QUESTIONS,
    topic: str | None = None,
) -> list[dict]:
    """Construit une session de QCM (un seul appel LLM batch pour les distracteurs).

    `topic` : sujet libre tapé par l'apprenant, qui cible aussi le cours d'origine
    des questions. `n` : longueur de session, bornée par le service."""
    return build_quiz(subject, n, topic=topic)


@router.post("/answer")
def answer(body: AnswerBody) -> dict:
    """Enregistre une réponse : maîtrise de la matière + rétention du profil."""
    return submit_answer(
        body.category, body.correct, session_id=body.session_id, verdict=body.verdict,
    )


@router.post("/evaluate")
def evaluate(body: EvaluateBody) -> dict:
    """Corrige une réponse rédigée (ou une remise en ordre) de la session.

    C'est ce qui permet au quiz de rejouer TOUS les types de questions et pas
    seulement les QCM : les types à rédiger sont corrigés ici, par le même
    verdict objectif et le même prompt d'évaluation que pendant la lecture."""
    return evaluate_quiz_answer(
        body.question_id,
        body.question,
        body.user_answer,
        question_type=body.question_type,
        expected_answer=body.answer,
        choices=body.choices,
    )


@router.post("/analysis")
def analysis(body: AnalysisBody) -> dict:
    """Analyse de fin de session + conseil de cours à renforcer."""
    return analyze_session(body.answers)


@router.post("/finalize")
def finalize(body: FinalizeBody) -> dict:
    """Sas de sortie : réflexions de métacognition + nudge du profil long terme."""
    return finalize_quiz_session(
        body.responses,
        body.score,
        questions_answered=body.questions_answered,
        correct=body.correct,
        duration_s=body.duration_s,
        subject=body.subject,
        topic=body.topic,
    )
