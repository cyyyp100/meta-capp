# pdf_viewer/chapter_index.py — Détection des chapitres (sommaire natif + taille de police)
#
# Approche volontairement légère et sans dépendance supplémentaire :
#   1. Sommaire natif PyMuPDF (instantané, fiable quand présent).
#   2. Sinon, heuristique par taille de police (titres = lignes nettement plus
#      grandes que le corps, hors lignes de données / citations).
#   3. Sinon, pseudo-chapitres « Pages N–M ».
from __future__ import annotations

import logging
import re
from collections import Counter

from config.settings import DEFAULT_PAGES_PER_CHAPTER
from core.document import normalize_chapter_list
from pdf_viewer.pdf_document import PdfDocument

logger = logging.getLogger("pdf_viewer.chapters")

# Une ligne assez grande pour être un titre : au moins +15 % vs le corps.
_HEADING_SIZE_RATIO = 1.15
# Bornes raisonnables pour un titre.
_MAX_HEADING_WORDS = 16
_MAX_HEADING_CHARS = 110
_MIN_HEADING_CHARS = 3

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b\s*[)\].]?\s*$")
_DECIMAL_RE = re.compile(r"\d+[.,]\d+")
_NUMBERED_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+[A-Za-zÀ-ÿ]")
_BOOK_MARKER_RE = re.compile(
    r"^\s*(?:chap(?:itre|ter)?|partie|part|section|annexe|appendix|livre|book)\b",
    re.I,
)
# Sections classiques sans numéro (acceptées même en page de garde).
_KNOWN_SECTION_RE = re.compile(
    r"^\s*(?:abstract|résumé|resume|introduction|conclusion|discussion|"
    r"references|bibliography|bibliographie|acknowledg(?:e)?ments?|remerciements|"
    r"related\s+work|background|method(?:s|ology)?|results?|experiments?|"
    r"appendix|annexe)\s*$",
    re.I,
)
# Repères d'affiliation/auteur fréquents sur les pages de garde (à rejeter).
_AFFILIATION_RE = re.compile(
    r"\b(?:university|universit[ée]|institute|institut|laborator|laboratoire|"
    r"department|département|college|école|school|@|\.edu|\.com|\.org|"
    r"corresponding\s+author)\b",
    re.I,
)


def build_chapter_index(pdf_path: str) -> list[dict]:
    """Construit l'index de chapitres du document (métadonnée de lecture).

    Plus aucun écran de sélection : l'index sert à estimer le chapitre courant
    pendant le scroll libre et à contextualiser le LLM.
    Renvoie des dicts ``{title, page_start, page_end, toc_level}``.
    """
    doc = PdfDocument(pdf_path)
    doc.open()
    try:
        page_count = doc.page_count()
        toc = doc.toc()
        if toc:
            chapters = _chapters_from_toc(toc, page_count)
            if chapters:
                logger.info("Chapitres via sommaire natif : %d", len(chapters))
                return chapters

        chapters = _chapters_from_font_size(doc, page_count)
        if len(chapters) >= 3:
            logger.info("Chapitres via taille de police : %d", len(chapters))
            return chapters
    finally:
        doc.close()

    logger.info("Aucun titre détecté → pseudo-chapitres (%d pages)", DEFAULT_PAGES_PER_CHAPTER)
    return _pseudo_chapters(page_count)


def _chapters_from_toc(toc: list[dict], page_count: int) -> list[dict]:
    raw = [
        {"title": entry["title"], "page_start": int(entry["page"]), "toc_level": int(entry["level"])}
        for entry in toc
        if entry.get("title") and 1 <= int(entry.get("page", 1)) <= max(1, page_count)
    ]
    return normalize_chapter_list(raw, page_count)


def _chapters_from_font_size(doc: PdfDocument, page_count: int) -> list[dict]:
    """Détecte les titres comme les lignes nettement plus grandes que le corps."""
    lines: list[tuple[str, float, int]] = []  # (texte, taille, page)
    size_counter: Counter[float] = Counter()
    for page in range(1, page_count + 1):
        for text, size in doc.line_sizes(page):
            rounded = round(size, 1)
            lines.append((text, rounded, page))
            # Le corps de texte = lignes « longues » (paragraphes).
            if len(text) >= 24:
                size_counter[rounded] += 1

    if not lines:
        return []

    body_size = size_counter.most_common(1)[0][0] if size_counter else (
        Counter(round(size, 1) for _t, size, _p in lines).most_common(1)[0][0]
    )
    heading_floor = body_size * _HEADING_SIZE_RATIO

    candidates: list[tuple[str, float, int]] = []
    for text, size, page in lines:
        if size < heading_floor:
            continue
        if not _looks_like_heading(text, page):
            continue
        candidates.append((text, size, page))

    if len(candidates) < 3:
        return []

    # Niveaux : on regroupe les tailles de titres détectées et on attribue
    # 1 à la plus grande, 2 à la suivante, etc. (plafonné à 3).
    distinct_sizes = sorted({size for _t, size, _p in candidates}, reverse=True)
    level_of = {size: min(3, rank + 1) for rank, size in enumerate(distinct_sizes)}

    raw = [
        {"title": text, "page_start": page, "toc_level": level_of[size]}
        for text, size, page in candidates
    ]
    return normalize_chapter_list(raw, page_count)


def _looks_like_heading(text: str, page: int = 2) -> bool:
    clean = re.sub(r"\s+", " ", text).strip()
    if not (_MIN_HEADING_CHARS <= len(clean) <= _MAX_HEADING_CHARS):
        return False
    if len(clean.split()) > _MAX_HEADING_WORDS:
        return False
    # Lignes de données / résultats chiffrés (tableaux) : « 71.8 ± 0.9 », « 32.3 0.61 ».
    if "±" in clean or len(_DECIMAL_RE.findall(clean)) >= 2:
        return False
    # Citations bibliographiques se terminant par une année.
    if _YEAR_RE.search(clean) or "et al" in clean.casefold():
        return False
    # Affiliations / e-mails / auteurs : bruit fréquent sur la page de garde.
    if _AFFILIATION_RE.search(clean):
        return False
    # Doit contenir des lettres (pas une ligne de numéros de page isolés).
    if not re.search(r"[A-Za-zÀ-ÿ]{2,}", clean):
        return False

    structural = bool(
        _NUMBERED_RE.match(clean)
        or _BOOK_MARKER_RE.match(clean)
        or _KNOWN_SECTION_RE.match(clean)
    )
    # Page de garde (titre/auteurs/affiliations) : n'accepter qu'un vrai marqueur
    # de structure, jamais un titre « nu » (qui y est presque toujours du bruit).
    if page <= 1:
        return structural
    if structural:
        return True
    # Titre « nu » sur une page de contenu : court et sans ponctuation finale.
    return len(clean.split()) <= 12 and not clean.endswith((".", ";", ":", ","))


def _pseudo_chapters(page_count: int) -> list[dict]:
    if page_count < 1:
        return []
    n = max(1, int(DEFAULT_PAGES_PER_CHAPTER))
    chapters: list[dict] = []
    for start in range(1, page_count + 1, n):
        end = min(start + n - 1, page_count)
        chapters.append(
            {"title": f"Pages {start}–{end}", "page_start": start, "page_end": end, "toc_level": 1}
        )
    return chapters
