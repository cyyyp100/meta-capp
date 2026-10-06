# db/session_reflections.py — Réponses métacognitives de fin de session
from __future__ import annotations

import logging

from db import get_connection
from db.user import DEFAULT_USER_ID, ensure_default_user

logger = logging.getLogger("DB.session_reflections")


def save_session_reflection(
    session_id: int | None,
    question_text: str,
    answer_text: str,
    user_id: int = DEFAULT_USER_ID,
    question_order: int = 0,
    practice_session_id: int | None = None,
) -> int | None:
    """Une réflexion, rattachée à une lecture (`session_id`) ou à une séance de
    pratique (`practice_session_id`). Sans aucune des deux, rien n'est écrit :
    une réflexion orpheline ne se relirait nulle part."""
    question = question_text.strip()
    answer = answer_text.strip()
    if not (session_id or practice_session_id) or not question or not answer:
        return None

    ensure_default_user()
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO session_reflections
               (session_id, practice_session_id, user_id, question_text, answer_text, question_order)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_id or None, practice_session_id or None, user_id or DEFAULT_USER_ID,
                question, answer, int(question_order),
            ),
        )
    logger.info(
        "Réponse métacognitive sauvegardée id=%s session=%s pratique=%s",
        cur.lastrowid, session_id, practice_session_id,
    )
    return int(cur.lastrowid)


def get_session_reflections(session_id: int, *, practice: bool = False) -> list[dict]:
    """Réflexions d'une lecture, ou d'une séance de pratique avec `practice=True`."""
    column = "practice_session_id" if practice else "session_id"
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT * FROM session_reflections
            WHERE {column}=?
            ORDER BY question_order, id""",
        (session_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_recent_reflection_questions(user_id: int = DEFAULT_USER_ID, limit: int = 12) -> list[str]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT question_text
           FROM session_reflections
           WHERE user_id=?
           ORDER BY created_at DESC, id DESC
           LIMIT ?""",
        (user_id or DEFAULT_USER_ID, int(limit)),
    ).fetchall()
    questions: list[str] = []
    seen: set[str] = set()
    for row in rows:
        question = (row["question_text"] or "").strip()
        key = question.lower()
        if question and key not in seen:
            questions.append(question)
            seen.add(key)
    return questions
