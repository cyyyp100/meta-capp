# db/flashcard_checks.py — Relectures des flashcards par Clikoda (migration v47)
from __future__ import annotations

from db import get_connection
from db.user import DEFAULT_USER_ID


def cards_to_check(limit: int, user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Les cartes à relire : jamais relues, ou modifiées depuis leur relecture
    (leur clé de doublon n'est plus celle qu'on a relue). Les plus anciennes
    d'abord. Les cartes de langue en sont exclues : elles ont leurs propres
    règles (lemme, sens, prononciation — services/flashcards)."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT f.id, f.front, f.back, f.dedup_key
             FROM flashcards f
        LEFT JOIN flashcard_checks c ON c.card_id = f.id
            WHERE f.user_id = ?
              AND f.language IS NULL
              AND (c.card_id IS NULL OR c.checked_key IS NOT f.dedup_key)
         ORDER BY f.created_at, f.id
            LIMIT ?""",
        (user_id or DEFAULT_USER_ID, max(0, int(limit))),
    ).fetchall()
    return [dict(row) for row in rows]


def save_check(
    card_id: int,
    checked_key: str,
    status: str,
    kind: str | None = None,
    front: str | None = None,
    back: str | None = None,
    reason: str | None = None,
) -> None:
    """Ce que la relecture a conclu ; remplace la relecture précédente."""
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO flashcard_checks (card_id, checked_key, checked_at, status, kind, front, back, reason)
               VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?)
               ON CONFLICT(card_id) DO UPDATE SET
                   checked_key = excluded.checked_key,
                   checked_at  = excluded.checked_at,
                   status      = excluded.status,
                   kind        = excluded.kind,
                   front       = excluded.front,
                   back        = excluded.back,
                   reason      = excluded.reason""",
            (card_id, checked_key, status, kind, front, back, reason),
        )


def get_suggestions(user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Les corrections qui attendent l'élève, avec la carte telle qu'elle est.
    Une carte modifiée depuis la relecture n'en a plus : la correction portait
    sur un texte qui n'existe plus."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT f.id AS card_id, f.front, f.back, c.kind,
                  c.front AS suggested_front, c.back AS suggested_back, c.reason, c.checked_at
             FROM flashcard_checks c
             JOIN flashcards f ON f.id = c.card_id
            WHERE f.user_id = ? AND c.status = 'suggested' AND c.checked_key IS f.dedup_key
         ORDER BY c.checked_at, f.id""",
        (user_id or DEFAULT_USER_ID,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_check(card_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM flashcard_checks WHERE card_id = ?", (card_id,)).fetchone()
    return dict(row) if row else None


def set_status(card_id: int, status: str, checked_key: str | None = None) -> None:
    """Suite donnée par l'élève (acceptée, écartée). `checked_key` : celle de
    la carte réécrite, pour qu'une correction acceptée ne soit pas relue."""
    conn = get_connection()
    with conn:
        if checked_key is None:
            conn.execute("UPDATE flashcard_checks SET status = ? WHERE card_id = ?", (status, card_id))
        else:
            conn.execute(
                "UPDATE flashcard_checks SET status = ?, checked_key = ? WHERE card_id = ?",
                (status, checked_key, card_id),
            )
