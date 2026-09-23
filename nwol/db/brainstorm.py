# db/brainstorm.py — CRUD des discussions de brainstorming (chat libre avec Gemma).
#
# Deux tables (schéma v23) :
#   brainstorm_discussions : 1 ligne par discussion (+ résumé glissant ;
#                            v33 : `pinned_at`, `folder_id`)
#   brainstorm_messages    : historique complet, 1 ligne par tour (user|assistant)
#
# SQL pur : la limite d'épinglage et la validation du dossier sont décidées dans
# `services/brainstorm.py`.
import json
import logging

from db import get_connection
from db.user import DEFAULT_USER_ID

logger = logging.getLogger("DB.brainstorm")

# Titre d'une discussion créée sans nom. Une discussion est VIERGE tant qu'elle
# porte l'un de ces titres et n'a aucun message : c'est la page blanche que
# « Nouvelle discussion » rouvre au lieu d'en empiler une autre.
DEFAULT_TITLE = "Nouvelle discussion"
BLANK_TITLES = (DEFAULT_TITLE, "New discussion")
TITLE_MAX_CHARS = 200

_BLANK_WHERE = f"message_count = 0 AND title IN ({', '.join('?' * len(BLANK_TITLES))})"


def create_discussion(
    title: str,
    folder_id: int | None = None,
    user_id: int = DEFAULT_USER_ID,
) -> int:
    title = (title or "").strip() or DEFAULT_TITLE
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO brainstorm_discussions (user_id, title, folder_id) VALUES (?, ?, ?)",
            (user_id, title[:TITLE_MAX_CHARS], folder_id),
        )
    logger.info("Discussion brainstorming créée id=%s dossier=%s", cur.lastrowid, folder_id)
    return int(cur.lastrowid)


def create_blank_discussion(folder_id: int | None = None, user_id: int = DEFAULT_USER_ID) -> int:
    """Rouvre la discussion vierge de l'utilisateur, ou en crée une s'il n'en a pas.

    Au plus une page blanche à la fois : dix clics sur « Nouvelle discussion »
    empilaient dix discussions vides. L'INSERT est conditionnel, en une seule
    requête — vérifier puis insérer en deux laisserait deux clics simultanés
    passer tous les deux. Il ouvre la transaction d'écriture même quand il
    n'insère rien, donc la vierge relue ensuite ne peut plus disparaître.

    La discussion rouverte remonte en tête des récentes (`updated_at`) ;
    ``folder_id`` donné la lie à ce dossier, ``None`` laisse son lien tel quel.
    """
    conn = get_connection()
    with conn:
        cur = conn.execute(
            f"""INSERT INTO brainstorm_discussions (user_id, title, folder_id)
                SELECT ?, ?, ?
                WHERE NOT EXISTS (SELECT 1 FROM brainstorm_discussions
                                  WHERE user_id=? AND {_BLANK_WHERE})""",
            (user_id, DEFAULT_TITLE, folder_id, user_id, *BLANK_TITLES),
        )
        if cur.rowcount > 0:
            logger.info("Discussion brainstorming créée id=%s dossier=%s", cur.lastrowid, folder_id)
            return int(cur.lastrowid)
        row = conn.execute(
            f"""SELECT id FROM brainstorm_discussions WHERE user_id=? AND {_BLANK_WHERE}
                ORDER BY updated_at DESC, id DESC LIMIT 1""",
            (user_id, *BLANK_TITLES),
        ).fetchone()
        conn.execute(
            """UPDATE brainstorm_discussions
               SET updated_at=datetime('now'), folder_id=COALESCE(?, folder_id)
               WHERE id=?""",
            (folder_id, row["id"]),
        )
    logger.info("Discussion brainstorming vierge rouverte id=%s", row["id"])
    return int(row["id"])


