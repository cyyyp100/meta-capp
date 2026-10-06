# db/session_gauges.py — Persistance des jauges temps réel
#
# Deux familles de séances, une table de jauges chacune, la même forme et les
# mêmes lectures : la lecture (`session_gauges` → `reading_sessions`) et la
# pratique, quiz et langues (`practice_session_gauges` → `practice_sessions`).
# `scope` choisit la table ; la logique (amorce, dernière valeur) reste unique.
from __future__ import annotations

import logging
from time import time

from db import get_connection

logger = logging.getLogger("DB.session_gauges")

READING = "reading"
PRACTICE = "practice"
_TABLES = {READING: "session_gauges", PRACTICE: "practice_session_gauges"}


def _table(scope: str) -> str:
    try:
        return _TABLES[scope]
    except KeyError:
        raise ValueError(f"Famille de séance inconnue : {scope!r}") from None


def record_gauge(
    session_id: int, gauge_name: str, value: float, t: float | None = None, *, scope: str = READING,
) -> int:
    timestamp = time() if t is None else t
    conn = get_connection()
    with conn:
        cur = conn.execute(
            f"""INSERT INTO {_table(scope)} (session_id, t, gauge_name, value)
                VALUES (?, ?, ?, ?)""",
            (session_id, float(timestamp), gauge_name, float(value)),
        )
    return int(cur.lastrowid)


def record_gauges(
    session_id: int, values: dict[str, float], t: float | None = None, *, scope: str = READING,
) -> None:
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
            f"""INSERT INTO {_table(scope)} (session_id, t, gauge_name, value)
                VALUES (?, ?, ?, ?)""",
            rows,
        )
    logger.debug("Jauges sauvegardées session=%s count=%s", session_id, len(rows))


def replace_gauges(
    session_id: int, points: list[tuple[float, dict[str, float]]], *, scope: str = PRACTICE,
) -> None:
    """Remplace TOUTE la courbe d'une séance, en une transaction.

    Une séance de pratique ne s'écrit pas au fil de l'eau : sa courbe est rejouée
    depuis ses mesures (`metacog.gauges.replay`). Rejouer deux fois les mêmes
    mesures doit donner la même courbe, pas la doubler."""
    rows = [
        (session_id, float(t), name, float(value))
        for t, values in points
        for name, value in values.items()
    ]
    table = _table(scope)
    conn = get_connection()
    with conn:
        conn.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))
        if rows:
            conn.executemany(
                f"INSERT INTO {table} (session_id, t, gauge_name, value) VALUES (?, ?, ?, ?)",
                rows,
            )


def get_session_gauges(
    session_id: int, gauge_name: str | None = None, *, scope: str = READING,
) -> list[dict]:
    table = _table(scope)
    conn = get_connection()
    if gauge_name:
        rows = conn.execute(
            f"""SELECT * FROM {table}
                WHERE session_id=? AND gauge_name=?
                ORDER BY t, id""",
            (session_id, gauge_name),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE session_id=? ORDER BY t, id",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_latest_gauges(session_id: int, *, scope: str = READING) -> dict[str, float]:
    rows = get_session_gauges(session_id, scope=scope)
    latest: dict[str, float] = {}
    for row in rows:
        latest[row["gauge_name"]] = float(row["value"])
    return latest


def get_first_gauges(session_id: int, *, scope: str = READING) -> dict[str, float]:
    """Première valeur enregistrée par jauge — l'AMORCE de la session.

    Sert à distinguer une jauge mesurée d'une jauge restée à son amorce
    (profil × 0,8) : sans ce repère, une jauge jamais exercée tirait le profil
    vers le bas de 20 % à chaque session, par pure construction."""
    first: dict[str, float] = {}
    for row in get_session_gauges(session_id, scope=scope):  # déjà trié par t, id
        first.setdefault(row["gauge_name"], float(row["value"]))
    return first
