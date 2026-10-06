# services/orchestrator.py — Cycle de vie applicatif (import de document, statut LLM).
#
# Import d'un PDF ou d'un fichier de code, indexation des chapitres et fiche
# LLM du document. Appelé par le routeur `library` et par la coque desktop
# quand un document est passé en ligne de commande.
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from config.settings import (
    DOCUMENT_DIGEST_EXCERPT_CHARS,
    DOCUMENT_DIGEST_EXCERPT_PAGES,
)
from db.chapters import save_chapters
from db.documents import (
    get_document,
    get_document_by_path,
    set_document_digest_status,
    update_document_digest,
    upsert_document,
)
from db.user import DEFAULT_USER_ID
from llm.ollama_client import (
    generate_document_digest_async,
    is_cancelled_error,
    is_ollama_available,
)
from pdf_viewer.chapter_index import build_chapter_index
from pdf_viewer.pdf_document import PdfDocument
from services import library, pdf_rag
from services.relink import adopt_missing_twin, file_digest

logger = logging.getLogger("services.orchestrator")

# Nombre de passages en file d'une fiche de document coupée par la fermeture
# d'un lecteur (cf. generate_document_digest) avant de la déclarer en échec.
_DIGEST_REQUEUE_MAX = 3
# Délai avant de la remettre en file. Remise tout de suite, elle reprendrait le
# worker unique à l'instant où l'utilisateur ouvre le document suivant, dont
# l'accroche attendrait derrière — c'est précisément l'attente que la coupure
# devait éviter. Vingt secondes laissent passer ce qui est interactif. Zéro =
# remise synchrone (tests).
_DIGEST_REQUEUE_DELAY_S = 20.0

__all__ = ["import_pdf", "import_code", "llm_status", "generate_document_digest"]


def import_pdf(path: str) -> dict:
    """Importe un PDF : upsert document + index de chapitres. Renvoie le détail.

    Le PDF est rendu tel quel (moteur "pdfium_scroll") : aucune reconstruction,
    aucun appel réseau. Un fichier déplacé depuis son import retrouve son
    document, historique compris (`_adopt`).
    """
    with PdfDocument(path) as pdf:
        page_count = pdf.page_count()
        has_toc = bool(pdf.toc())
        doc_path = pdf.path
        filename = pdf.filename

    content_hash = file_digest(doc_path)
    adopted = _adopt(doc_path, content_hash, code=False)
    if adopted is not None:
        return adopted
    doc_id = upsert_document(
        doc_path, filename, page_count, "pdfium_scroll", has_toc, content_hash=content_hash,
    )
    save_chapters(doc_id, build_chapter_index(doc_path))
    pdf_rag.clear_index(doc_id)  # réimport sous le même chemin : l'index mémoire est périmé
    generate_document_digest(doc_id, filename)

    return library.get_document(doc_id) or {"id": doc_id}


def _adopt(path: str, content_hash: str, *, code: bool) -> dict | None:
    """Chemin encore inconnu, mais contenu déjà dans la bibliothèque sous un
    document INTROUVABLE (fichier déplacé, puis réimporté) : c'est ce document
    qu'on rouvre, relié au nouveau chemin (services/relink), plutôt qu'un
    doublon vierge. None : import ordinaire."""
    if get_document_by_path(path) is not None:
        return None
    doc_id = adopt_missing_twin(path, content_hash, code=code)
    if doc_id is None:
        return None
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

    # La fiche part en fond pendant que le lecteur s'ouvre : fermer ce lecteur
    # coupe TOUTE génération en vol (`cancel_pending_generations`), la sienne
    # comprise. Ce n'est pas un échec : on la remet en file, au fond (priorité
    # basse), un nombre borné de fois — elle passera quand la file sera calme.
    attempts = {"n": 0}

    def _enqueue() -> None:
        attempts["n"] += 1
        generate_document_digest_async(
            doc_title=Path(title).stem,
            excerpt=excerpt,
            on_success=_on_success,
            on_error=_on_error,
        )

    def _on_error(message: str) -> None:
        if is_cancelled_error(message) and attempts["n"] < _DIGEST_REQUEUE_MAX:
            try:
                if _DIGEST_REQUEUE_DELAY_S > 0:
                    timer = threading.Timer(_DIGEST_REQUEUE_DELAY_S, _enqueue)
                    timer.daemon = True
                    timer.start()
                else:
                    _enqueue()
                return
            except Exception:  # pragma: no cover - best-effort
                logger.debug("Remise en file de la fiche document ignorée", exc_info=True)
        set_document_digest_status(doc_id, "failed")

    try:
        set_document_digest_status(doc_id, "pending")
        _enqueue()
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
    content_hash = file_digest(path)
    adopted = _adopt(path, content_hash, code=True)
    if adopted is not None:
        return adopted
    doc_id = upsert_document(
        path, filename, pages, "code", False, doc_type="code", content_hash=content_hash,
    )
    pdf_rag.clear_index(doc_id)
    # Un fichier de code est précisément le cas où le nom seul ne dit rien :
    # la fiche (résumé + mots-clés) est ce qui permettra de le retrouver.
    generate_document_digest(doc_id, filename)
    return library.get_document(doc_id) or {"id": doc_id}


def llm_status() -> dict:
    return {"available": is_ollama_available()}
