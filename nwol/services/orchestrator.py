# services/orchestrator.py — Cycle de vie applicatif (import PDF, statut LLM).
#
# Extrait du flux d'import de ui/app.py, sans Tkinter. Réutilisé par le serveur
# FastAPI (et utilisable par l'ancienne UI pendant la transition).
from __future__ import annotations

import os

from db.chapters import save_chapters
from db.documents import upsert_document
from llm.ollama_client import is_ollama_available
from pdf_viewer.chapter_index import build_chapter_index
from pdf_viewer.pdf_document import PdfDocument
from services import library

__all__ = ["import_pdf", "import_code", "llm_status"]


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

    return library.get_document(doc_id) or {"id": doc_id}


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
