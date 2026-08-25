# services/orchestrator.py — Cycle de vie applicatif (import de document, statut LLM).
#
# Import d'un PDF ou d'un fichier de code, indexation des chapitres et fiche
# LLM du document. Appelé par le routeur `library` et par la coque desktop
# quand un document est passé en ligne de commande.
from __future__ import annotations

import logging
import os
from pathlib import Path

from config.settings import (
    DOCUMENT_DIGEST_EXCERPT_CHARS,
    DOCUMENT_DIGEST_EXCERPT_PAGES,
)
from db.chapters import save_chapters
from db.documents import (
    get_document,
    set_document_digest_status,
    update_document_digest,
    upsert_document,
)
from db.user import DEFAULT_USER_ID
from llm.ollama_client import generate_document_digest_async, is_ollama_available
from pdf_viewer.chapter_index import build_chapter_index
from pdf_viewer.pdf_document import PdfDocument
from services import library

logger = logging.getLogger("services.orchestrator")

__all__ = ["import_pdf", "import_code", "llm_status", "generate_document_digest"]


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
    generate_document_digest(doc_id, filename)

    return library.get_document(doc_id) or {"id": doc_id}


def generate_document_digest(doc_id: int, title: str) -> None:
    """Matière, résumé et mots-clés du document via le LLM — best-effort.

    UN seul appel (`document_digest`) là où il y en avait un pour la matière
    seule : une place dans la file, une source de vérité pour le classement.

    Non bloquant — l'import rend la main tout de suite et la fiche arrive
    quelques secondes plus tard. Silencieux si Ollama est éteint : le repli local
    (`_fallback_document_digest_from_prompt`) fournit quand même une matière et
    des mots-clés, donc la recherche reste utile hors ligne.
    """
    if (get_document(doc_id) or {}).get("digest_status") == "done":
        return  # Ré-import du même chemin : on ne rejoue pas une fiche déjà faite.

    excerpt = "\n".join(
        library.page_text(doc_id, page)
        for page in range(1, DOCUMENT_DIGEST_EXCERPT_PAGES + 1)
    )[:DOCUMENT_DIGEST_EXCERPT_CHARS]
    if not excerpt.strip():
        return

    def _on_success(result: dict) -> None:
        result = result or {}
        try:
            update_document_digest(
                doc_id,
                subject=result.get("subject"),
                summary=result.get("summary") or "",
                keywords=result.get("keywords") or [],
            )
            if result.get("subject"):
                from db.subjects import ensure_subject

                # Alimente les jauges par matière du quiz — inchangé.
                ensure_subject(DEFAULT_USER_ID, result["subject"])
        except Exception:  # pragma: no cover - best-effort
            logger.debug("Persistance de la fiche document ignorée", exc_info=True)

    def _on_error(_message: str) -> None:
        set_document_digest_status(doc_id, "failed")

    try:
        set_document_digest_status(doc_id, "pending")
        generate_document_digest_async(
            doc_title=Path(title).stem,
            excerpt=excerpt,
            on_success=_on_success,
            on_error=_on_error,
        )
    except Exception:  # pragma: no cover - le LLM reste un bonus
        set_document_digest_status(doc_id, "failed")
        logger.debug("Génération de la fiche document indisponible", exc_info=True)


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
    # Un fichier de code est précisément le cas où le nom seul ne dit rien :
    # la fiche (résumé + mots-clés) est ce qui permettra de le retrouver.
    generate_document_digest(doc_id, filename)
    return library.get_document(doc_id) or {"id": doc_id}


def llm_status() -> dict:
    return {"available": is_ollama_available()}
