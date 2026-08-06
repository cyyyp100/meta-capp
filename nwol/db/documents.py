# db/documents.py — CRUD table documents
import logging
from datetime import datetime
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
        conn.execute(
            """INSERT INTO documents
               (path, filename, page_count, doc_type, extraction_engine, has_toc, last_opened, subject)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
                 filename=excluded.filename,
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
    return dict(row) if row else None


def get_document(doc_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    return dict(row) if row else None


def update_last_page(doc_id: int, page: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE documents SET last_page=?, last_opened=? WHERE id=?",
            (page, datetime.now().isoformat(), doc_id)
        )


def get_document_subject(doc_id: int) -> str | None:
    conn = get_connection()
    row = conn.execute("SELECT subject FROM documents WHERE id=?", (doc_id,)).fetchone()
    return row["subject"] if row else None


def update_document_subject(doc_id: int, subject: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE documents SET subject=? WHERE id=?",
            (subject, doc_id),
        )
    logger.info("Matière document mise à jour id=%s subject=%s", doc_id, subject)


def list_recent_documents(limit: int = 10) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM documents ORDER BY last_opened DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
