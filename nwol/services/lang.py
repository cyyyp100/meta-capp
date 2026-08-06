# services/lang.py — Base du module Langues (profil + progression).
#
# Périmètre actuel : sélection de langue, profil, progression. Le flux complet
# de leçons/exercices/corrections (LLM) reste un sous-système dédié à part.
from __future__ import annotations

import logging
import threading

from config.settings import LANGUAGE_SCRIPTS, LATIN_SCRIPT, SCRIPTS, TONAL_LANGUAGES
from db.lang_db import (
    SESSION_TYPE_LABEL,
    SESSION_TYPE_RENDER_KIND,
    complete_lang_lesson,
    create_lang_lesson,
    find_lang_flashcard_id,
    get_all_lang_profiles,
    get_curriculum,
    get_due_flashcards_for_language,
    get_exercises_cache,
    get_lang_errors_for_revision,
    get_lang_lesson,
    get_lang_lesson_count,
    get_lang_profile_by_id,
    get_lang_progress,
    get_lang_session_count,
    get_lesson_exercise_cache,
    get_or_create_lang_profile,
    get_recent_flashcards_for_language,
    get_skill_scores,
    save_curriculum,
    save_exercises_cache,
    save_lang_error,
    save_lang_exercise,
    save_lang_session,
    save_lesson_exercise_cache,
    update_lang_profile,
)
from db.user import DEFAULT_USER_ID
from llm.ollama_client import (
    evaluate_placement_async,
    generate_lang_correction_async,
    generate_lang_curriculum_async,
    generate_lang_lesson_async,
    generate_placement_test_async,
    generate_session_content_async,
)
from services.flashcards import create_lang_vocab_flashcards, review_flashcard
from services.lang_sequencer import LESSON_SIZE, decide_session_type, plan_lesson
from services.llm_bridge import run_llm_sync

logger = logging.getLogger("services.lang")

# Paliers de progression entre phases (en séances terminées, grain Assimil).
WRITING_TO_PASSIVE = 6              # alphabet fini (cyrillique, grec…) : phase d'écriture courte
WRITING_TO_PASSIVE_CONTINUOUS = 12  # script logographique (hanzi, kanji) : amorce plus longue
PASSIVE_TO_ACTIVE = 20              # fin de la vague passive -> vague active

# Préchargement de l'exercice suivant en tâche de fond (occupe le temps de lecture).
# Désactivable (tests déterministes : pas de thread concurrent sur la DB de test).
ENABLE_PREFETCH = True

__all__ = [
    "LANGUAGES",
    "list_languages",
    "get_language_script",
    "get_script_meta",
    "is_non_latin",
    "script_is_continuous",
    "script_is_rtl",
    "script_is_tonal",
    "writing_to_passive",
    "get_language_profile",
    "lang_stats_overview",
    "generate_lesson",
    "generate_session",
    "complete_session",
    "correct_attempt",
    "review_lang_card",
    "start_lesson",
    "get_lesson_exercise",
    "complete_lesson",
    "lang_warmup_cards",
    "lang_lesson_analysis",
    "finalize_lang_lesson",
    "placement_start",
    "placement_submit",
    "placement_skip",
]

# Catalogue des langues (code = nom français minuscule). Le `script` est dérivé
# de LANGUAGE_SCRIPTS ; `rtl` est exposé au frontend pour le rendu droite-à-gauche.
def _lang_entry(code: str, label: str, flag: str) -> dict:
    script = LANGUAGE_SCRIPTS.get(code, LATIN_SCRIPT)
    return {
        "code": code, "label": label, "flag": flag, "script": script,
        "rtl": bool(SCRIPTS.get(script, {}).get("rtl", False)),
    }


LANGUAGES = [
    _lang_entry("anglais", "Anglais", "🇬🇧"),
    _lang_entry("espagnol", "Espagnol", "🇪🇸"),
    _lang_entry("allemand", "Allemand", "🇩🇪"),
    _lang_entry("italien", "Italien", "🇮🇹"),
    _lang_entry("portugais", "Portugais", "🇵🇹"),
    _lang_entry("néerlandais", "Néerlandais", "🇳🇱"),
    _lang_entry("polonais", "Polonais", "🇵🇱"),
    _lang_entry("suédois", "Suédois", "🇸🇪"),
    _lang_entry("turc", "Turc", "🇹🇷"),
    _lang_entry("roumain", "Roumain", "🇷🇴"),
    _lang_entry("indonésien", "Indonésien", "🇮🇩"),
    _lang_entry("vietnamien", "Vietnamien", "🇻🇳"),
    _lang_entry("russe", "Russe", "🇷🇺"),
    _lang_entry("grec", "Grec", "🇬🇷"),
    _lang_entry("coréen", "Coréen", "🇰🇷"),
    _lang_entry("mandarin", "Mandarin", "🇨🇳"),
    _lang_entry("japonais", "Japonais", "🇯🇵"),
    _lang_entry("arabe", "Arabe", "🇸🇦"),
    _lang_entry("hébreu", "Hébreu", "🇮🇱"),
    _lang_entry("hindi", "Hindi", "🇮🇳"),
    _lang_entry("thaï", "Thaï", "🇹🇭"),
]


