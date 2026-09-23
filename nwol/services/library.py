# services/library.py — Documents, pages et images (lecture).
#
# Frontière entre le frontend/serveur et le stockage des documents + le rendu
# PDFium. Renvoie des dicts JSON-sérialisables ; les coordonnées de recherche
# sont en POINTS PDF, origine haut-gauche (le client met à l'échelle selon le
# zoom d'affichage) — voir pdf_viewer/pdf_document.py pour la convention.
from __future__ import annotations

import logging
import os
from collections import OrderedDict
from datetime import datetime, timezone

from config.settings import (
    LIBRARY_DOCUMENT_TITLE_MAX,
    LIBRARY_MAX_DOCUMENTS,
    LIBRARY_SEARCH_LIMIT,
    LIBRARY_SEARCH_POOL,
    LIBRARY_SEARCH_WEIGHT_FILENAME,
    LIBRARY_SEARCH_WEIGHT_KEYWORD,
    LIBRARY_SEARCH_WEIGHT_SUBJECT,
    LIBRARY_SEARCH_WEIGHT_SUMMARY,
)
from db.chapters import get_chapters, save_chapters
from db.documents import delete_document as _delete_document
from db.documents import get_document as _get_document
from db.documents import list_all_documents as _list_all
from db.documents import list_documents_for_search as _list_for_search
from db.documents import list_recent_documents as _list_recent
from db.documents import rename_document as _rename_document
from db.documents import update_page_count as _update_page_count
from i18n import t
from pdf_viewer.chapter_index import build_chapter_index
from pdf_viewer.page_renderer import clear_page_cache as _clear_page_cache
from pdf_viewer.page_renderer import clear_reader_cache as _clear_reader_cache
from pdf_viewer.page_renderer import render_page as _render_page
from pdf_viewer.pdf_document import PdfDocument
from utils.text import fold

logger = logging.getLogger("services.library")

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
    "delete_document",
    "rename_document",
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
    if doc.get("extraction_engine") == "code":
        detail = _summary(doc)
        detail["chapters"] = get_chapters(doc_id)
        # Pas de PDF : tailles de page uniformes (repli avant chargement des blocs).
        detail["page_sizes_pts"] = [[595, 842]] * (doc.get("page_count") or 1)
        return detail
    try:
        with PdfDocument(doc["path"]) as pdf:
            sizes = [[w, h] for (w, h) in pdf.page_sizes()]
    except Exception:
        sizes = []
    if sizes and len(sizes) != doc.get("page_count"):
        doc = _resync_rewritten_pdf(doc, len(sizes))
    detail = _summary(doc)
    detail["chapters"] = get_chapters(doc_id)
    detail["page_sizes_pts"] = sizes
    return detail


def _resync_rewritten_pdf(doc: dict, page_count: int) -> dict:
    """Le PDF a été réécrit sur place depuis l'import (rapport LaTeX recompilé…).

    `page_count` fixe la liste des pages du lecteur : resté à l'ancienne valeur,
    il fait demander des pages qui n'existent plus. Le texte de page et l'index
    RAG se revalident seuls sur le mtime ; les chapitres et les PNG (cache
    indexé par le seul chemin) non — on refait donc ce que ferait un réimport.
    """
    logger.info(
        "PDF réécrit depuis l'import id=%s : %s -> %s pages",
        doc["id"], doc.get("page_count"), page_count,
    )
    _update_page_count(doc["id"], page_count)
    try:
        save_chapters(doc["id"], build_chapter_index(doc["path"]))
    except Exception:  # pragma: no cover - des chapitres périmés valent mieux qu'un lecteur fermé
        logger.warning("Chapitres non reconstruits pour doc=%s", doc["id"], exc_info=True)
    try:
        _clear_page_cache(doc["path"])
    except OSError:  # pragma: no cover - le cache disque est jetable
        pass
    return {**doc, "page_count": page_count}


def render_page(doc_id: int, page: int, zoom: float = 2.5) -> str | None:
    """Chemin du PNG d'une page (cache disque géré par page_renderer)."""
    doc = _get_document(doc_id)
    if doc is None:
        return None
    if doc.get("extraction_engine") == "code":
        return None  # Document code : pas d'image (rendu texte côté client).
    return _render_page(doc["path"], page, zoom)


