# services/lang_sequencer.py — Séquenceur adaptatif des sessions de langue.
#
# Décide JUSTE le type de la prochaine session (jamais son contenu). C'est la
# séparation qui manquait à l'ancien _ensure_curriculum (qui mélangeait décision
# et génération en un seul appel monolithique trop lourd pour gemma4:e2b).
#
# Le LLM est un BONUS, pas une dépendance bloquante : un fallback déterministe
# garantit qu'une session démarre toujours, même Ollama éteint.
from __future__ import annotations

import logging

from db.lang_db import (
    SESSION_TYPE_LABEL,
    SESSION_TYPE_RENDER_KIND,
    get_due_flashcards_for_language,
    get_flashcard_count,
    get_lang_errors_for_revision,
    get_lang_session_count,
    get_last_completed_lesson_difficulty,
    get_last_lesson_theme,
    get_last_session_type,
    get_recent_lesson_score_avg,
    get_session_types_for_phase,
    get_skill_distribution,
    log_sequencer_decision,
)
from llm.ollama_client import choose_session_type_async, plan_lesson_async
from services.llm_bridge import run_llm_sync

logger = logging.getLogger("services.lang_sequencer")

# Une session de révision est imposée toutes les N sessions, sans appeler le LLM.
REVISION_EVERY = 7

# ── Planificateur de séance (arc Assimil à 4 temps sur 10 exercices) ───────────
#
# Une séance = 10 exercices joués en séquence. L'arc impose le RÔLE de chaque slot
# (ancrage → exposition → manipulation → clôture) ; le type concret de chaque slot
# est choisi parmi les types affinitaires disponibles pour la phase, en équilibrant
# les compétences. Construction déterministe (robuste hors-ligne) ; le LLM n'ajoute
# qu'un thème fédérateur.
LESSON_SIZE = 10
ARC_TEMPLATE: list[str] = (
    ["ancrage"] + ["exposition"] * 3 + ["manipulation"] * 5 + ["cloture"]
)  # 1 + 3 + 5 + 1 = 10

# Types affinitaires par temps (intersection avec les types disponibles pour la
# phase ; repli sur tous les types disponibles si l'intersection est vide). La
# liste « manipulation » mêle types actifs (production) et passifs (compréhension) :
# le filtre de phase sélectionne naturellement les bons.
TEMPS_AFFINITY: dict[str, list[str]] = {
    "ancrage": [
        "revision_adaptative", "vocabulaire_contextuel", "appariement", "ecriture_lecture",
    ],
    "exposition": [
        "dialogue_lecture", "dialogue_ecoute", "vocabulaire_contextuel",
        "histoire_courte", "culture_courte", "ecriture_decouverte", "ecriture_lecture",
    ],
    # Cœur de la séance : on densifie avec les types interactifs (la marche
    # manquante entre reconnaître et produire — manipulation active sans
    # production totale), corrigés côté client donc robustes hors-ligne.
    "manipulation": [
        "completion_choix", "cloze_libre", "remise_en_ordre", "construction_phrase",
        "transformation", "traduction_inverse", "dictee_courte", "rappel_production",
        "reformulation_libre", "mini_dialogue_simule", "correction_guidee",
        "ecriture_dictee", "ecriture_lecture", "vocabulaire_contextuel",
        "histoire_courte", "culture_courte",
    ],
    "cloture": [
        "revision_adaptative", "appariement", "vocabulaire_contextuel", "ecriture_lecture",
    ],
}

# Thèmes de repli si le LLM est indisponible (rotation par n° de séance).
_FALLBACK_THEMES = [
    "Les salutations", "Au café", "La famille", "Les achats", "Les transports",
    "Le temps qu'il fait", "Au restaurant", "La maison", "Le travail", "Les loisirs",
]

# Personnages récurrents (fil rouge affectif). Déterministe par profil (pas de
# colonne DB) : l'apprenant retrouve le même prénom de séance en séance.
_RECURRING_CHARACTERS = [
    "Marco", "Léa", "Sofia", "Tom", "Nina", "Lucas", "Emma", "Yann", "Clara", "Hugo",
]


def _recurring_character(profile: dict) -> str:
    return _RECURRING_CHARACTERS[int(profile.get("id", 0)) % len(_RECURRING_CHARACTERS)]


def build_sequencer_state(profile: dict) -> dict:
    """État condensé nécessaire au choix. AUCUN appel LLM ici (lecture DB pure)."""
    profile_id = profile["id"]
    language = profile.get("language", "")
    return {
        "session_n": get_lang_session_count(profile_id) + 1,
        "phase": profile.get("phase", "passive"),
        "last_session_type": get_last_session_type(profile_id),
        "skill_distribution_7": get_skill_distribution(profile_id, window=REVISION_EVERY),
        "weak_points": get_lang_errors_for_revision(profile_id, limit=5),
        # Pont SR → séance : nombre de cartes dues (alimente l'ancrage/clôture même
        # sans erreur récente — 2e vague Assimil).
        "due_count": len(get_due_flashcards_for_language(profile_id, language, limit=8)),
        # Fil rouge entre séances (Axe 4) : thème précédent + personnage récurrent.
        "previous_theme": get_last_lesson_theme(profile_id),
        "character": _recurring_character(profile),
    }


