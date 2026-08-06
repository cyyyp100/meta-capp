# db/subjects.py — CRUD niveaux de maîtrise par matière
from __future__ import annotations

import logging
from datetime import datetime

from db import get_connection

logger = logging.getLogger("DB.subjects")

SUBJECT_REALTIME_UPDATE_WEIGHT = 0.08

SUBJECT_LABELS: dict[str, str] = {
    "mathématiques": "Mathématiques",
    "physique": "Physique",
    "chimie": "Chimie",
    "biologie": "Biologie",
    "sciences": "Sciences",
    "informatique": "Informatique",
    "technologie": "Technologie",
    "histoire": "Histoire",
    "géographie": "Géographie",
    "français": "Français",
    "philosophie": "Philosophie",
    "littérature": "Littérature",
    "langues": "Langues",
    "économie": "Économie",
    "sciences-sociales": "Sciences sociales",
    "droit": "Droit",
    "gestion": "Gestion",
    "psychologie": "Psychologie",
    "sociologie": "Sociologie",
    "arts": "Arts",
    "musique": "Musique",
    "médecine": "Médecine",
    "sport": "Sport",
    "religion": "Religion",
    "culture": "Culture générale",
}


def ensure_subject(user_id: int, subject: str) -> dict:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO subject_profile
               (user_id, subject, level, questions_count, correct_count)
               VALUES (?, ?, 50.0, 0, 0)""",
            (user_id, subject),
        )
    return get_subject(user_id, subject)  # type: ignore[return-value]


def get_subject(user_id: int, subject: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM subject_profile WHERE user_id=? AND subject=?",
        (user_id, subject),
    ).fetchone()
    return dict(row) if row else None


def get_all_subjects(user_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM subject_profile WHERE user_id=? ORDER BY subject",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_subject_from_answer(
    user_id: int,
    subject: str,
    correct: bool,
    session_id: int | None = None,
) -> float:
    ensure_subject(user_id, subject)
    row = get_subject(user_id, subject)
    assert row is not None
    old_level = float(row["level"])
    questions = int(row["questions_count"]) + 1
    corrects = int(row["correct_count"]) + (1 if correct else 0)

    # EMA pondérée : alpha décroît avec le nombre de questions (stabilisation)
    alpha = max(0.08, 1.0 / questions)
    signal = 100.0 if correct else 0.0
    new_level = max(0.0, min(100.0, old_level * (1.0 - alpha) + signal * alpha))

    conn = get_connection()
    with conn:
        conn.execute(
            """UPDATE subject_profile
               SET level=?, questions_count=?, correct_count=?, updated_at=?
               WHERE user_id=? AND subject=?""",
            (new_level, questions, corrects, datetime.now().isoformat(), user_id, subject),
        )
        _insert_subject_history(conn, user_id, subject, old_level, new_level, session_id, "quiz")
    logger.info(
        "Niveau matière mis à jour : user=%s subject=%s level=%.1f",
        user_id, subject, new_level,
    )
    return new_level


def update_subject_from_evaluation(
    user_id: int,
    subject: str,
    evaluation: dict,
    current_level: float | None = None,
    alpha: float = SUBJECT_REALTIME_UPDATE_WEIGHT,
    session_id: int | None = None,
) -> float:
    """Update subject mastery from an inline course answer."""
    ensure_subject(user_id, subject)
    row = get_subject(user_id, subject)
    assert row is not None

    old_level = _clamp(current_level if current_level is not None else float(row["level"]))
    questions = int(row["questions_count"]) + 1
    corrects = int(row["correct_count"]) + (1 if evaluation.get("verdict") == "correct" else 0)
    weight = max(0.0, min(1.0, float(alpha)))
    target = _subject_score_from_evaluation(evaluation)
    new_level = _clamp(old_level * (1.0 - weight) + target * weight)

    conn = get_connection()
    with conn:
        conn.execute(
            """UPDATE subject_profile
               SET level=?, questions_count=?, correct_count=?, updated_at=?
               WHERE user_id=? AND subject=?""",
            (new_level, questions, corrects, datetime.now().isoformat(), user_id, subject),
        )
        _insert_subject_history(conn, user_id, subject, old_level, new_level, session_id, "inline")
    logger.info(
        "Niveau matière (temps réel) : user=%s subject=%s level=%.1f",
        user_id, subject, new_level,
    )
    return new_level


def update_subject_from_session(
    user_id: int,
    subject: str,
    session_score: float,
    session_id: int | None = None,
) -> float:
    """Update subject level after a reading session using a gentle EMA (alpha=0.05)."""
    ensure_subject(user_id, subject)
    row = get_subject(user_id, subject)
    assert row is not None
    old_level = float(row["level"])
    alpha = 0.05
    new_level = max(0.0, min(100.0, old_level * (1.0 - alpha) + session_score * alpha))
    conn = get_connection()
    with conn:
        conn.execute(
            """UPDATE subject_profile
               SET level=?, updated_at=?
               WHERE user_id=? AND subject=?""",
            (new_level, datetime.now().isoformat(), user_id, subject),
        )
        _insert_subject_history(conn, user_id, subject, old_level, new_level, session_id, "session")
    logger.info(
        "Niveau matière (lecture) : user=%s subject=%s level=%.1f",
        user_id, subject, new_level,
    )
    return new_level


def get_subject_history(
    user_id: int,
    subject: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    params: list = [user_id]
    query = "SELECT * FROM subject_history WHERE user_id=?"
    if subject:
        query += " AND subject=?"
        params.append(subject)
    query += " ORDER BY recorded_at, id"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_subject_history_by_subject(user_id: int) -> dict[str, list[tuple[int | None, float, str]]]:
    grouped: dict[str, list[tuple[int | None, float, str]]] = {}
    for row in get_subject_history(user_id):
        subject = row.get("subject")
        if not subject:
            continue
        grouped.setdefault(subject, []).append((
            row.get("session_id"),
            float(row.get("value_after", 50.0)),
            row.get("recorded_at") or "",
        ))

    for subject_row in get_all_subjects(user_id):
        subject = subject_row.get("subject")
        if not subject or subject in grouped:
            continue
        grouped[subject] = [(
            None,
            float(subject_row.get("level", 50.0)),
            subject_row.get("updated_at") or "",
        )]

    return dict(sorted(grouped.items()))


def _subject_score_from_evaluation(evaluation: dict) -> float:
    verdict_scores = {
        "correct": 100.0,
        "partial": 55.0,
        "incorrect": 0.0,
    }
    verdict_score = verdict_scores.get(evaluation.get("verdict"), 50.0)
    signals = evaluation.get("metacog_signals") or {}
    if not isinstance(signals, dict):
        signals = {}

    signal_values: list[float] = []
    for key in ("context_comprehension", "retention"):
        try:
            signal = float(signals.get(key, 0.0))
        except (TypeError, ValueError):
            signal = 0.0
        signal_values.append(50.0 + max(-2.0, min(2.0, signal)) * 25.0)

    signal_score = sum(signal_values) / len(signal_values) if signal_values else 50.0
    return _clamp(verdict_score * 0.75 + signal_score * 0.25)


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _insert_subject_history(
    conn,
    user_id: int,
    subject: str,
    value_before: float,
    value_after: float,
    session_id: int | None,
    source: str,
) -> None:
    conn.execute(
        """INSERT INTO subject_history
           (user_id, session_id, subject, value_before, value_after, source)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            session_id,
            subject,
            _clamp(value_before),
            _clamp(value_after),
            source,
        ),
    )