# Cache du texte de page : {(doc_id, page): (mtime, texte)}, borné, FIFO.
# `page_text` est appelé plusieurs fois par question (contexte LLM, masque,
# densité mathématique du tick d'intervention toutes les 5 s) et chaque appel
# rouvrait le PDF entier via PDFium. Le mtime garde le cache honnête si le
# document est modifié ou réimporté sous le même chemin.
_PAGE_TEXT_CACHE: OrderedDict[tuple[int, int], tuple[float, str]] = OrderedDict()
_PAGE_TEXT_CACHE_MAX = 128


def page_text(doc_id: int, page: int) -> str:
    """Texte d'une page — LE point d'alimentation de tout l'empilement LLM."""
    doc = _get_document(doc_id)
    if doc is None:
        return ""
    key = (int(doc_id), int(page))
    mtime = _mtime(doc.get("path"))
    cached = _PAGE_TEXT_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        _PAGE_TEXT_CACHE.move_to_end(key)
        return cached[1]

    if doc.get("extraction_engine") == "code":
        from services import code_reader

        text = code_reader.page_text(doc["path"], page)
    else:
        with PdfDocument(doc["path"]) as pdf:
            text = pdf.raw_text(page)

    _PAGE_TEXT_CACHE[key] = (mtime, text)
    _PAGE_TEXT_CACHE.move_to_end(key)
    while len(_PAGE_TEXT_CACHE) > _PAGE_TEXT_CACHE_MAX:
        _PAGE_TEXT_CACHE.popitem(last=False)
    return text


def _mtime(path: str | None) -> float:
    try:
        return os.path.getmtime(str(path))
    except OSError:
        return 0.0


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
    for key in [k for k in _PAGE_TEXT_CACHE if k[0] == int(doc_id)]:
        _PAGE_TEXT_CACHE.pop(key, None)
    doc = _get_document(doc_id)
    if doc and doc.get("path"):
        _clear_reader_cache(doc["path"])


def delete_document(doc_id: int) -> dict:
    """Retire un document de la bibliothèque.

    Ce qui part : la ligne et tout ce qui n'a de sens que pour ce document
    (sessions de lecture et leurs jauges, questions et réponses, surlignages,
    chapitres — cascade SQL), plus les PNG rendus, vignette comprise, et le
    cache texte. Ce qui reste : les flashcards, qui se détachent du document
    (`document_id = NULL`) parce qu'elles appartiennent aux révisions, et le
    profil métacognitif (`metacog_history` se détache de la session).

    Le fichier source de l'utilisateur n'est jamais touché : on ne l'a jamais
    copié, on n'a pas à l'effacer. ValueError si le document n'existe pas."""
    doc = _get_document(doc_id)
    if doc is None:
        raise ValueError(t("folders.document_missing"))
    for key in [k for k in _PAGE_TEXT_CACHE if k[0] == int(doc_id)]:
        _PAGE_TEXT_CACHE.pop(key, None)
    if doc.get("path") and doc.get("extraction_engine") != "code":
        try:
            _clear_page_cache(doc["path"])
        except OSError:  # pragma: no cover - le cache disque est jetable
            pass
    _delete_document(doc_id)
    return {"deleted": True, "id": int(doc_id)}


def rename_document(doc_id: int, title: str) -> dict:
    """Renomme un document de la bibliothèque (clic droit → Renommer).

    C'est le TITRE qui change, pas le fichier : `documents.path` désigne le
    PDF de l'utilisateur là où il l'a choisi, et on ne le touche jamais (même
    règle qu'à la suppression). Le titre est nettoyé comme un nom de dossier
    (blancs repliés, longueur bornée) ; vide, il est refusé — un document sans
    nom serait introuvable dans la recherche, qui pèse le titre en premier.
    Renvoie le détail à jour. ValueError si le document n'existe pas ou si le
    titre est vide."""
    if _get_document(doc_id) is None:
        raise ValueError(t("folders.document_missing"))
    clean = " ".join(str(title or "").split())[:LIBRARY_DOCUMENT_TITLE_MAX]
    if not clean:
        raise ValueError(t("library.title_empty"))
    _rename_document(doc_id, clean)
    return get_document(doc_id) or {"id": int(doc_id)}


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
