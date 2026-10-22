# server/routers/lang.py — Module Langues (profil, séances, feuilleton).
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config.settings import LANG_CORRECTION_MAX_CHARS, LANG_NAME_MAX_CHARS, LANG_WRITING_MAX_CHARS
from services import lang_hook, lang_runs, lang_writing
from services.lang import (
    complete_lesson,
    correct_attempt,
    finalize_lang_lesson,
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


class CorrectBody(BaseModel):
    # Le service coupe à LANG_CORRECTION_MAX_CHARS ; ici, seulement un
    # garde-fou contre une requête démesurée. La langue entre telle quelle
    # dans le prompt : elle est bornée ici.
    language: str = Field(max_length=LANG_NAME_MAX_CHARS)
    target_phrase: str = Field(max_length=LANG_CORRECTION_MAX_CHARS * 4)
    user_attempt: str = Field(max_length=LANG_CORRECTION_MAX_CHARS * 4)


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


@router.post("/correct")
def correct(body: CorrectBody) -> dict:
    return correct_attempt(body.language, body.target_phrase, body.user_attempt)


@router.post("/sr-review")
def sr_review(body: SrReviewBody) -> dict:
    """Boucle le pont SR : met à jour l'échéance d'une carte révisée en séance."""
    return review_lang_card(body.language, body.verdict, card_id=body.card_id, word=body.word)


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


class WritingBody(BaseModel):
    # Le service normalise et coupe à LANG_WRITING_MAX_CHARS ; ici, seulement
    # un garde-fou contre une requête démesurée.
    text: str = Field(default="", max_length=LANG_WRITING_MAX_CHARS * 4)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (lang_runs.RunError, lang_writing.WritingError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/upcoming")
def feuilleton_upcoming() -> list[dict]:
    """L'épisode suivant de chaque langue ouverte (prêt, en écriture…), en
    lecture seule : l'annonce « épisode prêt » et les pastilles de la page Langues."""
    return lang_runs.upcoming_episodes()


@router.get("/{language}/status")
def feuilleton_status(language: str) -> dict:
    """E9 : écran d'accueil d'une langue (épisode prêt, génération, niveau)."""
    return _call(lang_runs.language_status, language)


@router.post("/{language}/next/ensure")
def feuilleton_next_ensure(language: str) -> dict:
    """L'épisode suivant n'est ni prêt ni en cours d'écriture : il repart (même
    règle qu'au démarrage). Le GET `status` reste en lecture seule."""
    return _call(lang_runs.ensure_next, language)


@router.get("/{language}/hook")
def feuilleton_hook(language: str) -> dict:
    """L'accroche du sas d'entrée sur l'épisode que la séance va faire
    découvrir, écrite par Clikoda pendant le sas ; vide sans épisode neuf ou
    sans Clikoda (`lang_hook.entry_hook`)."""
    return {"hook": _call(lang_hook.entry_hook, language)}


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
    """E3 : plan complet de la séance, dans le mode que choisit le serveur."""
    return _call(lang_runs.start_run, language, body.warmup)


@router.get("/run/{run_id}")
def feuilleton_run(run_id: int) -> dict:
    return _call(lang_runs.run_view, run_id)


@router.post("/run/{run_id}/events")
def feuilleton_run_events(run_id: int, body: RunEventsBody) -> dict:
    return _call(lang_runs.record_events, run_id, body.events, body.current_step)


@router.post("/run/{run_id}/complete")
def feuilleton_run_complete(run_id: int, body: RunCompleteBody) -> dict:
    return _call(lang_runs.complete_run, run_id, body.end_reason, body.feeling)


@router.get("/run/{run_id}/lesson")
def feuilleton_run_lesson(run_id: int) -> dict:
    """La leçon de l'étape « leçon », relue en y entrant (sans attente)."""
    return _call(lang_runs.run_lesson, run_id)


@router.post("/run/{run_id}/writing")
def feuilleton_run_writing(run_id: int, body: WritingBody) -> dict:
    """L'expression écrite de la séance ; sa correction part en arrière-plan."""
    return _call(lang_writing.submit, run_id, body.text)


@router.get("/writing/{writing_id}")
def feuilleton_writing(writing_id: int) -> dict:
    return _call(lang_writing.get, writing_id)


@router.post("/writing/{writing_id}/seen")
def feuilleton_writing_seen(writing_id: int) -> dict:
    return _call(lang_writing.mark_seen, writing_id)


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
