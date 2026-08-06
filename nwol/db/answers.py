# db/answers.py — CRUD réponses utilisateur
from __future__ import annotations

import json
import logging

from db import get_connection
from db.user import DEFAULT_USER_ID, ensure_default_user

logger = logging.getLogger("DB.answers")


def save_answer(
    question_id: int | None,
    user_id: int,
    answer_text: str,
    verdict: str | None = None,
    feedback: str | None = None,
    completion: str | None = None,
    hint: str | None = None,
    response_time_ms: int | None = None,
    metacog_signals: dict | None = None,
    attempt_number: int = 1,
    session_id: int | None = None,
) -> int:
    ensure_default_user()
    text = answer_text.strip()
    length_chars = len(text)
    length_words = len(text.split())
    signals_json = json.dumps(metacog_signals or {}, ensure_ascii=False)

    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO answers
               (question_id, user_id, session_id, answer_text, verdict, feedback,
                completion, hint, response_time_ms, length_chars, length_words,
                metacog_signals, attempt_number)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                question_id,
                user_id or DEFAULT_USER_ID,
                session_id,
                text,
                verdict,
                feedback,
                completion,
                hint,
                response_time_ms,
                length_chars,
                length_words,
                signals_json,
                attempt_number,
            ),
        )
    logger.info("Réponse sauvegardée id=%s question=%s verdict=%s", cur.lastrowid, question_id, verdict)
    return int(cur.lastrowid)


def get_answer(answer_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM answers WHERE id=?", (answer_id,)).fetchone()
    return _decode_answer(row) if row else None


def get_answers_for_session(session_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM answers WHERE session_id=? ORDER BY answered_at, id",
        (session_id,),
    ).fetchall()
    return [_decode_answer(row) for row in rows]


def get_answers_for_question(question_id: int, user_id: int | None = None) -> list[dict]:
    conn = get_connection()
    if user_id is None:
        rows = conn.execute(
            "SELECT * FROM answers WHERE question_id=? ORDER BY attempt_number, id",
            (question_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM answers
               WHERE question_id=? AND user_id=?
               ORDER BY attempt_number, id""",
            (question_id, user_id),
        ).fetchall()
    return [_decode_answer(row) for row in rows]


def get_recent_session_answers(session_id: int, limit: int = 5) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM answers
           WHERE session_id=?
           ORDER BY answered_at DESC, id DESC
           LIMIT ?""",
        (session_id, limit),
    ).fetchall()
    return list(reversed([_decode_answer(row) for row in rows]))


def get_recurring_struggles(
    user_id: int = DEFAULT_USER_ID,
    doc_id: int | None = None,
    limit: int = 3,
) -> list[dict]:
    """Notions sur lesquelles l'utilisateur bute de façon répétée (cross-session).

    Une difficulté = une question avec au moins 2 tentatives ratées/partielles
    et plus d'échecs que de réussites. Les plus récentes d'abord.
    """
    clauses = ["a.user_id = ?", "a.verdict IS NOT NULL"]
    params: list = [user_id]
    if doc_id is not None:
        clauses.append("q.document_id = ?")
        params.append(doc_id)
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT q.id AS question_id,
                   q.question AS question,
                   q.question_type AS question_type,
                   q.document_id AS document_id,
                   c.title AS chapter_title,
                   SUM(CASE WHEN a.verdict IN ('incorrect', 'partial') THEN 1 ELSE 0 END) AS fail_count,
                   SUM(CASE WHEN a.verdict = 'correct' THEN 1 ELSE 0 END) AS success_count,
                   MAX(a.answered_at) AS last_answered_at
            FROM answers a
            JOIN questions q ON q.id = a.question_id
            LEFT JOIN chapters c ON c.id = q.chapter_id
            WHERE {' AND '.join(clauses)}
            GROUP BY q.id
            HAVING fail_count >= 2 AND fail_count > success_count
            ORDER BY last_answered_at DESC
            LIMIT ?""",
        (*params, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _decode_answer(row) -> dict:
    item = dict(row)
    try:
        item["metacog_signals"] = json.loads(item.get("metacog_signals") or "{}")
    except json.JSONDecodeError:
        item["metacog_signals"] = {}
    return item
