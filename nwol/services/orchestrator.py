# services/orchestrator.py — Cycle de vie applicatif (import de document, statut LLM).
#
# Import d'un PDF ou d'un fichier de code, indexation des chapitres et détection
# de la matière par le LLM. Appelé par le routeur `library` et par la coque
# desktop quand un document est passé en ligne de commande.
from __future__ import annotations

import logging
import os
from pathlib import Path

from db.chapters import save_chapters
from db.documents import update_document_subject, upsert_document
from db.user import DEFAULT_USER_ID
from llm.ollama_client import detect_document_subject_async, is_ollama_available
from pdf_viewer.chapter_index import build_chapter_index
from pdf_viewer.pdf_document import PdfDocument
from services import library

logger = logging.getLogger("services.orchestrator")

__all__ = ["import_pdf", "import_code", "llm_status", "detect_subject"]

# Nombre de pages lues pour deviner la matière, et taille max de l'extrait envoyé.
_SUBJECT_EXCERPT_PAGES = 2
_SUBJECT_EXCERPT_CHARS = 4000


def import_pdf(path: str) -> dict:
    """Importe un PDF : upsert document + index de chapitres. Renvoie le détail.

    Le PDF est rendu tel quel (moteur "pymupdf_scroll") : aucune reconstruction,
    aucun appel réseau.
    """
    with PdfDocument(path) as pdf:
        page_count = pdf.page_count()
        has_toc = bool(pdf.toc())
        doc_path = pdf.path
        filename = pdf.filename

    doc_id = upsert_document(doc_path, filename, page_count, "pymupdf_scroll", has_toc)
    save_chapters(doc_id, build_chapter_index(doc_path))
    detect_subject(doc_id, filename)

    return library.get_document(doc_id) or {"id": doc_id}


def detect_subject(doc_id: int, title: str) -> None:
    """Devine la matière du document via le LLM et la persiste — best-effort.

    Non bloquant : l'import rend la main immédiatement et la matière arrive plus
    tard (tâche `subject_detection`, très courte). La matière alimente les jauges
    par matière du quiz ; son absence ne dégrade que ce classement, jamais la
    lecture. Silencieux si Ollama est éteint."""
    excerpt = "\n".join(
        library.page_text(doc_id, page)
        for page in range(1, _SUBJECT_EXCERPT_PAGES + 1)
    )[:_SUBJECT_EXCERPT_CHARS]
    if not excerpt.strip():
        return

    def _on_success(result: dict) -> None:
        subject = (result or {}).get("subject")
        if not subject:
            return
        try:
            from db.subjects import ensure_subject

            update_document_subject(doc_id, subject)
            ensure_subject(DEFAULT_USER_ID, subject)
            logger.info("Matière détectée : doc=%s subject=%s", doc_id, subject)
        except Exception:  # pragma: no cover - best-effort
            logger.debug("Persistance de la matière ignorée", exc_info=True)

    try:
        detect_document_subject_async(
            doc_title=Path(title).stem,
            excerpt=excerpt,
            on_success=_on_success,
            on_error=lambda _e: None,
        )
    except Exception:  # pragma: no cover - le LLM reste un bonus
        logger.debug("Détection de matière indisponible", exc_info=True)


def import_code(path: str) -> dict:
    """Importe un fichier de CODE : document paginé, moteur "code".

    Réutilise l'infrastructure du lecteur (sessions, marque-page, sélection,
    contexte LLM) sans PDF ni reconstruction — le contenu est relu à la demande
    depuis le chemin. Aucun chapitre, aucun OCR.
    """
    from services import code_reader

    filename = os.path.basename(path)
    pages = code_reader.page_count(path)  # lève ValueError si binaire/trop gros
    doc_id = upsert_document(path, filename, pages, "code", False, doc_type="code")
    return library.get_document(doc_id) or {"id": doc_id}


def llm_status() -> dict:
    return {"available": is_ollama_available()}