def decide_session_type(profile: dict) -> tuple[str, str]:
    """Retourne (type_choisi, raison). Règles forcées d'abord, LLM en dernier recours."""
    state = build_sequencer_state(profile)
    session_n = state["session_n"]
    profile_id = profile["id"]

    # Règle forcée : révision périodique (toutes les REVISION_EVERY sessions).
    if session_n % REVISION_EVERY == 0:
        reason = f"Révision périodique (toutes les {REVISION_EVERY} sessions)"
        log_sequencer_decision(profile_id, session_n, "revision_adaptative", reason)
        return "revision_adaptative", reason

    available = get_session_types_for_phase(state["phase"])
    valid_codes = {t["code"] for t in available}

    chosen: str | None = None
    reason = ""
    try:
        result = run_llm_sync(
            lambda ok, err: choose_session_type_async(state, available, ok, err),
        )
        if isinstance(result, dict):
            chosen = result.get("chosen_type")
            reason = result.get("reason", "")
    except Exception as exc:  # Ollama indisponible / timeout / réponse illisible
        logger.info("Séquenceur : LLM indisponible (%s), fallback déterministe", exc)

    # Fallback si le LLM échoue ou renvoie un type invalide.
    if not chosen or chosen not in valid_codes:
        chosen = _fallback_choice(state, available)
        reason = "Choix déterministe (LLM indisponible ou réponse invalide)"

    log_sequencer_decision(profile_id, session_n, chosen, reason)
    return chosen, reason


def _fallback_choice(state: dict, available: list[dict]) -> str:
    """Sans LLM : exclut le dernier type, prend la compétence la moins représentée."""
    if not available:
        return "dialogue_ecoute"
    last = state.get("last_session_type")
    candidates = [t for t in available if t["code"] != last] or available
    dist = state.get("skill_distribution_7") or {}
    candidates.sort(key=lambda t: dist.get(t["skill"], 0))
    return candidates[0]["code"]


def _decide_theme(state: dict, profile: dict, phase: str) -> str:
    """Thème fédérateur de la séance. LLM en bonus, repli déterministe garanti."""
    language = profile.get("language", "")
    level = profile.get("level", "A1")
    if phase == "writing":
        return f"L'écriture — étape {state.get('session_n', 1)}"
    try:
        result = run_llm_sync(
            lambda ok, err: plan_lesson_async(state, level, language, phase, ok, err),
        )
        if isinstance(result, dict) and result.get("theme"):
            return result["theme"]
    except Exception as exc:
        logger.info("Plan de séance : LLM indisponible (%s), thème déterministe", exc)
    idx = (int(state.get("session_n", 1)) - 1) % len(_FALLBACK_THEMES)
    return _FALLBACK_THEMES[idx]


def compute_difficulty_target(
    profile: dict, profile_id: int, previous_difficulty: int | None = None
) -> int:
    """Indice de difficulté continu 1-10, DÉTERMINISTE (pas un appel LLM).

    Dérivé de l'historique réel pour rendre la progression visible séance par séance
    (et pas seulement par paliers de phase/CEFR) :
      - richesse lexicale acquise (flashcards de la langue), plafonnée à +5 ;
      - performance récente (moyenne glissante 0-1), entre -5 et +5 ;
      - plancher de phase (garde-fou bas/haut).
    Garde-fou anti yo-yo : jamais plus de ±1 par rapport à la séance précédente —
    progression Assimil = continue, pas en dents de scie.
    """
    vocab_size = get_flashcard_count(profile_id, profile.get("language", ""))
    vocab_score = min(vocab_size / 20, 5)
    recent_avg_score = get_recent_lesson_score_avg(profile_id, window=5)
    perf_score = (recent_avg_score - 0.5) * 10  # entre -5 et +5
    phase_floor = {"writing": 1, "passive": 2, "active": 5}.get(profile.get("phase", "passive"), 1)

    raw = phase_floor + vocab_score + perf_score
    target = max(1, min(10, round(raw)))
    if previous_difficulty is not None:
        target = max(previous_difficulty - 1, min(previous_difficulty + 1, target))
    return target


