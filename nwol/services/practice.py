# services/practice.py — Séances de pratique (quiz, langues) : une séance, sa courbe.
#
# Une lecture a un canal temps réel (le WebSocket du lecteur) qui fait bouger ses
# jauges pendant qu'elle a lieu. Un quiz et une séance de langue n'en ont pas, et
# n'en ont pas besoin : leurs jauges ne s'affichent jamais pendant la séance (même
# règle que la lecture), elles servent à la finalisation et à « Ma progression ».
# Leurs mesures sont donc enregistrées là où elles vivent — réponses du quiz,
# tables `lang_*` — puis REJOUÉES à la clôture par le moteur unique
# (`metacog.gauges.replay`) en une courbe figée, et le profil glisse vers elle
# par la finalisation commune (`services.session.nudge_metacog_profile`).
#
# Ce module ne sait rien d'un quiz ni d'une langue : il ouvre une séance, fige
# son amorce, rejoue des mesures et clôt. Ce qu'est une mesure, chaque activité
# le dit (`services.quiz`, `services.lang_runs`, `services.lang`).
from __future__ import annotations

import logging

from db.metacog import ensure_profile
from db.practice_sessions import (
    create_practice_session,
    end_practice_session,
    find_practice_session,
    get_practice_session,
    update_practice_details,
)
from db.session_gauges import PRACTICE, replace_gauges
from db.user import DEFAULT_USER_ID
from metacog.gauges import informed_counts, initialize_session_gauges, replay

logger = logging.getLogger("services.practice")

__all__ = ["start", "start_for_lang", "record", "close"]


def start(
    kind: str,
    user_id: int = DEFAULT_USER_ID,
    *,
    settings: dict | None = None,
    lang_run_id: int | None = None,
    lang_lesson_id: int | None = None,
    started_at: str | None = None,
) -> int:
    """Ouvre une séance de pratique et fige son AMORCE : profil × 0,8.

    Même départ qu'une lecture, et pour la même raison : c'est le repère qui
    distingue une jauge exercée d'une jauge restée intacte (`_measured_gauges`)."""
    try:
        profile = ensure_profile(user_id)
    except Exception:  # un profil illisible ne bloque pas la séance
        profile = {}
    return create_practice_session(
        kind,
        user_id,
        seed=initialize_session_gauges(profile),
        settings=settings,
        lang_run_id=lang_run_id,
        lang_lesson_id=lang_lesson_id,
        started_at=started_at,
    )


def start_for_lang(
    user_id: int = DEFAULT_USER_ID,
    *,
    lang_run_id: int | None = None,
    lang_lesson_id: int | None = None,
    settings: dict | None = None,
    started_at: str | None = None,
) -> int:
    """La séance de pratique d'une séance de langue — créée une fois, retrouvée ensuite."""
    existing = find_practice_session(lang_run_id=lang_run_id, lang_lesson_id=lang_lesson_id)
    if existing is not None:
        return int(existing["id"])
    return start(
        "lang", user_id, settings=settings,
        lang_run_id=lang_run_id, lang_lesson_id=lang_lesson_id, started_at=started_at,
    )


def record(session_id: int, measures: list[dict]) -> int:
    """Rejoue les mesures en une courbe de jauges et la persiste (en remplacement).

    Garde aussi, critère par critère, combien de mesures l'ont informé
    (`details.measured_by`) : la finalisation pondère chaque critère par SA
    quantité de mesure. Renvoie le nombre de mesures réellement appliquées."""
    session = get_practice_session(session_id)
    if session is None:
        raise ValueError(f"Séance de pratique introuvable : {session_id}")
    seed = session.get("seed") or {}
    points = replay(seed, measures)
    replace_gauges(session_id, points, scope=PRACTICE)
    update_practice_details(session_id, details={"measured_by": informed_counts(seed, measures)})
    return len(points) - 1


def close(session_id: int, measures: list[dict], duration_s: int | None = None) -> int:
    """Rejoue puis clôt la séance (`ended_at`, durée). Renvoie le nombre de mesures."""
    applied = record(session_id, measures)
    end_practice_session(session_id, duration_s)
    return applied
