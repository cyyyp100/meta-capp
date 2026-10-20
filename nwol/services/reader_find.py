# services/reader_find.py — Ctrl/Cmd+F du lecteur : chercher dans tout le document.
#
# La recherche de PDFium (`PdfDocument.search_text`) ne trouvait ni « equation »
# dans « Équation », ni un mot coupé en fin de ligne. Celle-ci cherche dans le
# texte PLIÉ de chaque page (`utils.text.fold_with_map` : accents et casse
# retirés, blancs réduits, césures recollées), et c'est dans ce même texte que
# `PdfDocument.find_folded` localise les occurrences : le total annoncé (« 3 /
# 17 ») et les occurrences surlignées ne peuvent pas diverger.
#
# Deux temps, deux endpoints : le RÉSUMÉ (combien, sur quelles pages) sur tout le
# document, depuis un index en mémoire ; les BOÎTES d'une page, à la demande,
# pour la page à l'écran et ses voisines. Pour un fichier de code, des plages en
# offsets UTF-16 dans le texte du bloc affiché, calculées ici : Python (NFKD) et
# JavaScript (NFD) ne replient pas les accents de la même façon.
from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict

from config.settings import READER_FIND_MAX_PAGE_HITS, READER_FIND_MAX_QUERY_CHARS, READER_FIND_MIN_CHARS
from db.documents import get_document
from pdf_viewer.pdf_document import PdfDocument
from utils.text import find_all, fold_query, fold_with_map, utf16_offsets

logger = logging.getLogger("services.reader_find")

__all__ = ["find_in_document", "find_on_page", "forget"]

# Index : {doc_id: {key: (chemin, mtime, page_count), pages: [texte plié]}}, LRU.
# Seuls les textes pliés sont gardés, jamais les tables de positions (`map`), cinq
# fois plus lourdes : ~3 Mo pour un document de 1 000 pages. Construit par lots
# qui relâchent PDFIUM_LOCK entre eux, comme l'index RAG (pdf_rag._page_texts) :
# une page demandée par le lecteur pendant l'indexation d'un manuel passe entre
# deux lots. Mesuré sur 458 pages : 0,41 s d'extraction, 0,13 s de repli, moins
# d'une milliseconde par requête ensuite.
_INDEX_MAX_DOCS = 3
_INDEX_BATCH_PAGES = 25
_INDEX: OrderedDict[int, dict] = OrderedDict()
_LOCK = threading.Lock()
# Un verrou de construction par document : deux requêtes simultanées (la frappe
# rebondit, le résumé et une page partent ensemble) n'indexent pas deux fois.
_BUILD_LOCKS: dict[int, threading.Lock] = {}


def find_in_document(doc_id: int, query: str) -> dict | None:
    """`{query, total, pages: [{page, count}], searchable, too_short}` — None si
    le document n'existe pas. `DocumentFileMissing` si son fichier a disparu.

    `query` est la requête PLIÉE (ce qui a été cherché). `searchable` faux : le
    document n'a aucun texte (PDF scanné) — l'interface le dit au lieu
    d'annoncer « aucun résultat ». `too_short` : moins de READER_FIND_MIN_CHARS
    caractères pliés, rien n'est cherché."""
    doc = get_document(doc_id)
    if doc is None:
        return None
    needle = _needle(query)
    pages = _pages(doc)
    result = {
        "query": needle,
        "total": 0,
        "pages": [],
        "searchable": any(text.strip() for text in pages),
        "too_short": len(needle) < READER_FIND_MIN_CHARS,
    }
    if result["too_short"] or not result["searchable"]:
        return result
    counts = [
        {"page": page, "count": count}
        for page, text in enumerate(pages, start=1)
        if (count := text.count(needle))
    ]
    result["pages"] = counts
    result["total"] = sum(entry["count"] for entry in counts)
    return result


