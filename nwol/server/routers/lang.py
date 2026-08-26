# server/routers/lang.py — Module Langues (profil + séquenceur adaptatif).
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from db.lang_db import SESSION_TYPES_SEED
from services.lang import (
    complete_lesson,
    complete_session,
    correct_attempt,
    finalize_lang_lesson,
    generate_lesson,
    generate_session,
    get_language_profile,
    get_lesson_exercise,
    lang_lesson_analysis,
    lang_stats_overview,
    lang_warmup_cards,
    list_languages,
    placement_skip,
    placement_start,
    placement_submit,
    review_lang_card,
    start_lesson,
)

router = APIRouter(prefix="/lang", tags=["lang"])


class LessonBody(BaseModel):
    language: str


class SessionCompleteBody(BaseModel):
    language: str
    session_type: str
    score: float = 0.0
    duration_s: int = 0


class CorrectBody(BaseModel):
    language: str
    target_phrase: str
    user_attempt: str


class SrReviewBody(BaseModel):
    language: str
    verdict: str
    card_id: int | None = None
    word: str = ""


class LessonCompleteBody(BaseModel):
    exercise_scores: list[float] = []
    duration_s: int = 0


class LessonFinalizeBody(BaseModel):
    responses: list[str] = []
    # Intitulés réellement affichés (le sas de langue a les siens, traduits) :
    # sans eux, les réflexions seraient persistées sous les libellés du lecteur.
    questions: list[str] = []


class PlacementSubmitBody(BaseModel):
    language: str
    answers: dict = {}


@router.get("/languages")
def languages() -> list[dict]:
    return list_languages()


@router.get("/profile")
def profile(language: str) -> dict:
    return get_language_profile(language)


@router.get("/stats")
def stats() -> list[dict]:
    """Vue par langue (score global + niveau + compétences) pour la page profil."""
    return lang_stats_overview()


@router.get("/warmup-cards")
def warmup_cards(language: str) -> list[dict]:
    """Cartes du warm-up (SAS d'entrée) filtrées par langue."""
    return lang_warmup_cards(language)


@router.get("/session-types")
def session_types() -> list[dict]:
    return [
        {"code": c, "phase": ph, "skill": sk, "label": lb, "render_kind": rk}
        for (c, ph, sk, lb, _desc, rk) in SESSION_TYPES_SEED
    ]


@router.post("/session")
def session(body: LessonBody) -> dict:
    return generate_session(body.language)


@router.post("/session/complete")
def session_complete(body: SessionCompleteBody) -> dict:
    return complete_session(body.language, body.session_type, body.score, body.duration_s)


@router.post("/correct")
def correct(body: CorrectBody) -> dict:
    return correct_attempt(body.language, body.target_phrase, body.user_attempt)


@router.post("/sr-review")
def sr_review(body: SrReviewBody) -> dict:
    """Boucle le pont SR : met à jour l'échéance d'une carte révisée en séance."""
    return review_lang_card(body.language, body.verdict, card_id=body.card_id, word=body.word)


@router.post("/lesson")
def lesson(body: LessonBody) -> dict:
    """DÉPRÉCIÉ — conservé le temps de la transition vers /lang/session."""
    return generate_lesson(body.language)


# ── Séances (10 exercices, arc 4 temps) ───────────────────────────────────────

@router.post("/lesson/start")
def lesson_start(body: LessonBody) -> dict:
    """Démarre une séance (ou demande le test de niveau si jamais passé)."""
    return start_lesson(body.language)


@router.get("/lesson/{lesson_id}/exercise/{index}")
def lesson_exercise(lesson_id: int, index: int) -> dict:
    return get_lesson_exercise(lesson_id, index)


@router.post("/lesson/{lesson_id}/complete")
def lesson_complete(lesson_id: int, body: LessonCompleteBody) -> dict:
    return complete_lesson(lesson_id, body.exercise_scores, body.duration_s)


@router.get("/lesson/{lesson_id}/analysis")
def lesson_analysis(lesson_id: int) -> dict:
    """Bilan LLM de la séance (best-effort) + décomposition par compétence."""
    return lang_lesson_analysis(lesson_id)


@router.post("/lesson/{lesson_id}/finalize")
def lesson_finalize(lesson_id: int, body: LessonFinalizeBody) -> dict:
    """Réflexions de métacognition + nudge du profil métacognitif global."""
    return finalize_lang_lesson(lesson_id, body.responses, questions=body.questions)


# ── Test de niveau (placement) ────────────────────────────────────────────────

@router.post("/placement/start")
def placement_start_route(body: LessonBody) -> dict:
    return placement_start(body.language)


@router.post("/placement/submit")
def placement_submit_route(body: PlacementSubmitBody) -> dict:
    return placement_submit(body.language, body.answers)


@router.post("/placement/skip")
def placement_skip_route(body: LessonBody) -> dict:
    return placement_skip(body.language)
