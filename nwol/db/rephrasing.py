# db/rephrasing.py — CRUD reformulations
from __future__ import annotations

import logging

from db import get_connection

logger = logging.getLogger("DB.rephrasing")


def save_rephrasing(
    question_id: int | None,
    session_id: int | None,
    angle: str | None,
    rephrased_text: str,
    note: str | None = None,
) -> int:
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO rephrasing
               (question_id, session_id, angle, rephrased_text, note)
               VALUES (?, ?, ?, ?, ?)""",
            (question_id, session_id, angle, rephrased_text, note),
        )
    logger.info("Reformulation sauvegardée id=%s", cur.lastrowid)
    return int(cur.lastrowid)


def get_rephrasings_for_session(session_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM rephrasing WHERE session_id=? ORDER BY created_at, id",
        (session_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def count_rephrasings_for_session(session_id: int) -> int:
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM rephrasing WHERE session_id=?",
        (session_id,),
    ).fetchone()
    return int(row["n"]) if row else 0
