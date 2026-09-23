# db/documents.py — CRUD table documents
import json
import logging
from datetime import datetime

from config.settings import LIBRARY_MAX_DOCUMENTS, LIBRARY_SEARCH_POOL
from db import get_connection

logger = logging.getLogger("DB.documents")


def upsert_document(
    path: str,
    filename: str,
    page_count: int,
    engine: str,
    has_toc: bool,
    doc_type: str = "book",
    subject: str | None = None,
) -> int:
    conn = get_connection()
    with conn:
        # `filename` est ABSENT du DO UPDATE : c'est le titre affiché dans la
        # bibliothèque, que l'utilisateur peut renommer (`rename_document`).
        # Le chemin est la clé du conflit, donc le nom sur disque n'a pas changé ;
        # ré-importer ne doit pas défaire un renommage.
        conn.execute(
            """INSERT INTO documents
               (path, filename, page_count, doc_type, extraction_engine, has_toc, last_opened, subject)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
                 page_count=excluded.page_count,
                 doc_type=excluded.doc_type,
                 extraction_engine=excluded.extraction_engine,
                 has_toc=excluded.has_toc,
                 last_opened=excluded.last_opened,
                 subject=COALESCE(excluded.subject, subject)""",
            (path, filename, page_count, doc_type, engine, int(has_toc),
             datetime.now().isoformat(), subject)
        )
        row = conn.execute("SELECT id FROM documents WHERE path=?", (path,)).fetchone()
        if row is None:
            raise RuntimeError(f"Document introuvable après upsert: {path}")
        doc_id = row["id"]
    logger.info(f"Document upsert id={doc_id} : {filename}")
    return doc_id


def get_document_by_path(path: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM documents WHERE path=?", (path,)).fetchone()
    return _decode_document(row) if row else None


def get_document(doc_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    return _decode_document(row) if row else None


def _decode_document(row) -> dict:
    """Ligne `documents` -> dict avec `keywords` décodé.

    Miroir de db.flashcards._decode_flashcard : le tableau JSON stocké en TEXT
    ne doit jamais fuir au-dessus de cette couche.
    """
    doc = dict(row)
    try:
        doc["keywords"] = json.loads(doc.get("keywords") or "[]")
    except (TypeError, ValueError):
        doc["keywords"] = []
    if not isinstance(doc["keywords"], list):
        doc["keywords"] = []
    return doc


def rename_document(doc_id: int, title: str) -> bool:
    """Change le titre affiché (`filename`) d'un document ; False s'il n'existe pas.

    Seule écriture de cette colonne après l'import. Tout ce qui affiche un
    titre de document (flashcards, quiz, brainstorming, recherche) lit
    `documents.filename` par jointure : le renommage se propage sans autre
    écriture. Le FICHIER sur disque n'est pas touché — comme à la suppression.
    """
    conn = get_connection()
    with conn:
        cur = conn.execute("UPDATE documents SET filename=? WHERE id=?", (title, doc_id))
    renamed = cur.rowcount > 0
    if renamed:
        logger.info("Document renommé id=%s : %s", doc_id, title)
    return renamed


def update_last_page(doc_id: int, page: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE documents SET last_page=?, last_opened=? WHERE id=?",
            (page, datetime.now().isoformat(), doc_id)
        )


def update_page_count(doc_id: int, page_count: int) -> None:
    """Réaligne `page_count` sur le fichier quand il a été réécrit depuis l'import."""
    conn = get_connection()
    with conn:
        conn.execute("UPDATE documents SET page_count=? WHERE id=?", (page_count, doc_id))


def get_document_subject(doc_id: int) -> str | None:
    conn = get_connection()
    row = conn.execute("SELECT subject FROM documents WHERE id=?", (doc_id,)).fetchone()
    return row["subject"] if row else None


def update_document_digest(
    doc_id: int,
    subject: str | None,
    summary: str,
    keywords: list[str],
) -> None:
    """Écrit la fiche LLM d'un document (matière + résumé + mots-clés).

    Un seul UPDATE, écrivain unique de ces quatre colonnes. `subject` est
    conservé si le LLM n'en propose pas — une fiche partielle ne doit pas
    effacer une matière déjà connue.
    """
    conn = get_connection()
    with conn:
        conn.execute(
            """UPDATE documents
               SET subject=COALESCE(?, subject), auto_summary=?, keywords=?,
                   digest_status='done'
               WHERE id=?""",
            (subject, summary, json.dumps(keywords, ensure_ascii=False), doc_id),
        )
    logger.info(
        "Fiche document mise à jour id=%s subject=%s mots-clés=%s",
        doc_id, subject, len(keywords),
    )


def set_document_digest_status(doc_id: int, status: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute("UPDATE documents SET digest_status=? WHERE id=?", (status, doc_id))


def list_recent_documents(limit: int = 10) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM documents ORDER BY last_opened DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_decode_document(r) for r in rows]


def list_all_documents(limit: int = LIBRARY_MAX_DOCUMENTS) -> list[dict]:
    """Catalogue complet, du plus récemment ouvert au plus ancien.

    `id DESC` départage les documents jamais ouverts (`last_opened` égal).
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM documents ORDER BY last_opened DESC, id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_decode_document(r) for r in rows]


def list_documents_for_search(limit: int = LIBRARY_SEARCH_POOL) -> list[dict]:
    """Lot borné parcouru par la recherche — même requête, autre intention."""
    return list_all_documents(limit)


def delete_document(doc_id: int) -> bool:
    """Supprime la ligne `documents` ; les tables liées suivent par cascade SQL
    (sessions, questions, réponses, surlignages, chapitres, index) — les
    flashcards, elles, passent à `document_id = NULL` et survivent (schéma).

    Le FICHIER source n'est jamais touché : `documents.path` désigne le PDF
    de l'utilisateur, là où il l'a choisi, pas une copie de l'application.
    Renvoie False si le document n'existait pas."""
    conn = get_connection()
    with conn:
        cur = conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    deleted = cur.rowcount > 0
    if deleted:
        logger.info("Document supprimé id=%s", doc_id)
    return deleted
