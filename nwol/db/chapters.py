# db/chapters.py — CRUD table chapters
import logging
from db import get_connection

logger = logging.getLogger("DB.chapters")


def save_chapters(doc_id: int, chapters: list[dict]) -> None:
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM chapters WHERE document_id=?", (doc_id,))
        conn.executemany(
            "INSERT INTO chapters (document_id, title, page_start, page_end, toc_level) VALUES (?,?,?,?,?)",
            [(doc_id, c["title"], c["page_start"], c.get("page_end"), c.get("toc_level", 1))
             for c in chapters]
        )
    logger.info(f"Chapitres sauvegardés pour doc={doc_id} ({len(chapters)})")


def get_chapters(doc_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM chapters WHERE document_id=? ORDER BY page_start, toc_level, id", (doc_id,)
    ).fetchall()
    return [dict(r) for r in rows]
