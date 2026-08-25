# services/library.py — Documents, pages et images (lecture).
#
# Frontière entre le frontend/serveur et le stockage des documents + le rendu
# PyMuPDF. Renvoie des dicts JSON-sérialisables ; les coordonnées de recherche
# sont en POINTS PDF (le client met à l'échelle selon le zoom d'affichage).
from __future__ import annotations

from datetime import datetime, timezone

from config.settings import (
    LIBRARY_MAX_DOCUMENTS,
    LIBRARY_SEARCH_LIMIT,
    LIBRARY_SEARCH_POOL,
    LIBRARY_SEARCH_WEIGHT_FILENAME,
    LIBRARY_SEARCH_WEIGHT_KEYWORD,
    LIBRARY_SEARCH_WEIGHT_SUBJECT,
    LIBRARY_SEARCH_WEIGHT_SUMMARY,
)
from db.chapters import get_chapters
from db.documents import get_document as _get_document
from db.documents import list_all_documents as _list_all
from db.documents import list_documents_for_search as _list_for_search
from db.documents import list_recent_documents as _list_recent
from pdf_viewer.page_renderer import clear_reader_cache as _clear_reader_cache
from pdf_viewer.page_renderer import render_page as _render_page
from pdf_viewer.pdf_document import PdfDocument
from utils.text import fold

__all__ = [
    "list_recent_documents",
    "list_all_documents",
    "search_documents",
    "get_document",
    "render_page",
    "page_text",
    "page_blocks",
    "page_words",
    "search_page",
    "clear_reader_cache",
]


def list_recent_documents(limit: int = 10) -> list[dict]:
    return [_summary(doc) for doc in _list_recent(limit)]


def list_all_documents(limit: int = LIBRARY_MAX_DOCUMENTS) -> list[dict]:
    return [_summary(doc) for doc in _list_all(limit)]


def search_documents(query: str, limit: int = LIBRARY_SEARCH_LIMIT) -> list[dict]:
    """Recherche globale : nom de fichier + résumé généré + mots-clés + matière.

    Filtrage en Python et non en SQL : `LIKE` ne sait pas plier les accents, or
    « equations » doit trouver « Équations différentielles ». La base est locale
    (quelques centaines de documents), on parcourt un lot borné.

    Classement calqué sur `pdf_rag.rank_chunks` : nombre de termes DISTINCTS
    trouvés d'abord (un document qui répond à toute la requête passe devant un
    document qui répète un seul mot), score pondéré ensuite, dernière ouverture
    pour départager.
    """
    from services.brainstorm_search import extract_terms

    terms = extract_terms(query, max_terms=6)
    if not terms:
        # « ia », « c++ », « rn » : requêtes courtes légitimes que le découpage
        # en mots significatifs rejette.
        folded = fold(query)
        if len(folded) < 2:
            return []
        terms = [folded]

    scored: list[tuple[int, int, str, dict]] = []
    for doc in _list_for_search(LIBRARY_SEARCH_POOL):
        haystacks = (
            (fold(doc.get("filename") or ""), LIBRARY_SEARCH_WEIGHT_FILENAME),
            (fold(" ".join(doc.get("keywords") or [])), LIBRARY_SEARCH_WEIGHT_KEYWORD),
            (fold(doc.get("auto_summary") or ""), LIBRARY_SEARCH_WEIGHT_SUMMARY),
            (fold(doc.get("subject") or ""), LIBRARY_SEARCH_WEIGHT_SUBJECT),
        )
        distinct = score = 0
        for term in terms:
            hit = sum(weight for (text, weight) in haystacks if term in text)
            if hit:
                distinct += 1
                score += hit
        if distinct:
            scored.append((distinct, score, doc.get("last_opened") or "", doc))

    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [_summary(doc) for (_d, _s, _o, doc) in scored[:limit]]


