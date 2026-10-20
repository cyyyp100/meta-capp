# db/page_dwell.py — Persistance du temps passé et des visites par page
from __future__ import annotations

import logging

from db import get_connection
from db.user import DEFAULT_USER_ID

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


def reading_dwell_samples(
    *,
    min_dwell_s: float,
    limit: int,
    document_id: int | None = None,
    code: bool | None = None,
    user_id: int = DEFAULT_USER_ID,
) -> list[float]:
    """Temps passés sur des pages LUES, des plus récents aux plus anciens.

    Une ligne par (séance, page) d'au moins `min_dwell_s`, dans les seules
    séances qui ont lu quelque chose (`pages_read > 0`) : avant la garde du sas
    (routers/reading.py), quitter depuis le sas y écrivait la mise en condition
    comme une lecture de la page 1. `document_id` borne à un document, `code` à
    une nature (fichier de code ou PDF) ; ni l'un ni l'autre, tout le monde."""
    clauses = ["rs.user_id = ?", "rs.pages_read > 0", "pd.dwell_s >= ?"]
    params: list = [int(user_id), float(min_dwell_s)]
    if document_id is not None:
        clauses.append("rs.document_id = ?")
        params.append(int(document_id))
    if code is not None:
        clauses.append("COALESCE(d.extraction_engine, '') " + ("= 'code'" if code else "<> 'code'"))
    params.append(max(0, int(limit)))
    rows = get_connection().execute(
        f"""SELECT pd.dwell_s
            FROM page_dwell pd
            JOIN reading_sessions rs ON rs.id = pd.session_id
            JOIN documents d ON d.id = rs.document_id
            WHERE {' AND '.join(clauses)}
            ORDER BY rs.started_at DESC, rs.id DESC, pd.page
            LIMIT ?""",
        params,
    ).fetchall()
    return [float(row["dwell_s"]) for row in rows]
