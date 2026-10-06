# db/session_warmup.py — Persistance de la révision éclair du sas d'entrée
from __future__ import annotations

import logging

from db import get_connection

logger = logging.getLogger("DB.session_warmup")

_COLUMNS = ("position", "card_id", "front_ms", "back_ms", "front_pace", "back_pace")


def save_session_warmup(session_id: int, cards: list[dict]) -> bool:
    """Enregistre le warm-up d'une séance (une ligne par carte).

    Une séance n'a qu'UN warm-up : s'il est déjà en base (le lecteur renvoie
    `start_reading` à chaque reconnexion), rien n'est écrit et la fonction
    renvoie False — l'appelant ne doit alors pas en reverser l'effet."""
    if not session_id or not cards:
        return False
    conn = get_connection()
    with conn:
        if conn.execute(
            "SELECT 1 FROM session_warmup_cards WHERE session_id=? LIMIT 1", (int(session_id),)
        ).fetchone():
            return False
        conn.executemany(
            f"INSERT INTO session_warmup_cards (session_id, {', '.join(_COLUMNS)}) "
            f"VALUES (?, {', '.join('?' for _ in _COLUMNS)})",
            [(int(session_id), *(card.get(col) for col in _COLUMNS)) for card in cards],
        )
    logger.info("Warm-up persisté : session=%s cartes=%d", session_id, len(cards))
    return True


def get_session_warmup(session_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM session_warmup_cards WHERE session_id=? ORDER BY position",
        (session_id,),
    ).fetchall()
    return [dict(row) for row in rows]
