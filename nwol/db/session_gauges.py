# db/session_gauges.py — Persistance des jauges temps réel
from __future__ import annotations

import logging
from time import time

from db import get_connection

logger = logging.getLogger("DB.session_gauges")


def record_gauge(session_id: int, gauge_name: str, value: float, t: float | None = None) -> int:
    timestamp = time() if t is None else t
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO session_gauges (session_id, t, gauge_name, value)
               VALUES (?, ?, ?, ?)""",
            (session_id, float(timestamp), gauge_name, float(value)),
        )
    return int(cur.lastrowid)


def record_gauges(session_id: int, values: dict[str, float], t: float | None = None) -> None:
    timestamp = time() if t is None else t
    rows = [
        (session_id, float(timestamp), name, float(value))
        for name, value in values.items()
    ]
    if not rows:
        return

    conn = get_connection()
    with conn:
        conn.executemany(
            """INSERT INTO session_gauges (session_id, t, gauge_name, value)
               VALUES (?, ?, ?, ?)""",
            rows,
        )
    logger.debug("Jauges sauvegardées session=%s count=%s", session_id, len(rows))


def get_session_gauges(session_id: int, gauge_name: str | None = None) -> list[dict]:
    conn = get_connection()
    if gauge_name:
        rows = conn.execute(
            """SELECT * FROM session_gauges
               WHERE session_id=? AND gauge_name=?
               ORDER BY t, id""",
            (session_id, gauge_name),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM session_gauges WHERE session_id=? ORDER BY t, id",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_latest_gauges(session_id: int) -> dict[str, float]:
    rows = get_session_gauges(session_id)
    latest: dict[str, float] = {}
    for row in rows:
        latest[row["gauge_name"]] = float(row["value"])
    return latest