def list_languages() -> list[dict]:
    return LANGUAGES


def get_language_script(language: str) -> str:
    """Script intrinsèque de la langue ('latin' par défaut)."""
    return LANGUAGE_SCRIPTS.get((language or "").lower(), LATIN_SCRIPT)


def get_script_meta(language: str) -> dict:
    """Métadonnées du script d'une langue (kind/rtl/tonal/continuous/romanization).

    Repli sur la meta 'latin' pour toute langue/script inconnu (jamais d'exception).
    """
    return SCRIPTS.get(get_language_script(language), SCRIPTS[LATIN_SCRIPT])


def is_non_latin(language: str) -> bool:
    return get_language_script(language) != LATIN_SCRIPT


def script_is_continuous(language: str) -> bool:
    """Script logographique : caractères enseignés en continu (jamais 'finis')."""
    return bool(get_script_meta(language).get("continuous"))


def script_is_rtl(language: str) -> bool:
    """Écriture de droite à gauche (rendu frontend + consigne LLM)."""
    return bool(get_script_meta(language).get("rtl"))


def script_is_tonal(language: str) -> bool:
    """Langue à tons phonémiques (porté par le script OU par la langue, ex. vietnamien)."""
    return bool(get_script_meta(language).get("tonal")) or (language or "").lower() in TONAL_LANGUAGES


def writing_to_passive(language: str) -> int:
    """Nombre de séances d'écriture avant de passer à la phase passive.

    Court pour un alphabet fini (on « finit » l'alphabet) ; plus long pour un script
    logographique (hanzi/kanji) où l'amorce front-charge radicaux/traits/tons/kana et
    les caractères les plus fréquents — l'acquisition se poursuit ensuite en continu.
    """
    return WRITING_TO_PASSIVE_CONTINUOUS if script_is_continuous(language) else WRITING_TO_PASSIVE


def _initial_phase(language: str) -> str:
    """Phase d'entrée d'un profil neuf : 'writing' si script non-latin, sinon 'passive'."""
    return "writing" if is_non_latin(language) else "passive"


def get_language_profile(language: str, user_id: int = DEFAULT_USER_ID) -> dict:
    profile = _ensure_profile(user_id, language)
    progress = get_lang_progress(profile["id"])
    # Analyse poussée : score moyen 0–100 par compétence (compréhension écrite,
    # expression écrite, vocabulaire, …) sur tout l'historique d'exercices.
    progress["skills"] = get_skill_scores(profile["id"])
    meta = get_script_meta(language)
    return {
        "profile": profile,
        "progress": progress,
        "script": get_language_script(language),
        "rtl": script_is_rtl(language),
        "tonal": script_is_tonal(language),
        "script_kind": meta.get("kind"),
    }