def get_document(doc_id: int) -> dict | None:
    """Détail d'un document : résumé + chapitres + tailles de page (points)."""
    doc = _get_document(doc_id)
    if doc is None:
        return None
    detail = _summary(doc)
    detail["chapters"] = get_chapters(doc_id)
    if doc.get("extraction_engine") == "code":
        # Pas de PDF : tailles de page uniformes (repli avant chargement des blocs).
        detail["page_sizes_pts"] = [[595, 842]] * (doc.get("page_count") or 1)
        return detail
    try:
        with PdfDocument(doc["path"]) as pdf:
            detail["page_sizes_pts"] = [[w, h] for (w, h) in pdf.page_sizes()]
    except Exception:
        detail["page_sizes_pts"] = []
    return detail


def render_page(doc_id: int, page: int, zoom: float = 2.5) -> str | None:
    """Chemin du PNG d'une page (cache disque géré par page_renderer)."""
    doc = _get_document(doc_id)
    if doc is None:
        return None
    if doc.get("extraction_engine") == "code":
        return None  # Document code : pas d'image (rendu texte côté client).
    return _render_page(doc["path"], page, zoom)


def page_text(doc_id: int, page: int) -> str:
    """Texte d'une page — LE point d'alimentation de tout l'empilement LLM."""
    doc = _get_document(doc_id)
    if doc is None:
        return ""
    if doc.get("extraction_engine") == "code":
        from services import code_reader

        return code_reader.page_text(doc["path"], page)
    with PdfDocument(doc["path"]) as pdf:
        return pdf.raw_text(page)


def page_blocks(doc_id: int, page: int) -> list[dict] | None:
    """Reader blocks d'une page (None si le document n'est pas en blocs)."""
    doc = _get_document(doc_id)
    if doc is None or doc.get("extraction_engine") != "code":
        return None
    from services import code_reader

    return [code_reader.page_block(doc["path"], page)]


def page_words(doc_id: int, page: int) -> list[list]:
    """Boîtes de mots d'une page → [[x0, y0, x1, y1, "mot"], …] en points PDF.

    Sert au calque de texte transparent du lecteur web (sélection native).
    """
    doc = _get_document(doc_id)
    if doc is None or doc.get("extraction_engine") == "code":
        return []
    with PdfDocument(doc["path"]) as pdf:
        return [[x0, y0, x1, y1, word] for (x0, y0, x1, y1, word) in pdf.words(page)]


def clear_reader_cache(doc_id: int) -> None:
    """Purge les pages rendues du doc (sauf la vignette) — fin de session lecture."""
    doc = _get_document(doc_id)
    if doc and doc.get("path"):
        _clear_reader_cache(doc["path"])


def search_page(doc_id: int, page: int, needle: str) -> list[list[float]]:
    """Rects (x0, y0, x1, y1) en points PDF où `needle` apparaît sur la page."""
    doc = _get_document(doc_id)
    if doc is None or doc.get("extraction_engine") == "code":
        return []
    with PdfDocument(doc["path"]) as pdf:
        return [list(rect) for rect in pdf.search_text(page, needle)]


def _local_import_date(created_at: str) -> str:
    """`documents.created_at` vient du `datetime('now')` de SQLite, donc en UTC,
    alors que `last_opened` est déjà local. Sans cette conversion, un import passé
    après 22 h (heure d'été) s'afficherait la veille dans la bibliothèque."""
    if not created_at:
        return ""
    try:
        utc = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return created_at
    return utc.astimezone().isoformat(timespec="seconds")


def _summary(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "title": doc.get("filename") or "",
        "filename": doc.get("filename") or "",
        "page_count": doc.get("page_count") or 0,
        "last_page": doc.get("last_page") or 1,
        "subject": doc.get("subject"),
        "last_opened": doc.get("last_opened") or "",
        # `created_at` est absent du ON CONFLICT DO UPDATE de `upsert_document` :
        # il date le PREMIER import et survit aux ré-ouvertures. D'où le nom exposé.
        "imported_at": _local_import_date(doc.get("created_at") or ""),
        # Le frontend branche le lecteur en blocs (fichiers de code) sur ce champ.
        "extraction_engine": doc.get("extraction_engine"),
        # Rangement et classification automatique (v26). Sans ces clés, rien
        # n'atteint le frontend : ce dict EST le contrat d'API du document.
        "folder_id": doc.get("folder_id"),
        "summary": doc.get("auto_summary") or "",
        "keywords": doc.get("keywords") or [],
        "digest_status": doc.get("digest_status") or "none",
    }
