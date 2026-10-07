# server/routers/lang.py — Module Langues (profil + séquenceur adaptatif).
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db.lang_db import SESSION_TYPES_SEED
from services import lang_runs
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
    # None = exercice sans aucun item noté : il ne compte pas dans la moyenne (K1).
    exercise_scores: list[float | None] = []
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


@router.get("/warmup-cards")
def warmup_cards(language: str) -> list[dict]:
    """Cartes du warm-up (SAS d'entrée) filtrées par langue, `WARMUP_MAX_CARDS`
    au plus : dues d'abord, puis récentes (E10)."""
    if lang_runs.is_pilot(language):
        return lang_runs.warmup_cards(language)
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



# ── Méthode « feuilleton » (langues du pilote, plan § 15.1) ──────────────────
# Aucun de ces endpoints n'attend Clikoda : ils répondent immédiatement, la
# génération des épisodes tourne en tâche de fond (services/lang_episodes.py).
# La logique vit dans services/lang_runs.py ; ici, seulement la forme HTTP.

class OnboardingBody(BaseModel):
    interests: list[str] = Field(default_factory=list, max_length=12)
    has_studied: bool = False


class PlacementAnswersBody(BaseModel):
    answers: dict[str, int] = Field(default_factory=dict)


class RunStartBody(BaseModel):
    mode: str | None = None
    # Cartes révisées au sas d'entrée (E10) ; le service les borne lui-même.
    warmup: int = 0


class RunEventsBody(BaseModel):
    events: list[dict] = Field(default_factory=list, max_length=2000)
    current_step: str | None = None


class RunCompleteBody(BaseModel):
    end_reason: str = "fini"
    feeling: str | None = None


class ReportBody(BaseModel):
    episode_id: int
    line: int | None = None
    token: int | None = None
    kind: str = "autre"
    comment: str = ""


class CompareBody(BaseModel):
    original: str = Field(default="", max_length=2000)
    typed: str = Field(default="", max_length=2000)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except lang_runs.RunError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{language}/status")
def feuilleton_status(language: str) -> dict:
    """E9 : écran d'accueil d'une langue (épisode prêt, génération, niveau)."""
    return _call(lang_runs.language_status, language)


@router.post("/{language}/onboarding")
def feuilleton_onboarding(language: str, body: OnboardingBody) -> dict:
    return _call(lang_runs.onboarding, language, body.interests, body.has_studied)


@router.get("/{language}/placement")
def feuilleton_placement(language: str) -> dict:
    """E2 : items du test de niveau, SANS les clés."""
    return _call(lang_runs.placement_items, language)


@router.post("/{language}/placement/submit")
def feuilleton_placement_submit(language: str, body: PlacementAnswersBody) -> dict:
    return _call(lang_runs.placement_submit, language, body.answers)


@router.post("/{language}/run/start")
def feuilleton_run_start(language: str, body: RunStartBody) -> dict:
    """E3 : plan complet de la séance (mode facultatif : court, relecture)."""
    mode = body.mode if body.mode in ("court", "relecture") else None
    return _call(lang_runs.start_run, language, mode, body.warmup)


@router.get("/run/{run_id}")
def feuilleton_run(run_id: int) -> dict:
    return _call(lang_runs.run_view, run_id)


@router.post("/run/{run_id}/events")
def feuilleton_run_events(run_id: int, body: RunEventsBody) -> dict:
    return _call(lang_runs.record_events, run_id, body.events, body.current_step)


@router.post("/run/{run_id}/complete")
def feuilleton_run_complete(run_id: int, body: RunCompleteBody) -> dict:
    return _call(lang_runs.complete_run, run_id, body.end_reason, body.feeling)


@router.get("/{language}/library")
def feuilleton_library(language: str) -> list[dict]:
    return _call(lang_runs.library, language)


@router.get("/episode/{episode_id}")
def feuilleton_episode(episode_id: int) -> dict:
    return _call(lang_runs.episode_view, episode_id)


@router.post("/report")
def feuilleton_report(body: ReportBody) -> dict:
    return _call(lang_runs.report, body.episode_id, body.line, body.token, body.kind, body.comment)


@router.post("/compare")
def feuilleton_compare(body: CompareBody) -> dict:
    """N5 : différences entre l'original et une retraduction saisie."""
    return lang_runs.compare_retranslation(body.original, body.typed)


@router.post("/{language}/rewind")
def feuilleton_rewind(language: str) -> dict:
    """§ 14.2 : l'apprenant accepte de relire les derniers épisodes."""
    return _call(lang_runs.accept_rewind, language)
