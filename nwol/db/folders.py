# db/folders.py — CRUD de l'arbre de dossiers de la bibliothèque (schéma v26).
#
# SQL pur, aucune politique : les cycles, la profondeur maximale et le sort des
# documents d'un dossier supprimé sont décidés dans `services/folders.py`.
# `parent_id IS NULL` marque la racine ; les filtres nullables passent par
# `IS ?` (SQLite compare NULL correctement avec `IS`, pas avec `=`).
import logging

from config.settings import LIBRARY_FOLDER_NAME_MAX
from db import get_connection
from db.user import DEFAULT_USER_ID, ensure_default_user

logger = logging.getLogger("DB.folders")

_COLUMNS = "id, parent_id, name, position, created_at"


def create_folder(
    name: str,
    parent_id: int | None = None,
    user_id: int = DEFAULT_USER_ID,
) -> int:
    ensure_default_user()
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO library_folders (user_id, parent_id, name, position) VALUES (?, ?, ?, ?)",
            (user_id, parent_id, name[:LIBRARY_FOLDER_NAME_MAX], next_position(parent_id, user_id)),
        )
    logger.info("Dossier créé id=%s parent=%s : %s", cur.lastrowid, parent_id, name)
    return int(cur.lastrowid)


def get_folder(folder_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM library_folders WHERE id=?", (folder_id,)
    ).fetchone()
    return dict(row) if row else None


def list_folders(user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Liste plate, ordonnée pour un assemblage d'arbre déterministe."""
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT {_COLUMNS} FROM library_folders WHERE user_id=?
            ORDER BY parent_id IS NOT NULL, parent_id, position, name COLLATE NOCASE""",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def rename_folder(folder_id: int, name: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE library_folders SET name=? WHERE id=?",
            (name[:LIBRARY_FOLDER_NAME_MAX], folder_id),
        )
    logger.info("Dossier renommé id=%s : %s", folder_id, name)


def set_folder_parent(folder_id: int, parent_id: int | None, position: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE library_folders SET parent_id=?, position=? WHERE id=?",
            (parent_id, position, folder_id),
        )
    logger.info("Dossier déplacé id=%s -> parent=%s", folder_id, parent_id)


def delete_folder(folder_id: int) -> None:
    """Supprime le dossier. Les sous-dossiers suivent (ON DELETE CASCADE) ; les
    documents sont seulement détachés (ON DELETE SET NULL)."""
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM library_folders WHERE id=?", (folder_id,))
    logger.info("Dossier supprimé id=%s", folder_id)


def next_position(parent_id: int | None, user_id: int = DEFAULT_USER_ID) -> int:
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS next FROM library_folders "
        "WHERE user_id=? AND parent_id IS ?",
        (user_id, parent_id),
    ).fetchone()
    return int(row["next"]) if row else 0


def descendant_ids(folder_id: int) -> set[int]:
    """IDs du sous-arbre, `folder_id` compris.

    Sert au garde-fou de cycle : déplacer un dossier dans l'un de ses propres
    descendants détacherait le sous-arbre de la racine — invisible ET
    indestructible depuis l'interface.
    """
    conn = get_connection()
    rows = conn.execute(
        """WITH RECURSIVE sub(id) AS (
               SELECT id FROM library_folders WHERE id = ?
               UNION ALL
               SELECT f.id FROM library_folders f JOIN sub ON f.parent_id = sub.id
           )
           SELECT id FROM sub""",
        (folder_id,),
    ).fetchall()
    return {int(row["id"]) for row in rows}


def set_document_folder(doc_id: int, folder_id: int | None) -> None:
    conn = get_connection()
    with conn:
        conn.execute("UPDATE documents SET folder_id=? WHERE id=?", (folder_id, doc_id))
    logger.info("Document rangé id=%s -> dossier=%s", doc_id, folder_id)


def count_documents_by_folder() -> dict[int | None, int]:
    """{folder_id: nombre de documents}. Un seul GROUP BY, jamais N requêtes."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT folder_id, COUNT(*) AS n FROM documents GROUP BY folder_id"
    ).fetchall()
    return {row["folder_id"]: int(row["n"]) for row in rows}