def find_on_page(doc_id: int, page: int, query: str) -> dict | None:
    """Les occurrences d'une page, au plus READER_FIND_MAX_PAGE_HITS
    (`truncated` dit s'il y en avait plus) — None si le document n'existe pas.

    PDF : `{page, rects, truncated}`, une liste de rects (points PDF, origine
    haut-gauche, un par ligne) par occurrence. Fichier de code : `{page, ranges,
    truncated}`, des plages `[début, fin)` en unités UTF-16 du texte du bloc."""
    doc = get_document(doc_id)
    if doc is None:
        return None
    needle = _needle(query)
    code = doc.get("extraction_engine") == "code"
    empty = {"page": int(page), "ranges" if code else "rects": [], "truncated": False}
    if len(needle) < READER_FIND_MIN_CHARS:
        return empty
    path = _require_file(doc)
    limit = READER_FIND_MAX_PAGE_HITS + 1
    if code:
        from services import code_reader

        text = code_reader.page_block(path, int(page))["text"]
        folded, mapping = fold_with_map(text)
        offsets = utf16_offsets(text)
        starts = find_all(folded, needle, limit)
        ranges = [
            [offsets[mapping[start]], offsets[mapping[start + len(needle) - 1] + 1]]
            for start in starts[:READER_FIND_MAX_PAGE_HITS]
        ]
        return {**empty, "ranges": ranges, "truncated": len(starts) > READER_FIND_MAX_PAGE_HITS}
    with PdfDocument(path) as pdf:
        hits = pdf.find_folded(int(page), needle, limit)
    rects = [
        [[round(value, 2) for value in rect] for rect in hit]
        for hit in hits[:READER_FIND_MAX_PAGE_HITS]
    ]
    return {**empty, "rects": rects, "truncated": len(hits) > READER_FIND_MAX_PAGE_HITS}


def forget(doc_id: int) -> None:
    """Oublie l'index d'un document : lecteur fermé (library.clear_reader_cache),
    document supprimé ou relié à un autre fichier (library.forget_path_caches)."""
    with _LOCK:
        _INDEX.pop(int(doc_id), None)


# ── Interne ──────────────────────────────────────────────────────────────────


def _needle(query: str) -> str:
    return fold_query(str(query or "")[:READER_FIND_MAX_QUERY_CHARS])


def _require_file(doc: dict) -> str:
    """Même règle que la lecture d'une page : un fichier déplacé répond 410
    `file_missing` (server/app.py), l'interface propose de le localiser."""
    from services.library import DocumentFileMissing, file_missing

    path = doc.get("path") or ""
    if file_missing(path):
        raise DocumentFileMissing(doc["id"], path)
    return path


def _pages(doc: dict) -> list[str]:
    """Textes pliés de toutes les pages, depuis l'index ou construits. La clé
    (chemin, mtime, nombre de pages) revalide l'index d'un fichier réécrit ou
    relié depuis."""
    path = _require_file(doc)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    key = (path, mtime, int(doc.get("page_count") or 0))
    doc_id = int(doc["id"])
    with _LOCK:
        cached = _cached(doc_id, key)
        if cached is not None:
            return cached
        build_lock = _BUILD_LOCKS.setdefault(doc_id, threading.Lock())
    with build_lock:
        with _LOCK:
            cached = _cached(doc_id, key)  # construit pendant qu'on attendait
            if cached is not None:
                return cached
        pages = _build(doc, path)
        with _LOCK:
            _INDEX[doc_id] = {"key": key, "pages": pages}
            _INDEX.move_to_end(doc_id)
            while len(_INDEX) > _INDEX_MAX_DOCS:
                _INDEX.popitem(last=False)
    logger.info("Index de recherche du lecteur : doc=%s, %d pages", doc_id, len(pages))
    return pages


def _cached(doc_id: int, key: tuple) -> list[str] | None:
    """Sous `_LOCK`."""
    entry = _INDEX.get(doc_id)
    if entry is None or entry["key"] != key:
        return None
    _INDEX.move_to_end(doc_id)
    return entry["pages"]


def _build(doc: dict, path: str) -> list[str]:
    if doc.get("extraction_engine") == "code":
        from services import code_reader

        return [fold_with_map(text)[0] for text in code_reader.page_texts(path)]
    pages: list[str] = []
    with PdfDocument(path) as pdf:
        count = pdf.page_count()
    for start in range(1, count + 1, _INDEX_BATCH_PAGES):
        with PdfDocument(path) as pdf:
            for page in range(start, min(start + _INDEX_BATCH_PAGES, count + 1)):
                pages.append(pdf.folded_text(page))
    return pages
