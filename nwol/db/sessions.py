# db/sessions.py — CRUD sessions de lecture
from __future__ import annotations

import json
import logging
from datetime import datetime

from db import get_connection
from db.user import DEFAULT_USER_ID, ensure_default_user

logger = logging.getLogger("DB.sessions")


def start_session(
    document_id: int,
    user_id: int = DEFAULT_USER_ID,
    chapters_completed: list | None = None,
) -> int:
    ensure_default_user()
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO reading_sessions
               (document_id, user_id, chapters_completed)
               VALUES (?, ?, ?)""",
            (
                document_id,
                user_id,
                json.dumps(chapters_completed or [], ensure_ascii=False),
            ),
        )
    logger.info("Session lecture démarrée id=%s doc=%s", cur.lastrowid, document_id)
    return int(cur.lastrowid)


def end_session(
    session_id: int,
    pages_read: int | None = None,
    duration_s: int | None = None,
    chapters_completed: list | None = None,
) -> None:
    session = get_session(session_id)
    if session is None:
        raise ValueError(f"Session introuvable: {session_id}")

    if duration_s is None:
        duration_s = _duration_from_started_at(session.get("started_at"))

    updates = ["ended_at=?", "duration_s=?"]
    params: list = [datetime.now().isoformat(), duration_s]

    if pages_read is not None:
        updates.append("pages_read=?")
        params.append(pages_read)
    if chapters_completed is not None:
        updates.append("chapters_completed=?")
        params.append(json.dumps(chapters_completed, ensure_ascii=False))

    params.append(session_id)
    conn = get_connection()
    with conn:
        conn.execute(
            f"UPDATE reading_sessions SET {', '.join(updates)} WHERE id=?",
            params,
        )
    logger.info("Session lecture terminée id=%s durée=%ss", session_id, duration_s)


def update_session_progress(
    session_id: int,
    pages_read: int | None = None,
    chapters_completed: list | None = None,
) -> None:
    updates = []
    params: list = []
    if pages_read is not None:
        updates.append("pages_read=?")
        params.append(pages_read)
    if chapters_completed is not None:
        updates.append("chapters_completed=?")
        params.append(json.dumps(chapters_completed, ensure_ascii=False))
    if not updates:
        return

    params.append(session_id)
    conn = get_connection()
    with conn:
        conn.execute(
            f"UPDATE reading_sessions SET {', '.join(updates)} WHERE id=?",
            params,
        )


def get_session(session_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM reading_sessions WHERE id=?", (session_id,)).fetchone()
    return _decode_session(row) if row else None


def get_open_session(user_id: int = DEFAULT_USER_ID) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        """SELECT * FROM reading_sessions
           WHERE user_id=? AND ended_at IS NULL
           ORDER BY started_at DESC, id DESC
           LIMIT 1""",
        (user_id,),
    ).fetchone()
    return _decode_session(row) if row else None


def list_sessions(user_id: int = DEFAULT_USER_ID, limit: int = 20) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM reading_sessions
           WHERE user_id=?
           ORDER BY started_at DESC, id DESC
           LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    return [_decode_session(row) for row in rows]


def _decode_session(row) -> dict:
    item = dict(row)
    try:
        item["chapters_completed"] = json.loads(item.get("chapters_completed") or "[]")
    except json.JSONDecodeError:
        item["chapters_completed"] = []
    return item


def _duration_from_started_at(started_at: str | None) -> int:
    if not started_at:
        return 0
    try:
        started = datetime.fromisoformat(started_at)
        return max(0, int((datetime.now() - started).total_seconds()))
    except ValueError:
        return 0
