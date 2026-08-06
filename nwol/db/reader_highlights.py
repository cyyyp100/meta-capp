# db/reader_highlights.py — Surlignages persistants du lecteur web.
#
# Le texte surligné par l'étudiant est mémorisé en base (table reader_highlights,
# schéma v20) : il réapparaît à la réouverture du PDF et sert à enrichir le
# contexte transmis au LLM (passages qui « tiennent à cœur » à l'étudiant).
# Module distinct du module Tk reader/highlights.py (localisation éphémère).
from __future__ import annotations

import json
import logging

from db import get_connection
from db.user import DEFAULT_USER_ID, ensure_default_user

logger = logging.getLogger("DB.reader_highlights")

_VALID_COLORS = ("key", "explain", "reference")


def add_highlight(
    document_id: int,
    page: int,
    quote: str,
    rects: list[list[float]],
    color: str = "key",
    user_id: int = DEFAULT_USER_ID,
    anchor: dict | None = None,
) -> int:
    """Mémorise un surlignage ; renvoie son id.

    `anchor` (v25, lecteur reconstruit) : {block_id, start, end} — ancrage TEXTE
    dans les blocs OCR ; `rects` reste la référence des documents raster."""
    ensure_default_user()
    clean_color = color if color in _VALID_COLORS else "key"
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO reader_highlights
               (user_id, document_id, page, quote, rects_json, color, anchor_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id or DEFAULT_USER_ID,
                int(document_id),
                int(page),
                (quote or "").strip(),
                json.dumps(rects or [], ensure_ascii=False),
                clean_color,
                json.dumps(anchor, ensure_ascii=False) if anchor else None,
            ),
        )
    logger.info("Surlignage créé id=%s doc=%s page=%s", cur.lastrowid, document_id, page)
    return int(cur.lastrowid)


def list_highlights(document_id: int, user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Tous les surlignages d'un document, ordonnés par page puis création."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM reader_highlights
           WHERE user_id=? AND document_id=?
           ORDER BY page ASC, id ASC""",
        (user_id, int(document_id)),
    ).fetchall()
    return [_decode(row) for row in rows]


def delete_highlight(highlight_id: int, user_id: int = DEFAULT_USER_ID) -> int:
    """Supprime un surlignage (filtré par utilisateur). Renvoie le nb supprimé."""
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "DELETE FROM reader_highlights WHERE id=? AND user_id=?",
            (int(highlight_id), user_id),
        )
    return int(cur.rowcount or 0)


def get_highlight_quotes(
    document_id: int,
    page: int | None = None,
    limit: int = 5,
    user_id: int = DEFAULT_USER_ID,
) -> list[str]:
    """Citations surlignées pour enrichir le contexte LLM.

    Si `page` est fourni, priorise la page courante puis ses voisines ; sinon
    renvoie les surlignages les plus récents du document.
    """
    conn = get_connection()
    if page is None:
        rows = conn.execute(
            """SELECT quote FROM reader_highlights
               WHERE user_id=? AND document_id=?
               ORDER BY id DESC LIMIT ?""",
            (user_id, int(document_id), int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT quote FROM reader_highlights
               WHERE user_id=? AND document_id=?
               ORDER BY ABS(page - ?) ASC, id DESC LIMIT ?""",
            (user_id, int(document_id), int(page), int(limit)),
        ).fetchall()
    quotes: list[str] = []
    for row in rows:
        quote = (row["quote"] or "").strip()
        if quote:
            quotes.append(quote)
    return quotes


def _decode(row) -> dict:
    item = dict(row)
    try:
        item["rects"] = json.loads(item.get("rects_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        item["rects"] = []
    anchor_raw = item.get("anchor_json")
    try:
        item["anchor"] = json.loads(anchor_raw) if anchor_raw else None
    except (json.JSONDecodeError, TypeError):
        item["anchor"] = None
    return item
