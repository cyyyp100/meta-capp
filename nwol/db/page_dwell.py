# db/page_dwell.py — Persistance du temps passé et des visites par page
from __future__ import annotations

import logging

from db import get_connection

logger = logging.getLogger("DB.page_dwell")


def save_page_dwell(
    session_id: int,
    dwell_by_page: dict[int, float],
    visits_by_page: dict[int, int],
) -> None:
    """Persiste le dwell/visites d'une session de lecture (une ligne par page vue)."""
    if not session_id or not dwell_by_page:
        return
    rows = [
        (session_id, int(page), float(dwell or 0.0), int(visits_by_page.get(page, 0)))
        for page, dwell in sorted(dwell_by_page.items())
    ]
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM page_dwell WHERE session_id=?", (session_id,))
        conn.executemany(
            "INSERT INTO page_dwell (session_id, page, dwell_s, visits) VALUES (?, ?, ?, ?)",
            rows,
        )
    logger.info("Dwell persisté : session=%s pages=%d", session_id, len(rows))


def get_page_dwell(session_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT page, dwell_s, visits FROM page_dwell WHERE session_id=? ORDER BY page",
        (session_id,),
    ).fetchall()
    return [dict(row) for row in rows]
