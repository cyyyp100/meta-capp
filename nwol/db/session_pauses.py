# db/session_pauses.py — Persistance des pauses prises pendant une lecture
from __future__ import annotations

import logging

from db import get_connection

logger = logging.getLogger("DB.session_pauses")

_COLUMNS = (
    "started_at", "page", "duration_s", "planned_s", "source",
    "after_recommendation", "recommendation_kind", "recommendation_delay_s",
    "attention_at_start", "ended_by",
)


def save_pause(session_id: int, pause: dict) -> None:
    """Enregistre une pause terminée (une ligne par pause).

    `pause` est le dict de `services.pause.PauseRecord.as_row()` ; les clés
    absentes valent NULL."""
    if not session_id:
        return
    values = [pause.get(col) for col in _COLUMNS]
    values[_COLUMNS.index("after_recommendation")] = int(bool(pause.get("after_recommendation")))
    conn = get_connection()
    with conn:
        conn.execute(
            f"INSERT INTO session_pauses (session_id, {', '.join(_COLUMNS)}) "
            f"VALUES (?, {', '.join('?' for _ in _COLUMNS)})",
            (int(session_id), *values),
        )
    logger.info(
        "Pause persistée : session=%s durée=%.0fs source=%s",
        session_id, float(pause.get("duration_s") or 0.0), pause.get("source"),
    )


def get_session_pauses(session_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM session_pauses WHERE session_id=? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [
        {**dict(row), "after_recommendation": bool(row["after_recommendation"])}
        for row in rows
    ]