def list_discussions(user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Épinglées d'abord (ordre d'épinglage, le plus récent en tête), puis le reste
    par activité. Épingler ne touche pas `updated_at` : une épinglée ne saute
    donc pas d'une place à chaque message."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT b.id, b.title, b.summary, b.message_count, b.created_at, b.updated_at,
                  b.pinned_at, b.folder_id, f.name AS folder_name
           FROM brainstorm_discussions b
           LEFT JOIN library_folders f ON f.id = b.folder_id
           WHERE b.user_id=?
           ORDER BY b.pinned_at IS NULL, b.pinned_at DESC, b.updated_at DESC, b.id DESC""",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_discussion(discussion_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        """SELECT b.*, f.name AS folder_name
           FROM brainstorm_discussions b
           LEFT JOIN library_folders f ON f.id = b.folder_id
           WHERE b.id=?""",
        (discussion_id,),
    ).fetchone()
    return dict(row) if row else None


def pin_discussion(discussion_id: int, max_pinned: int, user_id: int = DEFAULT_USER_ID) -> bool:
    """Épingle la discussion si le plafond n'est pas atteint. ``False`` sinon.

    Un seul UPDATE conditionnel : compter puis écrire en deux requêtes laisserait
    deux épinglages simultanés passer tous les deux sous le plafond. Déjà
    épinglée -> ``True`` sans rien réécrire (sa place en tête ne bouge pas).
    """
    conn = get_connection()
    with conn:
        row = conn.execute(
            "SELECT pinned_at FROM brainstorm_discussions WHERE id=?", (discussion_id,)
        ).fetchone()
        if row is not None and row["pinned_at"] is not None:
            return True
        cur = conn.execute(
            """UPDATE brainstorm_discussions SET pinned_at=datetime('now')
               WHERE id=? AND pinned_at IS NULL
                 AND (SELECT COUNT(*) FROM brainstorm_discussions
                      WHERE user_id=? AND pinned_at IS NOT NULL) < ?""",
            (discussion_id, user_id, int(max_pinned)),
        )
    return cur.rowcount > 0


def unpin_discussion(discussion_id: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE brainstorm_discussions SET pinned_at=NULL WHERE id=?", (discussion_id,)
        )


def set_discussion_folder(discussion_id: int, folder_id: int | None) -> None:
    """Lie la discussion à un dossier (``None`` = toute la base)."""
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE brainstorm_discussions SET folder_id=? WHERE id=?",
            (folder_id, discussion_id),
        )
    logger.info("Discussion brainstorming id=%s liée au dossier %s", discussion_id, folder_id)


def rename_discussion(discussion_id: int, title: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE brainstorm_discussions SET title=?, updated_at=datetime('now') WHERE id=?",
            ((title or "").strip()[:TITLE_MAX_CHARS] or DEFAULT_TITLE, discussion_id),
        )


def delete_discussion(discussion_id: int) -> None:
    conn = get_connection()
    with conn:
        # ON DELETE CASCADE supprime les messages associés.
        conn.execute("DELETE FROM brainstorm_discussions WHERE id=?", (discussion_id,))
    logger.info("Discussion brainstorming supprimée id=%s", discussion_id)


def add_message(
    discussion_id: int,
    role: str,
    content: str,
    sources: list[dict] | None = None,
) -> int:
    """Ajoute un message et incrémente le compteur de la discussion."""
    sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO brainstorm_messages (discussion_id, role, content, sources_json) VALUES (?, ?, ?, ?)",
            (discussion_id, role, content, sources_json),
        )
        conn.execute(
            """UPDATE brainstorm_discussions
               SET message_count = message_count + 1, updated_at = datetime('now')
               WHERE id=?""",
            (discussion_id,),
        )
    return int(cur.lastrowid)


def get_messages(discussion_id: int, limit: int | None = None) -> list[dict]:
    """Messages d'une discussion, du plus ancien au plus récent.

    Avec ``limit``, renvoie les N DERNIERS messages (toujours en ordre
    chronologique) — pratique pour borner le contexte envoyé au LLM.
    """
    conn = get_connection()
    if limit is None:
        rows = conn.execute(
            "SELECT * FROM brainstorm_messages WHERE discussion_id=? ORDER BY id",
            (discussion_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM brainstorm_messages WHERE discussion_id=? ORDER BY id DESC LIMIT ?",
            (discussion_id, int(limit)),
        ).fetchall()
        rows = list(reversed(rows))
    return [_decode(r) for r in rows]


def update_summary(discussion_id: int, summary: str, upto_msg_id: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """UPDATE brainstorm_discussions
               SET summary=?, summary_upto_msg_id=?
               WHERE id=?""",
            ((summary or "").strip(), int(upto_msg_id), discussion_id),
        )


def _decode(row) -> dict:
    data = dict(row)
    raw = data.pop("sources_json", None)
    try:
        data["sources"] = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        data["sources"] = []
    return data
