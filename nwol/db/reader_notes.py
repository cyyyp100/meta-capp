# db/reader_notes.py — Post-it et signets du lecteur (schéma v45).
#
# Un post-it est posé sur une page : (x, y) en points PDF, origine haut-gauche,
# NULL pour un fichier de code (il s'empile dans la marge). Un signet marque une
# page, sans position ; un seul par page (index unique partiel). Toutes les
# fonctions sont bornées au document : l'id d'une note d'un autre document est
# introuvable. Aucune validation ici : c'est le rôle de services/annotations.py.
from __future__ import annotations

import logging

from db import get_connection
from db.user import DEFAULT_USER_ID

logger = logging.getLogger("DB.reader_notes")

_COLUMNS = "id, document_id, page, kind, x, y, body, label_id, created_at, updated_at"


def list_notes(document_id: int, user_id: int = DEFAULT_USER_ID) -> list[dict]:
    rows = get_connection().execute(
        f"""SELECT {_COLUMNS} FROM reader_notes
            WHERE user_id=? AND document_id=?
            ORDER BY page ASC, COALESCE(y, 0) ASC, COALESCE(x, 0) ASC, id ASC""",
        (user_id, int(document_id)),
    ).fetchall()
    return [dict(row) for row in rows]


def get_note(note_id: int, document_id: int, user_id: int = DEFAULT_USER_ID) -> dict | None:
    row = get_connection().execute(
        f"SELECT {_COLUMNS} FROM reader_notes WHERE id=? AND document_id=? AND user_id=?",
        (int(note_id), int(document_id), user_id),
    ).fetchone()
    return dict(row) if row else None


def signet_on_page(document_id: int, page: int, user_id: int = DEFAULT_USER_ID) -> dict | None:
    row = get_connection().execute(
        f"""SELECT {_COLUMNS} FROM reader_notes
            WHERE user_id=? AND document_id=? AND page=? AND kind='signet'""",
        (user_id, int(document_id), int(page)),
    ).fetchone()
    return dict(row) if row else None


def create_note(
    document_id: int,
    page: int,
    kind: str,
    *,
    x: float | None,
    y: float | None,
    body: str,
    label_id: int | None,
    user_id: int = DEFAULT_USER_ID,
) -> int:
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO reader_notes (user_id, document_id, page, kind, x, y, body, label_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, int(document_id), int(page), kind, x, y, body, label_id),
        )
    logger.info("Note créée id=%s (%s, doc=%s page=%s)", cur.lastrowid, kind, document_id, page)
    return int(cur.lastrowid)


_EDITABLE = ("body", "label_id", "x", "y")


def update_note(note_id: int, document_id: int, fields: dict, user_id: int = DEFAULT_USER_ID) -> bool:
    """Applique `fields` (body, label_id, x, y) à la note du document ; False si
    elle n'existe pas dans ce document."""
    changes = {k: v for k, v in fields.items() if k in _EDITABLE}
    if not changes:
        return get_note(note_id, document_id, user_id) is not None
    assignments = ", ".join(f"{column}=?" for column in changes)
    conn = get_connection()
    with conn:
        cur = conn.execute(
            f"""UPDATE reader_notes SET {assignments}, updated_at=datetime('now')
                WHERE id=? AND document_id=? AND user_id=?""",
            (*changes.values(), int(note_id), int(document_id), user_id),
        )
    return bool(cur.rowcount)


def delete_note(note_id: int, document_id: int, user_id: int = DEFAULT_USER_ID) -> int:
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "DELETE FROM reader_notes WHERE id=? AND document_id=? AND user_id=?",
            (int(note_id), int(document_id), user_id),
        )
    return int(cur.rowcount or 0)
