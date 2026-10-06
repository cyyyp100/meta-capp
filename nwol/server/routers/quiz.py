# server/routers/quiz.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config.settings import (
    QUIZ_DEFAULT_QUESTIONS,
    QUIZ_MAX_QUESTIONS,
    QUIZ_MIN_QUESTIONS,
)
from services.quiz import (
    analyze_session,
    build_quiz,
    evaluate_quiz_answer,
    finalize_quiz_session,
    list_subjects,
    record_quiz_session,
    submit_answer,
)

router = APIRouter(prefix="/quiz", tags=["quiz"])


class AnswerBody(BaseModel):
    category: str | None = None
    correct: bool = False
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


class SessionSettings(BaseModel):
    """Réglages figés au lancement de la session (écran « Lancer le quiz »)."""

    mode: str = "subject"               # "subject" | "multi" (pratique entrelacée)
    subject: str | None = None
    topic: str | None = None


class AnalysisBody(BaseModel):
    answers: list[dict[str, Any]] = []
    # Sans réglages (ancien client), l'analyse reste cadrée par l'historique seul.
    settings: SessionSettings | None = None
    # Séance enregistrée (`POST /quiz/session`) : le bilan est gardé avec elle.
    session_id: int | None = None


class SessionAnswer(BaseModel):
    """Une réponse de la séance, telle que le quiz l'a jouée."""

    question_id: int | None = None
    question: str = ""
    question_type: str = ""
    category: str | None = None
    source: str | None = None
    document_id: int | None = None
    chapter_title: str | None = None
    user_answer: str = ""
    verdict: str = ""
    # False : verdict de l'apprenant (auto-évaluation hors ligne, « je ne sais pas »).
    graded: bool = True
    response_time_ms: int | None = None
    # Signaux renvoyés par `/quiz/evaluate` pour une réponse rédigée, tels quels.
    signals: dict[str, Any] | None = None


class SessionBody(BaseModel):
    """Séance jouée, enregistrée d'un bloc à la fin (ou quand on la quitte)."""

    settings: SessionSettings | None = None
    answers: list[SessionAnswer] = Field(default_factory=list, max_length=200)
    duration_s: int = 0


class FinalizeBody(BaseModel):
    """Clôture d'une session de quiz (sas de sortie)."""

    # Séance enregistrée : le profil glisse vers SA courbe de jauges, et les
    # métriques sont relues en base. Les champs suivants ne servent qu'au repli.
    session_id: int | None = None
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
    """Bornes de la longueur de session. Le champ de l'UI les applique, le
    service re-borne ce qui arrive (`clamp_quiz_length`) : l'UI ne devine pas."""
    return {
        "default_length": QUIZ_DEFAULT_QUESTIONS,
        "min_length": QUIZ_MIN_QUESTIONS,
        "max_length": QUIZ_MAX_QUESTIONS,
    }


@router.get("/questions")
def questions(
    subject: str | None = None,
    n: int = QUIZ_DEFAULT_QUESTIONS,
    topic: str | None = None,
    interleaved: bool = False,
) -> list[dict]:
    """Construit une session de QCM (un seul appel LLM batch pour les distracteurs).

    `topic` : précision libre tapée par l'apprenant, qui affine DANS `subject`
    (ou dans toute la base sans matière) et cible aussi le cours d'origine des
    questions. `n` : longueur de session, bornée par le service.
    `interleaved` : le mode « multi-apprentissage » de l'UI (pratique entrelacée)
    — tirage alterné dans tous les domaines, qui rend `subject` et `topic` sans
    objet (le service les ignore)."""
    return build_quiz(subject, n, topic=topic, interleaved=interleaved)


@router.post("/answer")
def answer(body: AnswerBody) -> dict:
    """Enregistre une réponse : maîtrise de la matière (le profil, lui, glisse à
    la clôture de la séance, vers sa courbe de jauges)."""
    return submit_answer(body.category, body.correct, verdict=body.verdict)


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


@router.post("/session")
def session(body: SessionBody) -> dict:
    """Enregistre la séance jouée : ses réponses et sa courbe de jauges. Renvoie
    ``{session_id, metrics}`` (``session_id`` nul s'il n'y avait aucune réponse)."""
    settings = body.settings.model_dump() if body.settings else None
    return record_quiz_session(
        settings, [entry.model_dump() for entry in body.answers], duration_s=body.duration_s,
    )


@router.post("/analysis")
def analysis(body: AnalysisBody) -> dict:
    """Analyse de fin de session (dans le cadre choisi) + cours à renforcer."""
    settings = body.settings.model_dump() if body.settings else None
    return analyze_session(body.answers, settings=settings, session_id=body.session_id)


@router.post("/finalize")
def finalize(body: FinalizeBody) -> dict:
    """Clôture : réflexions de métacognition + glissement du profil long terme."""
    result = finalize_quiz_session(
        body.responses,
        body.score,
        questions_answered=body.questions_answered,
        correct=body.correct,
        duration_s=body.duration_s,
        subject=body.subject,
        topic=body.topic,
        session_id=body.session_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Séance de quiz introuvable")
    return result