def lang_stats_overview(user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Vue par langue pour la page profil : une entrée par langue étudiée.

    Renvoie le score global 0–100 (moyenne des séances), le niveau CEFR, le nombre
    de séances et la décomposition par compétence. N'inclut que les langues déjà
    jouées (au moins un exercice ou une séance), pour éviter d'afficher des langues
    vierges. Déterministe, jamais de LLM.
    """
    labels = {lang["code"]: lang for lang in LANGUAGES}
    overview: list[dict] = []
    for profile in get_all_lang_profiles(user_id):
        progress = get_lang_progress(profile["id"])
        if not progress.get("total_sessions") and not progress.get("total_lessons"):
            continue
        meta = labels.get(profile["language"], {})
        overview.append({
            "language": profile["language"],
            "label": meta.get("label", profile["language"]),
            "flag": meta.get("flag", ""),
            "level": profile.get("level") or "A1",
            "global_score": round(float(progress.get("avg_score") or 0.0), 1),
            "total_lessons": progress.get("total_lessons", 0),
            "skills": get_skill_scores(profile["id"]),
        })
    return overview


def _ensure_profile(user_id: int, language: str) -> dict:
    """Profil de langue, en posant la phase d'entrée correcte pour un profil tout neuf.

    `get_or_create_lang_profile` crée le profil avec la phase 'passive' par défaut
    (colonne DB). Pour un script non-latin et un profil n'ayant jamais joué, on
    bascule en phase 'writing' (intégration de l'écriture avant la phase passive).
    """
    profile = get_or_create_lang_profile(user_id, language)
    never_played = not profile.get("last_session") and get_lang_session_count(profile["id"]) == 0
    if never_played and is_non_latin(language) and profile.get("phase") != "writing":
        update_lang_profile(profile["id"], phase="writing", touch_last_session=False)
        profile = get_or_create_lang_profile(user_id, language)
    return profile


def _ensure_curriculum(language: str) -> list[dict]:
    existing = get_curriculum(language)
    if existing:
        return existing
    result = run_llm_sync(lambda ok, err: generate_lang_curriculum_async(language, ok, err), timeout=90)
    lessons = result.get("lessons") if isinstance(result, dict) else result if isinstance(result, list) else []
    if lessons:
        save_curriculum(language, lessons)
    return get_curriculum(language)


def generate_session(language: str, user_id: int = DEFAULT_USER_ID) -> dict:
    """Décide puis génère UNE session juste-à-temps (séquenceur adaptatif).

    Remplace l'ancien flux generate_lesson : plus de pré-curriculum monolithique.
    Deux appels courts (choix de type ~20s, contenu ciblé ~60s) au lieu d'un seul
    appel énorme qui dépassait le timeout sur gemma4:e2b.
    """
    profile = get_or_create_lang_profile(user_id, language)
    session_type, reason = decide_session_type(profile)
    weak_points = get_lang_errors_for_revision(profile["id"], limit=5)
    try:
        content = run_llm_sync(
            lambda ok, err: generate_session_content_async(
                language, session_type, profile, weak_points, ok, err
            ),
            timeout=60,  # un seul type de contenu : bien plus tenable qu'un curriculum entier
        )
    except Exception as exc:
        logger.warning("Génération de session échouée (%s) : %s", session_type, exc)
        content = None
    if not content:
        return {"error": "Génération indisponible (Ollama ?).", "session_type": session_type}
    return {
        "session_type": session_type,
        "render_kind": content.get("render_kind", SESSION_TYPE_RENDER_KIND.get(session_type)),
        "label": content.get("label", SESSION_TYPE_LABEL.get(session_type, session_type)),
        "reason": reason,
        "content": content,
    }


def complete_session(
    language: str,
    session_type: str,
    score: float,
    duration_s: int,
    user_id: int = DEFAULT_USER_ID,
) -> dict:
    """Clôture d'une session : écrit le résultat (DB, pas de LLM).

    C'est ce qui remplit la répartition des compétences (via session_type) dont
    le séquenceur se sert pour rééquilibrer les prochaines décisions.
    """
    profile = get_or_create_lang_profile(user_id, language)
    session_n = get_lang_session_count(profile["id"]) + 1
    save_lang_session(
        profile["id"], session_n, int(duration_s or 0), float(score or 0.0), session_type
    )
    return {"ok": True, "total_sessions": get_lang_session_count(profile["id"])}


def correct_attempt(
    language: str,
    target_phrase: str,
    user_attempt: str,
    user_id: int = DEFAULT_USER_ID,
) -> dict:
    """Corrige une production (types translation/production/dictation) et persiste
    les erreurs pour alimenter la révision adaptative (boucle fermée)."""
    profile = get_or_create_lang_profile(user_id, language)
    try:
        result = run_llm_sync(
            lambda ok, err: generate_lang_correction_async(
                language, target_phrase, user_attempt, ok, err
            ),
            timeout=30,
        )
    except Exception as exc:
        logger.warning("Correction indisponible : %s", exc)
        return {"error": "Correction indisponible (Ollama ?)."}
    if not result:
        return {"error": "Correction indisponible (Ollama ?)."}
    if result.get("verdict") in ("partial", "incorrect"):
        for c in result.get("corrections", []):
            word = (c.get("original") or "").strip()
            if word:
                # error_type catégorisé (Axe 2) → révision ciblée plus fine
                # (réviser « tes accords » plutôt qu'un mot isolé).
                error_type = (c.get("error_type") or "").strip() or "production"
                save_lang_error(profile["id"], 0, error_type, word, target_phrase)
    return result


def review_lang_card(
    language: str,
    verdict: str,
    *,
    card_id: int | None = None,
    word: str = "",
    user_id: int = DEFAULT_USER_ID,
) -> dict:
    """Boucle le pont SR : repousse/rapproche l'échéance d'une carte révisée en séance.

    C'est le CŒUR de l'Axe 1 (plan1) : sans cette mise à jour, réviser une carte SR
    dans une séance ne compterait pas pour la mémoire long terme — le pont serait
    décoratif. On retrouve la carte par son id (repli déterministe) ou par son mot
    (chemin LLM, matching accent-folded), puis on réutilise le SR global.
    """
    profile = get_or_create_lang_profile(user_id, language)
    if card_id is None:
        card_id = find_lang_flashcard_id(profile["id"], language, word)
    if card_id is None:
        return {"ok": False, "matched": False}
    verdict = verdict if verdict in ("correct", "partial", "incorrect") else "incorrect"
    try:
        review_flashcard(int(card_id), verdict)
    except Exception:
        logger.warning("Bouclage SR (carte %s) échoué", card_id, exc_info=True)
        return {"ok": False, "matched": True}
    return {"ok": True, "matched": True, "card_id": int(card_id)}


# ── Séances Assimil (10 exercices, arc 4 temps) ───────────────────────────────

def _vocab_items_from_exercise(content: dict) -> list[dict]:
    """Extrait les items de vocabulaire d'un exercice, quel que soit son render_kind.

    Normalise tout vers {word(cible), translation(FR)} attendu par
    create_lang_vocab_flashcards. Couvre dialogue/reading/vocabulary.
    """
    if not isinstance(content, dict):
        return []
    items: list[dict] = []
    for src_key in ("vocabulary", "items"):
        for it in content.get(src_key) or []:
            if isinstance(it, dict) and it.get("word") and it.get("translation"):
                items.append({"word": it["word"], "translation": it["translation"]})
    for g in content.get("glossary") or []:  # reading : glossaire = {word, translation}
        if isinstance(g, dict) and g.get("word") and g.get("translation"):
            items.append({"word": g["word"], "translation": g["translation"]})
    return items


def _harvest_vocab(language: str, content: dict, user_id: int) -> int:
    """Crée les flashcards de vocabulaire d'un exercice (best-effort, dédupliqué)."""
    items = _vocab_items_from_exercise(content)
    if not items:
        return 0
    try:
        return create_lang_vocab_flashcards(language, items, user_id)
    except Exception:
        logger.warning("Vocabulaire -> flashcards : échec non bloquant", exc_info=True)
        return 0


def _build_lesson_context(profile_id: int, lesson_id: int, up_to_index: int) -> str:
    """Contexte glissant : vocabulaire des exercices déjà générés de la séance.

    Donne au LLM de quoi enchaîner les 10 exercices de façon cohérente sans
    second appel : on relit le cache des exercices 0..up_to_index-1.
    """
    words: list[str] = []
    for i in range(max(0, up_to_index)):
        ex = get_lesson_exercise_cache(profile_id, lesson_id, i)
        for it in _vocab_items_from_exercise(ex or {}):
            words.append(f"{it['word']} ({it['translation']})")
        if len(words) >= 12:
            break
    return ", ".join(words[:12])


def _deterministic_revision_from_cards(due_cards: list[dict], session_type: str) -> dict | None:
    """Quiz de révision SANS LLM depuis les cartes SR dues (recto FR → verso cible).

    Filet de l'Axe 1 : la mémoire long terme ne doit jamais dépendre d'Ollama. Si
    la génération LLM du quiz échoue, on présente quand même les cartes dues en
    révision simple, en gardant `card_id` pour boucler l'échéance à la correction.
    """
    exercises = []
    for c in due_cards:
        front = (c.get("front") or "").strip()  # français
        back = (c.get("back") or "").strip()     # langue cible
        if not front or not back:
            continue
        exercises.append({
            "type": "translation", "prompt_fr": front, "expected": back,
            "target_word": back, "hint": "", "card_id": c.get("id"),
        })
    if not exercises:
        return None
    return {
        "kind": "revision", "render_kind": "revision", "session_type": session_type,
        "label": SESSION_TYPE_LABEL.get(session_type, session_type), "exercises": exercises,
    }


def _generate_exercise(language: str, profile: dict, lesson: dict, index: int) -> dict:
    """Génère (JIT) le contenu d'un exercice d'une séance, avec contexte de cohérence."""
    plan = lesson.get("plan") or {}
    slots = plan.get("slots") or []
    slot = slots[index]
    context = _build_lesson_context(profile["id"], lesson["id"], index)
    aug_profile = {
        **profile,
        "level": plan.get("level", profile.get("level", "A1")),
        "lesson_theme": plan.get("theme", ""),
        "lesson_context": context,
        "difficulty_target": plan.get("difficulty_target"),
    }
    weak_points = get_lang_errors_for_revision(profile["id"], limit=5)
    # Pont SR → séance : sur un slot de révision, on repêche les cartes dues pour
    # enrichir le quiz (et servir de repli déterministe si Ollama est éteint).
    due_cards: list[dict] = []
    if slot["render_kind"] == "revision":
        due_cards = get_due_flashcards_for_language(profile["id"], language, limit=8)
    try:
        content = run_llm_sync(
            lambda ok, err: generate_session_content_async(
                language, slot["exercise_type"], aug_profile, weak_points, ok, err,
                due_cards=due_cards,
            ),
            timeout=60,
        )
    except Exception as exc:
        logger.warning("Exercice %d (%s) échoué : %s", index, slot["exercise_type"], exc)
        content = None
    if not isinstance(content, dict):
        # Filet déterministe (Axe 1) : révision des cartes dues même sans LLM.
        content = _deterministic_revision_from_cards(due_cards, slot["exercise_type"])
        if not isinstance(content, dict):
            return {
                "error": "Génération indisponible (Ollama ?).",
                "render_kind": slot["render_kind"],
                "temps": slot["temps"],
                "slot_index": index,
            }
    content["temps"] = slot["temps"]
    content["slot_index"] = index
    return content


def _prefetch_exercise(language: str, profile: dict, lesson: dict, index: int) -> None:
    """Pré-génère l'exercice `index` en tâche de fond (occupe le temps de lecture).

    La file LLM est sérialisée : ce prefetch s'exécute après la requête courante.
    Best-effort, totalement isolé (jamais bloquant pour l'UI).
    """
    if not ENABLE_PREFETCH:
        return
    slots = (lesson.get("plan") or {}).get("slots") or []
    if index < 0 or index >= len(slots):
        return
    if get_lesson_exercise_cache(profile["id"], lesson["id"], index) is not None:
        return

    def _job() -> None:
        try:
            if get_lesson_exercise_cache(profile["id"], lesson["id"], index) is not None:
                return
            content = _generate_exercise(language, profile, lesson, index)
            if not content.get("error"):
                save_lesson_exercise_cache(profile["id"], lesson["id"], index, content)
                _harvest_vocab(language, content, profile.get("user_id", DEFAULT_USER_ID))
        except Exception:
            logger.debug("Prefetch exercice %d ignoré", index, exc_info=True)

    threading.Thread(target=_job, daemon=True).start()


def _public_plan(plan: dict) -> list[dict]:
    """Métadonnées des slots exposées au frontend (sans le contenu généré)."""
    return [
        {
            "slot_index": s["slot_index"],
            "temps": s["temps"],
            "label": s["label"],
            "render_kind": s["render_kind"],
        }
        for s in (plan.get("slots") or [])
    ]


def start_lesson(language: str, user_id: int = DEFAULT_USER_ID) -> dict:
    """Démarre une SÉANCE (10 exercices). Gate test de niveau si jamais passé.

    Construit le plan (arc 4 temps), crée la séance, génère l'exercice 0 et
    précharge l'exercice 1. Cohérent avec la philosophie juste-à-temps.
    """
    profile = _ensure_profile(user_id, language)
    if not profile.get("placement_done"):
        return {
            "needs_placement": True,
            "language": language,
            "script": get_language_script(language),
        }
    plan = plan_lesson(profile)
    lesson_n = get_lang_lesson_count(profile["id"]) + 1
    lesson_id = create_lang_lesson(
        profile["id"], lesson_n,
        theme=plan["theme"], dialogue=None, plan=plan, level=plan["level"],
    )
    first = get_lesson_exercise(lesson_id, 0, user_id)
    return {
        "lesson_id": lesson_id,
        "theme": plan["theme"],
        "level": plan["level"],
        "phase": plan["phase"],
        "difficulty_target": plan.get("difficulty_target"),
        "size": LESSON_SIZE,
        "plan": _public_plan(plan),
        "index": 0,
        "exercise": first.get("exercise"),
        "error": first.get("error"),
    }


def get_lesson_exercise(lesson_id: int, index: int, user_id: int = DEFAULT_USER_ID) -> dict:
    """Sert l'exercice `index` d'une séance (cache sinon génération JIT) + précharge le suivant."""
    lesson = get_lang_lesson(lesson_id)
    if not lesson:
        return {"error": "Séance introuvable."}
    profile = get_lang_profile_by_id(lesson["profile_id"])
    if not profile:
        return {"error": "Profil introuvable."}
    profile = {**profile, "user_id": user_id}
    language = profile["language"]
    slots = (lesson.get("plan") or {}).get("slots") or []
    if index < 0 or index >= len(slots):
        return {"error": "Index d'exercice invalide."}

    cached = get_lesson_exercise_cache(profile["id"], lesson_id, index)
    if cached is not None:
        content = cached
    else:
        content = _generate_exercise(language, profile, lesson, index)
        if not content.get("error"):
            save_lesson_exercise_cache(profile["id"], lesson_id, index, content)
            _harvest_vocab(language, content, user_id)

    _prefetch_exercise(language, profile, lesson, index + 1)
    return {
        "lesson_id": lesson_id,
        "index": index,
        "size": len(slots),
        "exercise": content,
        "error": content.get("error"),
    }


def _advance_after_lesson(profile: dict, language: str) -> None:
    """Avance la progression après une séance terminée (compteur + paliers de phase)."""
    completed = get_lang_lesson_count(profile["id"])  # inclut celle qu'on vient de clôturer
    phase = profile.get("phase", "passive")
    new_phase = phase
    if phase == "writing" and completed >= writing_to_passive(language):
        new_phase = "passive"
    elif phase == "passive" and completed >= PASSIVE_TO_ACTIVE:
        new_phase = "active"
    update_lang_profile(
        profile["id"],
        current_lesson=int(profile.get("current_lesson") or 1) + 1,
        phase=new_phase if new_phase != phase else None,
        touch_last_session=True,
    )


def complete_lesson(
    lesson_id: int,
    exercise_scores: list,
    duration_s: int,
    user_id: int = DEFAULT_USER_ID,
) -> dict:
    """Clôture une séance : score, traçage par exercice (compétences), erreurs, progression."""
    lesson = get_lang_lesson(lesson_id)
    if not lesson:
        return {"error": "Séance introuvable."}
    profile = get_lang_profile_by_id(lesson["profile_id"])
    if not profile:
        return {"error": "Profil introuvable."}
    slots = (lesson.get("plan") or {}).get("slots") or []
    scores = [float(s) for s in (exercise_scores or []) if isinstance(s, (int, float))]
    avg01 = (sum(scores) / len(scores)) if scores else 0.0

    for i, slot in enumerate(slots):
        sc = exercise_scores[i] if exercise_scores and i < len(exercise_scores) else 0.0
        save_lang_exercise(
            profile["id"], lesson_id, lesson["lesson_n"], i,
            slot["temps"], slot["exercise_type"], float(sc or 0.0),
        )
        # Boucle d'erreurs : si un exercice a auto-identifié une faiblesse (clôture).
        ex = get_lesson_exercise_cache(profile["id"], lesson_id, i)
        cloture = (ex or {}).get("cloture") if isinstance(ex, dict) else None
        log_err = cloture.get("log_error") if isinstance(cloture, dict) else None
        if isinstance(log_err, dict) and log_err.get("word"):
            save_lang_error(
                profile["id"], lesson["lesson_n"],
                log_err.get("error_type") or "vocabulaire",
                log_err["word"], log_err.get("context", ""),
            )

    complete_lang_lesson(lesson_id, score=round(avg01 * 100, 1), duration_s=duration_s)
    _advance_after_lesson(profile, profile["language"])
    return {"ok": True, "total_lessons": get_lang_lesson_count(profile["id"])}


# ── Rituel de séance (SAS entrée/sortie, calqué sur le flux PDF) ───────────────

def lang_warmup_cards(language: str, limit: int = 5, user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Cartes de warm-up pour le SAS d'entrée d'une séance de langue.

    Cartes dues d'abord (pont SR), complétées par les cartes récentes de la langue
    si trop peu sont dues, pour garantir un warm-up. Recto FR / verso langue cible
    (convention des flashcards de vocabulaire). Best-effort, jamais bloquant.
    """
    profile = _ensure_profile(user_id, language)
    cards = get_due_flashcards_for_language(profile["id"], language, limit=limit)
    if len(cards) < limit:
        seen = {c["id"] for c in cards}
        for extra in get_recent_flashcards_for_language(profile["id"], language, limit=limit):
            if extra["id"] not in seen:
                cards.append(extra)
            if len(cards) >= limit:
                break
    return [{"id": c["id"], "front": c["front"], "back": c["back"]} for c in cards[:limit]]


def lang_lesson_analysis(lesson_id: int, user_id: int = DEFAULT_USER_ID) -> dict:
    """Bilan LLM best-effort d'une séance (équivalent de session_analysis pour le PDF).

    Construit un contexte langue (thème, niveau, score, compétences, points faibles)
    et réutilise le « session summary » du moteur. Renvoie {"analysis", "skills"} ;
    analysis vide si Ollama indisponible. La décomposition par compétence (`skills`)
    est toujours fournie (déterministe)."""
    lesson = get_lang_lesson(lesson_id)
    if not lesson:
        return {"analysis": "", "skills": {}}
    profile = get_lang_profile_by_id(lesson["profile_id"])
    if not profile:
        return {"analysis": "", "skills": {}}
    skills = get_skill_scores(profile["id"])
    slots = (lesson.get("plan") or {}).get("slots") or []
    context = {
        "session_data": {
            "duration_s": int(lesson.get("duration_s") or 0),
            "questions_answered": len(slots),
            "success_rate": round(float(lesson.get("score") or 0.0)),
            "language": profile["language"],
            "theme": lesson.get("theme"),
            "level": lesson.get("level"),
            "skills": skills,
            "weak_points": get_lang_errors_for_revision(profile["id"], limit=5),
        },
    }
    try:
        from llm.ollama_client import generate_session_summary_async

        result = run_llm_sync(
            lambda ok, err: generate_session_summary_async(context, ok, err),
            timeout=45,
        )
        summary = (result or {}).get("session_summary") or {}
        return {"analysis": str(summary.get("qualitative_summary") or ""), "skills": skills}
    except Exception:  # pragma: no cover - best-effort, LLM indisponible
        return {"analysis": "", "skills": skills}


def finalize_lang_lesson(lesson_id: int, responses: list, user_id: int = DEFAULT_USER_ID) -> dict:
    """Finalisation métacognitive d'une séance : réflexions + nudge du profil global.

    Comme la finalisation d'une session PDF, mais sans session de lecture
    (session_id=None) : les réponses de métacognition et le score de séance font
    glisser les 6 jauges du profil et régénèrent l'analyse générale de Gemma."""
    lesson = get_lang_lesson(lesson_id)
    if not lesson:
        return {"error": "Séance introuvable."}
    profile = get_lang_profile_by_id(lesson["profile_id"])
    if not profile:
        return {"error": "Profil introuvable."}
    owner = int(profile.get("user_id") or user_id)
    score = float(lesson.get("score") or 0.0)  # 0–100 (séance déjà clôturée)
    slots = (lesson.get("plan") or {}).get("slots") or []
    metrics = {
        "duration_s": int(lesson.get("duration_s") or 0),
        "pages_read": 0,
        "questions_answered": len(slots),
        "correct": 0,
        "success_rate": round(score),
        "language": profile["language"],
        "theme": lesson.get("theme"),
    }
    try:
        from services.session import nudge_metacog_profile

        nudge_metacog_profile(owner, score, list(responses or []), metrics, session_id=None)
    except Exception:  # pragma: no cover - best-effort : la clôture ne doit pas casser
        logger.debug("Nudge métacognitif (langue) ignoré", exc_info=True)
    return {"ok": True, "score": score}


# ── Test de niveau (placement) ────────────────────────────────────────────────

def _entry_point_from_cefr(language: str, cefr: str, can_read_script: bool) -> tuple[str, int]:
    """Mappe le niveau CEFR estimé vers (phase d'entrée, n° de leçon de départ).

    Pour un script logographique (mandarin/japonais), l'apprentissage des caractères
    se poursuit de toute façon en continu (slot « nouveaux caractères » par séance,
    cf. lang_sequencer.plan_lesson) : même un apprenant sachant lire n'« épuise » pas
    le système d'écriture — la phase d'entrée ne décide que de l'amorce front-chargée.
    """
    if is_non_latin(language) and not can_read_script:
        return "writing", 1
    if cefr in ("B1", "B2", "C1", "C2"):
        return "active", 1
    if cefr == "A2":
        return "passive", 6
    return "passive", 1


def _heuristic_cefr(test: dict, answers: dict) -> tuple[str, bool]:
    """Repli sans LLM : ratio de bonnes réponses QCM -> niveau ; lecture script -> can_read."""
    total = correct = 0
    script_items = script_ok = 0
    for it in test.get("items") or []:
        if it.get("format") != "qcm":
            continue
        total += 1
        ans = str(answers.get(str(it.get("id")), answers.get(it.get("id"), ""))).strip().upper()[:1]
        good = ans == it.get("correct")
        correct += 1 if good else 0
        if it.get("skill") == "ecriture":
            script_items += 1
            script_ok += 1 if good else 0
    ratio = (correct / total) if total else 0.0
    cefr = "A1"
    for threshold, level in ((0.85, "C1"), (0.7, "B2"), (0.55, "B1"), (0.35, "A2")):
        if ratio >= threshold:
            cefr = level
            break
    can_read = script_items == 0 or (script_ok / script_items) >= 0.5
    return cefr, can_read


def placement_skip(language: str, user_id: int = DEFAULT_USER_ID) -> dict:
    """L'apprenant déclare n'avoir jamais étudié la langue : pas de test, point d'entrée débutant."""
    profile = _ensure_profile(user_id, language)
    phase = _initial_phase(language)
    update_lang_profile(
        profile["id"], level="A1", phase=phase, placement_done=1,
        current_lesson=1, touch_last_session=False,
    )
    return {"ok": True, "level": "A1", "phase": phase}


def placement_start(language: str, user_id: int = DEFAULT_USER_ID) -> dict:
    """Génère un test de niveau complet et le mémorise (correction côté serveur au submit)."""
    profile = _ensure_profile(user_id, language)
    script = get_language_script(language)
    try:
        # Gate joué une seule fois par langue : timeout généreux (couvre le chargement
        # à froid du modèle, souvent le tout premier appel LLM pour cette langue).
        test = run_llm_sync(
            lambda ok, err: generate_placement_test_async(language, script, ok, err),
            timeout=150,
        )
    except Exception as exc:
        logger.warning("Test de niveau indisponible : %s", exc)
        test = None
    if not test or not test.get("items"):
        return {"error": "Test de niveau indisponible (Ollama ?)."}
    # Stocke le test complet (avec réponses) pour la correction ; n'expose que le public.
    save_exercises_cache(profile["id"], 0, "placement", test)
    public_items = []
    for it in test["items"]:
        pub = {"id": it["id"], "format": it["format"], "question": it["question"]}
        if it["format"] == "qcm":
            pub["choices"] = it.get("choices", [])
        public_items.append(pub)
    return {"items": public_items}


def placement_submit(language: str, answers: dict, user_id: int = DEFAULT_USER_ID) -> dict:
    """Corrige le test, estime le CEFR (LLM + repli heuristique) et fixe le point d'entrée."""
    profile = _ensure_profile(user_id, language)
    test = get_exercises_cache(profile["id"], 0, "placement")
    if not test or not test.get("items"):
        return {"error": "Test expiré, recommence."}
    answers = answers or {}
    lines = []
    for it in test["items"]:
        ans = answers.get(str(it.get("id")), answers.get(it.get("id"), ""))
        if it.get("format") == "qcm":
            good = str(ans).strip().upper()[:1] == it.get("correct")
            lines.append(f"item {it['id']} ({it['level']}, {it.get('skill','')}): {'correct' if good else 'incorrect'}")
        else:
            lines.append(
                f"item {it['id']} ({it['level']}, production): reponse='{str(ans).strip()}' attendu='{it.get('expected','')}'"
            )
    summary = "\n".join(lines)
    try:
        ev = run_llm_sync(
            lambda ok, err: evaluate_placement_async(language, summary, ok, err),
            timeout=30,
        )
    except Exception as exc:
        logger.info("Éval CEFR LLM indisponible (%s), repli heuristique", exc)
        ev = None
    if isinstance(ev, dict) and ev.get("cefr"):
        cefr, can_read = ev["cefr"], bool(ev.get("can_read_script", False))
        comment = ev.get("comment", "")
    else:
        cefr, can_read = _heuristic_cefr(test, answers)
        comment = ""
    phase, current_lesson = _entry_point_from_cefr(language, cefr, can_read)
    update_lang_profile(
        profile["id"], level=cefr, phase=phase, placement_done=1,
        current_lesson=current_lesson, touch_last_session=False,
    )
    return {"ok": True, "level": cefr, "phase": phase, "comment": comment}


def generate_lesson(language: str, user_id: int = DEFAULT_USER_ID) -> dict:
    """DÉPRÉCIÉ — ancien flux curriculum + leçon (gardé pour l'alias /lang/lesson).

    Remplacé par generate_session (séquenceur adaptatif). Ne plus utiliser :
    _ensure_curriculum génère un curriculum entier qui dépasse le timeout."""
    profile = get_or_create_lang_profile(user_id, language)
    curriculum = _ensure_curriculum(language)
    if not curriculum:
        return {"error": "Curriculum indisponible (Ollama ?)."}
    lesson_n = int(profile.get("current_lesson") or 1)
    row = next((c for c in curriculum if int(c.get("lesson_n", 0)) == lesson_n), curriculum[0])
    lesson = run_llm_sync(
        lambda ok, err: generate_lang_lesson_async(language, int(row.get("lesson_n", 1)), row, ok, err),
        timeout=90,
    )
    return {
        "lesson_n": int(row.get("lesson_n", 1)),
        "theme": row.get("theme", ""),
        "dialogue": (lesson or {}).get("dialogue", []),
        "notes": (lesson or {}).get("notes", {}),
        "vocabulary": (lesson or {}).get("vocabulary", []),
    }
