# db/reader_highlights.py — Surlignages persistants du lecteur web.
#
# Le texte surligné par l'étudiant est mémorisé en base (table reader_highlights,
# schéma v20) : il réapparaît à la réouverture du PDF et sert à enrichir le
# contexte transmis au LLM (passages qui « tiennent à cœur » à l'étudiant).
# Module distinct du module Tk reader/highlights.py (localisation éphémère).
#
# v45 : chaque surlignage a une étiquette (`label_id`, cf. db/annotation_labels),
# un style (surligné, souligné, barré, encadré) et une note. La validation est
# celle de services/annotations.py ; `color` reste, historique.
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
    *,
    label_id: int | None = None,
    style: str | None = None,
    note: str | None = None,
) -> int:
    """Mémorise un surlignage ; renvoie son id.

    `anchor` (v25, lecteur reconstruit) : {block_id, start, end} — ancrage TEXTE
    dans les blocs OCR ; `rects` reste la référence des documents raster.

    PAS DE DOUBLON : le même passage (même page, même texte) surligné une
    seconde fois met à jour le surlignage existant — couleur et rectangles —
    et renvoie SON id. Sinon chaque re-sélection empilait une couche de plus,
    et le contexte LLM citait le passage autant de fois. L'étiquette et le
    style ne changent que s'ils sont fournis, et une note existante n'est
    jamais effacée par un nouveau surlignage du même passage (v45)."""
    ensure_default_user()
    clean_color = color if color in _VALID_COLORS else "key"
    clean_quote = (quote or "").strip()
    conn = get_connection()
    existing = conn.execute(
        """SELECT id FROM reader_highlights
           WHERE user_id=? AND document_id=? AND page=? AND quote=? LIMIT 1""",
        (user_id or DEFAULT_USER_ID, int(document_id), int(page), clean_quote),
    ).fetchone()
    if existing is not None:
        with conn:
            conn.execute(
                """UPDATE reader_highlights
                   SET rects_json=?, color=?, anchor_json=?,
                       label_id=COALESCE(?, label_id), style=COALESCE(?, style),
                       note=COALESCE(?, note), updated_at=datetime('now')
                   WHERE id=?""",
                (
                    json.dumps(rects or [], ensure_ascii=False),
                    clean_color,
                    json.dumps(anchor, ensure_ascii=False) if anchor else None,
                    label_id,
                    style,
                    note or None,
                    existing["id"],
                ),
            )
        logger.info("Surlignage déjà présent id=%s (doc=%s page=%s), mis à jour", existing["id"], document_id, page)
        return int(existing["id"])
    with conn:
        cur = conn.execute(
            """INSERT INTO reader_highlights
               (user_id, document_id, page, quote, rects_json, color, anchor_json,
                label_id, style, note, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                user_id or DEFAULT_USER_ID,
                int(document_id),
                int(page),
                clean_quote,
                json.dumps(rects or [], ensure_ascii=False),
                clean_color,
                json.dumps(anchor, ensure_ascii=False) if anchor else None,
                label_id,
                style or "highlight",
                note or None,
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


def find_highlight(
    document_id: int, page: int, quote: str, user_id: int = DEFAULT_USER_ID
) -> dict | None:
    """Le surlignage de ce passage (même page, même texte), s'il existe déjà."""
    row = get_connection().execute(
        """SELECT * FROM reader_highlights
           WHERE user_id=? AND document_id=? AND page=? AND quote=? LIMIT 1""",
        (user_id, int(document_id), int(page), (quote or "").strip()),
    ).fetchone()
    return _decode(row) if row else None


def get_highlight(highlight_id: int, document_id: int, user_id: int = DEFAULT_USER_ID) -> dict | None:
    """Un surlignage DE CE DOCUMENT : l'id d'un autre document est introuvable."""
    row = get_connection().execute(
        "SELECT * FROM reader_highlights WHERE id=? AND document_id=? AND user_id=?",
        (int(highlight_id), int(document_id), user_id),
    ).fetchone()
    return _decode(row) if row else None


# Colonnes qu'une édition peut changer ; la valeur None est écrite telle quelle
# (étiquette retirée, note effacée) — c'est au service de dire quoi changer.
_EDITABLE = ("label_id", "style", "note")


def update_highlight(
    highlight_id: int, document_id: int, fields: dict, user_id: int = DEFAULT_USER_ID
) -> bool:
    """Applique `fields` (sous-ensemble de label_id, style, note) au surlignage
    du document. False s'il n'existe pas dans ce document."""
    changes = {k: v for k, v in fields.items() if k in _EDITABLE}
    if not changes:
        return get_highlight(highlight_id, document_id, user_id) is not None
    assignments = ", ".join(f"{column}=?" for column in changes)
    conn = get_connection()
    with conn:
        cur = conn.execute(
            f"""UPDATE reader_highlights SET {assignments}, updated_at=datetime('now')
                WHERE id=? AND document_id=? AND user_id=?""",
            (*changes.values(), int(highlight_id), int(document_id), user_id),
        )
    return bool(cur.rowcount)


def delete_highlight(
    highlight_id: int, user_id: int = DEFAULT_USER_ID, *, document_id: int | None = None
) -> int:
    """Supprime un surlignage (filtré par utilisateur et, si donné, par
    document : un id d'un autre document ne supprime rien). Renvoie le nb
    supprimé."""
    conn = get_connection()
    with conn:
        if document_id is None:
            cur = conn.execute(
                "DELETE FROM reader_highlights WHERE id=? AND user_id=?",
                (int(highlight_id), user_id),
            )
        else:
            cur = conn.execute(
                "DELETE FROM reader_highlights WHERE id=? AND user_id=? AND document_id=?",
                (int(highlight_id), user_id, int(document_id)),
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