def plan_lesson(profile: dict) -> dict:
    """Construit le plan d'une séance : thème + difficulté + 10 slots (arc 4 temps).

    Déterministe d'abord (jamais bloquant) ; le LLM n'ajoute que le thème. Chaque slot
    porte son rôle (temps), le type concret choisi et le render_kind associé. L'indice
    de difficulté est calculé UNE fois par séance (densité homogène) et propagé au LLM.
    """
    # Import local : évite le cycle services.lang ↔ services.lang_sequencer (résolu
    # à l'appel, les deux modules étant alors complètement chargés).
    from services.lang import script_is_continuous

    state = build_sequencer_state(profile)
    phase = state["phase"]
    available = get_session_types_for_phase(phase)
    by_code = {t["code"]: t for t in available}
    valid = set(by_code)
    weak = state.get("weak_points") or []

    # Introduction CONTINUE des caractères (scripts logographiques : hanzi, kanji).
    # Même après la phase d'écriture, on réserve UN slot d'exposition à un lot de
    # caractères neufs chaque séance (alternance découverte/lecture). On expose juste
    # la meta du type forcé pour le lookup render_kind/skill — sans polluer le pool
    # des autres slots. Sans effet pour les alphabets finis ni la DB.
    continuous_chars = script_is_continuous(profile.get("language", "")) and phase != "writing"
    char_slot_type: str | None = None
    char_slot_index = 1  # premier slot d'exposition de l'arc
    if continuous_chars:
        writing_types = {t["code"]: t for t in get_session_types_for_phase("writing")}
        lesson_n = int(state.get("session_n") or 0)
        candidate = "ecriture_lecture" if lesson_n % 2 == 0 else "ecriture_decouverte"
        if candidate in writing_types:
            char_slot_type = candidate
            by_code.setdefault(candidate, writing_types[candidate])
        else:
            continuous_chars = False
    # Pont SR → séance : l'ancrage et la clôture font de la révision dès qu'il y a
    # de la matière à réviser — soit des erreurs passées, soit des cartes SR dues.
    # Trois branches (cf. plan1, Axe 1) : erreurs → révision ; sinon cartes dues →
    # révision ; sinon contenu neuf. La SOURCE concrète (erreurs vs cartes) est
    # résolue à la génération du contenu (services/lang).
    has_revision_material = bool(weak) or int(state.get("due_count", 0) or 0) > 0
    # Copie mutable de la répartition : on l'incrémente au fil des slots pour
    # rééquilibrer la suite de la séance (pas seulement l'historique des 7 dernières).
    dist = dict(state.get("skill_distribution_7") or {})

    theme = _decide_theme(state, profile, phase)
    previous_difficulty = get_last_completed_lesson_difficulty(profile["id"])
    difficulty = compute_difficulty_target(profile, profile["id"], previous_difficulty)

    slots: list[dict] = []
    last_type: str | None = None
    for i, temps in enumerate(ARC_TEMPLATE):
        # Slot « nouveaux caractères » réservé (scripts logographiques) : on force un
        # type d'écriture pour garantir l'exposition continue aux caractères.
        if continuous_chars and i == char_slot_index and char_slot_type:
            chosen = char_slot_type
            last_type = chosen
            skill = by_code.get(chosen, {}).get("skill", "")
            dist[skill] = dist.get(skill, 0) + 1
            slots.append({
                "slot_index": i,
                "temps": temps,
                "exercise_type": chosen,
                "render_kind": SESSION_TYPE_RENDER_KIND.get(
                    chosen, by_code.get(chosen, {}).get("render_kind", "writing")
                ),
                "label": SESSION_TYPE_LABEL.get(chosen, chosen),
            })
            continue
        candidates = [c for c in TEMPS_AFFINITY.get(temps, []) if c in valid] or list(valid)
        # Sans matière à réviser (ni erreur ni carte due), la révision n'a rien à
        # faire : on l'écarte → repli sur du contenu neuf.
        if not has_revision_material:
            candidates = [c for c in candidates if c != "revision_adaptative"] or candidates
        # Ancrage / clôture : privilégier la révision dès qu'il y a de la matière.
        if temps in ("ancrage", "cloture") and has_revision_material and "revision_adaptative" in valid:
            chosen = "revision_adaptative"
        else:
            pool = [c for c in candidates if c != last_type] or candidates
            pool.sort(key=lambda c: dist.get(by_code.get(c, {}).get("skill", ""), 0))
            chosen = pool[0] if pool else "dialogue_ecoute"
        last_type = chosen
        skill = by_code.get(chosen, {}).get("skill", "")
        dist[skill] = dist.get(skill, 0) + 1
        slots.append({
            "slot_index": i,
            "temps": temps,
            "exercise_type": chosen,
            "render_kind": SESSION_TYPE_RENDER_KIND.get(
                chosen, by_code.get(chosen, {}).get("render_kind", "dialogue")
            ),
            "label": SESSION_TYPE_LABEL.get(chosen, chosen),
        })

    return {
        "theme": theme,
        "level": profile.get("level", "A1"),
        "phase": phase,
        "difficulty_target": difficulty,
        "slots": slots,
    }
