# db/metacog.py — CRUD profil métacognitif
from __future__ import annotations

import logging
from datetime import datetime

from db import get_connection
from db.user import DEFAULT_USER_ID, ensure_default_user

logger = logging.getLogger("DB.metacog")

CRITERIA = (
    "attention",
    "context_comprehension",
    "creativity",
    "retention",
    "curiosity",
    "meta_cognition",
)


def ensure_profile(user_id: int = DEFAULT_USER_ID) -> dict:
    ensure_default_user()
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO metacog_profile
               (user_id, attention, context_comprehension, creativity, retention, curiosity, meta_cognition)
               VALUES (?, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0)""",
            (user_id,),
        )
    profile = get_profile(user_id)
    if profile is None:
        raise RuntimeError(f"Profil métacognitif introuvable pour user={user_id}")
    return profile


def get_profile(user_id: int = DEFAULT_USER_ID) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM metacog_profile WHERE user_id=?",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def update_profile_values(
    user_id: int,
    values: dict[str, float],
    increment_sessions: bool = False,
) -> None:
    clean_values = {
        key: _clamp_score(value)
        for key, value in values.items()
        if key in CRITERIA
    }
    if not clean_values and not increment_sessions:
        return

    ensure_profile(user_id)
    assignments = [f"{key}=?" for key in clean_values]
    params: list = list(clean_values.values())
    if increment_sessions:
        assignments.append("sessions_count=sessions_count + 1")
    assignments.append("updated_at=?")
    params.append(datetime.now().isoformat())
    params.append(user_id)

    conn = get_connection()
    with conn:
        conn.execute(
            f"UPDATE metacog_profile SET {', '.join(assignments)} WHERE user_id=?",
            params,
        )
    logger.info("Profil métacognitif mis à jour user=%s", user_id)


def insert_history(
    user_id: int,
    session_id: int | None,
    criterion: str,
    value_before: float,
    value_after: float,
    session_score: float,
    alpha: float,
) -> int:
    if criterion not in CRITERIA:
        raise ValueError(f"Critère inconnu: {criterion}")

    ensure_profile(user_id)
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO metacog_history
               (user_id, session_id, criterion, value_before, value_after,
                session_score, alpha)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                session_id,
                criterion,
                float(value_before),
                float(value_after),
                float(session_score),
                float(alpha),
            ),
        )
    return int(cur.lastrowid)


def get_history(
    user_id: int = DEFAULT_USER_ID,
    criterion: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    params: list = [user_id]
    query = "SELECT * FROM metacog_history WHERE user_id=?"
    if criterion:
        query += " AND criterion=?"
        params.append(criterion)
    query += " ORDER BY recorded_at, id"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_history_by_criterion(user_id: int = DEFAULT_USER_ID) -> dict[str, list[tuple[int | None, float, str]]]:
    rows = get_history(user_id)
    grouped = {criterion: [] for criterion in CRITERIA}
    for row in rows:
        criterion = row.get("criterion")
        if criterion not in grouped:
            continue
        grouped[criterion].append((
            row.get("session_id"),
            float(row.get("value_after", 50.0)),
            row.get("recorded_at") or "",
        ))
    return grouped


def set_general_analysis(user_id: int, text: str) -> None:
    """Mémorise l'analyse générale de l'apprenant (texte LLM) affichée sur le profil."""
    ensure_profile(user_id)
    conn = get_connection()
    with conn:
        conn.execute(
            """UPDATE metacog_profile
               SET general_analysis=?, general_analysis_updated_at=?
               WHERE user_id=?""",
            (str(text or "").strip(), datetime.now().isoformat(), user_id),
        )
    logger.info("Analyse générale mise à jour user=%s (%d car.)", user_id, len(text or ""))


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, float(value)))
