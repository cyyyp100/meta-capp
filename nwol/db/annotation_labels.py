# db/annotation_labels.py — Étiquettes de la prise de notes (schéma v45).
#
# Une étiquette est un nom et une couleur de la palette fermée : « Important »,
# « Définition »… (semées, `preset` non NULL) puis celles de l'élève. Elles sont
# globales à l'utilisateur, pas au document. Un surlignage, un post-it ou un
# signet en porte une (`label_id`, SET NULL à la suppression de l'étiquette).
# Aucune validation ici : c'est le rôle de services/annotations.py.
from __future__ import annotations

import logging

from db import get_connection
from db.user import DEFAULT_USER_ID

logger = logging.getLogger("DB.annotation_labels")


def seed_presets(presets: tuple[tuple[str, str], ...], user_id: int = DEFAULT_USER_ID) -> int:
    """Sème les étiquettes prédéfinies de l'utilisateur s'il n'en a AUCUNE —
    base neuve, ou effacée. Une étiquette prédéfinie supprimée par l'élève ne
    revient donc pas. Renvoie le nombre d'étiquettes créées."""
    conn = get_connection()
    with conn:
        if conn.execute("SELECT 1 FROM annotation_labels WHERE user_id=? LIMIT 1", (user_id,)).fetchone():
            return 0
        cur = conn.executemany(
            """INSERT OR IGNORE INTO annotation_labels (user_id, preset, color, position)
               VALUES (?, ?, ?, ?)""",
            [(user_id, preset, color, position) for position, (preset, color) in enumerate(presets)],
        )
    created = int(cur.rowcount or 0)
    if created:
        logger.info("Étiquettes prédéfinies semées : %d (user=%s)", created, user_id)
    return created


def list_labels(user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Les étiquettes dans l'ordre de l'élève, avec le nombre d'éléments qui les
    portent (`usage` : surlignages + post-it + signets, tous documents)."""
    rows = get_connection().execute(
        """SELECT l.id, l.preset, l.name, l.color, l.position,
                  (SELECT COUNT(*) FROM reader_highlights h WHERE h.label_id = l.id)
                + (SELECT COUNT(*) FROM reader_notes n WHERE n.label_id = l.id) AS usage
           FROM annotation_labels l
           WHERE l.user_id=?
           ORDER BY l.position ASC, l.id ASC""",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_label(label_id: int, user_id: int = DEFAULT_USER_ID) -> dict | None:
    row = get_connection().execute(
        "SELECT id, preset, name, color, position FROM annotation_labels WHERE id=? AND user_id=?",
        (int(label_id), user_id),
    ).fetchone()
    return dict(row) if row else None


def preset_label_id(preset: str, user_id: int = DEFAULT_USER_ID) -> int | None:
    row = get_connection().execute(
        "SELECT id FROM annotation_labels WHERE user_id=? AND preset=?",
        (user_id, preset),
    ).fetchone()
    return int(row["id"]) if row else None


def count_labels(user_id: int = DEFAULT_USER_ID) -> int:
    row = get_connection().execute(
        "SELECT COUNT(*) AS n FROM annotation_labels WHERE user_id=?", (user_id,)
    ).fetchone()
    return int(row["n"])


def create_label(name: str, color: str, user_id: int = DEFAULT_USER_ID) -> int:
    """Ajoute une étiquette de l'élève, en dernière position."""
    conn = get_connection()
    with conn:
        position = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM annotation_labels WHERE user_id=?",
            (user_id,),
        ).fetchone()["p"]
        cur = conn.execute(
            "INSERT INTO annotation_labels (user_id, preset, name, color, position) VALUES (?, NULL, ?, ?, ?)",
            (user_id, name, color, int(position)),
        )
    logger.info("Étiquette créée id=%s", cur.lastrowid)
    return int(cur.lastrowid)


def update_label(label_id: int, fields: dict, user_id: int = DEFAULT_USER_ID) -> bool:
    """Applique `fields` (name, color) ; None est écrit tel quel (name NULL =
    nom traduit du preset)."""
    changes = {k: v for k, v in fields.items() if k in ("name", "color")}
    if not changes:
        return get_label(label_id, user_id) is not None
    assignments = ", ".join(f"{column}=?" for column in changes)
    conn = get_connection()
    with conn:
        cur = conn.execute(
            f"UPDATE annotation_labels SET {assignments} WHERE id=? AND user_id=?",
            (*changes.values(), int(label_id), user_id),
        )
    return bool(cur.rowcount)


def delete_label(label_id: int, user_id: int = DEFAULT_USER_ID) -> bool:
    """Supprime l'étiquette ; ses éléments restent, sans étiquette (SET NULL)."""
    conn = get_connection()
    with conn:
        cur = conn.execute("DELETE FROM annotation_labels WHERE id=? AND user_id=?", (int(label_id), user_id))
    if cur.rowcount:
        logger.info("Étiquette supprimée id=%s", label_id)
    return bool(cur.rowcount)


def set_positions(ordered_ids: list[int], user_id: int = DEFAULT_USER_ID) -> None:
    """Range les étiquettes dans l'ordre de `ordered_ids`."""
    conn = get_connection()
    with conn:
        conn.executemany(
            "UPDATE annotation_labels SET position=? WHERE id=? AND user_id=?",
            [(position, int(label_id), user_id) for position, label_id in enumerate(ordered_ids)],
        )
