# core/document.py — Chargement PDF, TOC, métadonnées
from __future__ import annotations
import logging
import re
from pathlib import Path
from typing import Any
from config.settings import DEFAULT_PAGES_PER_CHAPTER

logger = logging.getLogger("Document")

_SECTION_NUMBER_RE = re.compile(
    r"^\s*(?P<number>(?:\d+\s*\.\s*)*\d+|[A-Z](?:\s*\.\s*\d+)+|[A-Z]\.)"
    r"(?:\.)?(?:\s+|(?=[A-Za-zÀ-ÿ]))\S+",
    re.I,
)
_SECTION_NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?P<number>(?:\d+\s*\.\s*)*\d+|[A-Z](?:\s*\.\s*\d+)+|[A-Z]\.)"
    r"(?:\.)?(?:\s+|(?=[A-Za-zÀ-ÿ]))(?P<label>.+)$",
    re.I,
)
_LEADING_JUNK_RE = re.compile(r"^\s*[\.\-–—•·]+\s*(?=[A-Za-zÀ-ÿ])")
_SECTION_CROSS_REFERENCE_RE = re.compile(
    r"^\s*(?:section|sec\.?)\s+\d+(?:\.\d+)*\s+"
    r"(?:describes?|discuss(?:es)?|includes?|presents?|shows?|provides?|details?|introduces?|"
    r"explains?|contains?|is|are)\b",
    re.I,
)
_DISCOURSE_NUMBERED_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)+|[A-Z](?:\.\d+)+|[A-Z]\.)\.?\s+"
    r"(?:First|Second|Third|Finally|However|Moreover|Furthermore|This|These|The|We|Our|In|For|As)\b",
    re.I,
)
_COMMON_UNNUMBERED_SECTION_RE = re.compile(
    r"^\s*(?:abstract|résumé|resume|introduction|conclusion|discussion|references|"
    r"bibliography|bibliographie|acknowledg(?:e)?ments?|remerciements)\s*$",
    re.I,
)
_TOC_HEADING_RE = re.compile(
    r"^\s*(?:contents|table\s+of\s+contents|sommaire|table\s+des\s+mati[eè]res|"
    r"table\s+des\s+matieres)\s*$",
    re.I,
)
_TOC_ENTRY_TRAILING_PAGE_RE = re.compile(
    r"^\s*(?P<number>\d+(?:\.\d+)*)\.?\s+"
    r"(?P<label>[A-Za-zÀ-ÿ][^\n]*?)\s+"
    r"(?P<page>\d+|[ivxlcdm]+)\s*$",
    re.I,
)
_TOC_ENTRY_DOTTED_LEADER_RE = re.compile(r"\.{2,}\s*(?:\d+|[ivxlcdm]+)\s*$", re.I)
_METADATA_CHAPTER_RE = re.compile(
    r"(?:\bar\s*xiv\b\s*:?\s*\d{4}\.\d{4,5}|"
    r"\bdoi\b\s*:|\bdoi\.org\b|\bissn\b\s*:|\bisbn\b\s*:|"
    r"\bcopyright\b|\bcreative\s+commons\b)",
    re.I,
)
_PSEUDO_CHAPTER_RE = re.compile(r"^\s*pages?\s+\d+\s*[–-]\s*\d+\s*$", re.I)


class PDFDocument:
    def __init__(self, path: str):
        self.path = str(Path(path).resolve())
        self.filename = Path(path).name
        self._fitz_doc = None
        self.page_count: int = 0
        self.has_toc: bool = False
        self.toc: list[dict] = []
        self.chapters: list[dict] = []

    def open(self) -> None:
        try:
            import fitz
            self._fitz_doc = fitz.open(self.path)
            self.page_count = len(self._fitz_doc)
            self._load_toc()
            logger.info(f"PDF chargé : {self.filename} ({self.page_count} pages)")
        except Exception as e:
            logger.error(f"Impossible d'ouvrir {self.path} : {e}")
            raise

    def close(self) -> None:
        if self._fitz_doc:
            self._fitz_doc.close()
            self._fitz_doc = None

    def _load_toc(self) -> None:
        raw_toc = self._fitz_doc.get_toc()  # [(level, title, page), ...]
        if raw_toc:
            self.has_toc = True
            self.toc = [
                {"level": lvl, "title": title, "page": page}
                for lvl, title, page in raw_toc
            ]
            self.chapters = self._toc_to_chapters()
            logger.info(f"TOC natif trouvé : {len(self.chapters)} chapitres")
        else:
            self.has_toc = False
            self.chapters = self._make_pseudo_chapters()
            logger.warning(
                f"Pas de TOC natif → pseudo-chapitres "
                f"({DEFAULT_PAGES_PER_CHAPTER} pages chacun)"
            )

    def update_chapters_from_blocks(self, blocks: list[Any]) -> bool:
        """Remplace les pseudo-chapitres par des titres extraits du contenu PDF."""
        extracted = self._chapters_from_blocks(blocks)
        if not extracted:
            return False
        if self.has_toc:
            merged = _merge_chapter_lists(self.chapters, extracted, self.page_count)
            if merged == self.chapters:
                return False
            self.chapters = merged
            self.toc = [
                {
                    "level": int(chapter.get("toc_level", 1) or 1),
                    "title": chapter.get("title", ""),
                    "page": int(chapter.get("page_start", 1) or 1),
                }
                for chapter in merged
            ]
            logger.info("TOC enrichi depuis les titres extraits : %d entrée(s)", len(merged))
            return True
        if self.chapters == extracted:
            return False
        self.chapters = extracted
        self.has_toc = True
        self.toc = [
            {
                "level": int(chapter.get("toc_level", 1) or 1),
                "title": chapter.get("title", ""),
                "page": int(chapter.get("page_start", 1) or 1),
            }
            for chapter in extracted
        ]
        logger.info("TOC reconstruit depuis les titres extraits : %d entrée(s)", len(extracted))
        return True

    def _toc_to_chapters(self) -> list[dict]:
        """Convertit le TOC brut en portées sélectionnables, tous niveaux inclus."""
        chapters = []
        toc = self.toc
        for i, entry in enumerate(toc):
            # page_end = page before the next entry at the same or higher level
            page_end = self.page_count
            for j in range(i + 1, len(toc)):
                if toc[j]["level"] <= entry["level"]:
                    page_end = max(entry["page"], toc[j]["page"] - 1)
                    break
            chapters.append({
                "title": _clean_chapter_title(entry["title"]),
                "page_start": entry["page"],
                "page_end": page_end,
                "toc_level": entry["level"],
            })
        return normalize_chapter_list(chapters, self.page_count)

    def _chapters_from_blocks(self, blocks: list[Any]) -> list[dict]:
        headings: list[dict] = []
        for block in blocks:
            btype = _block_value(block, "type")
            if btype not in {"heading", "subheading", "subsubheading"}:
                continue
            if _block_is_metadata(block):
                continue
            title = _clean_chapter_title(str(_block_value(block, "text") or ""))
            if not title or _looks_like_document_title(title, block, headings):
                continue
            page = _block_page(block)
            if page is not None and _looks_like_toc_artifact(title, page, blocks):
                continue
            if not _looks_like_selectable_heading(title):
                continue
            if page is None:
                continue
            level = _heading_level_from_title(title) or _block_heading_level(block, btype)
            if _looks_like_back_matter_heading(title):
                level = 1
            headings.append({"title": title, "page_start": page, "toc_level": level})

        if len(headings) < 2:
            return []

        headings = _dedupe_chapter_candidates(headings)
        min_level = min(item["toc_level"] for item in headings)
        for item in headings:
            item["toc_level"] = max(1, item["toc_level"] - min_level + 1)

        chapters: list[dict] = []
        for i, entry in enumerate(headings):
            page_end = self.page_count
            for nxt in headings[i + 1 :]:
                if nxt["toc_level"] <= entry["toc_level"]:
                    page_end = max(entry["page_start"], nxt["page_start"] - 1)
                    break
            chapters.append({**entry, "page_end": page_end})
        return chapters

    def _make_pseudo_chapters(self) -> list[dict]:
        n = DEFAULT_PAGES_PER_CHAPTER
        chapters = []
        for start in range(1, self.page_count + 1, n):
            end = min(start + n - 1, self.page_count)
            chapters.append({
                "title": f"Pages {start}–{end}",
                "page_start": start,
                "page_end": end,
                "toc_level": 1,
            })
        return chapters

    def get_page_pixmap(self, page_number: int, dpi: int = 150):
        """Retourne un pixmap PyMuPDF pour affichage direct (page 1-based)."""
        if not self._fitz_doc:
            return None
        page = self._fitz_doc[page_number - 1]
        mat = __import__("fitz").Matrix(dpi / 72, dpi / 72)
        return page.get_pixmap(matrix=mat)


def _block_value(block: Any, key: str) -> Any:
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key, None)


def _block_is_metadata(block: Any) -> bool:
    metadata = _block_value(block, "metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return bool(_block_value(block, "is_metadata") or metadata.get("is_metadata"))


def _block_page(block: Any) -> int | None:
    for key in ("page", "page_number", "page_start"):
        value = _block_value(block, key)
        if value is None:
            continue
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            continue
    return None


def _block_heading_level(block: Any, btype: str) -> int:
    value = _block_value(block, "level")
    try:
        return min(3, max(1, int(value)))
    except (TypeError, ValueError):
        return {"heading": 1, "subheading": 2, "subsubheading": 3}.get(btype, 1)


def _heading_level_from_title(title: str) -> int | None:
    clean = _clean_chapter_title(title)
    match = _SECTION_NUMBER_RE.match(clean)
    if not match:
        return None
    number = _normalize_section_number(match.group("number"))
    return min(3, max(1, number.count(".") + 1))


def _looks_like_document_title(title: str, block: Any, previous_headings: list[dict]) -> bool:
    if previous_headings:
        return False
    page = _block_page(block)
    level = _block_heading_level(block, str(_block_value(block, "type") or "heading"))
    if page != 1 or level != 1:
        return False
    return not bool(_SECTION_NUMBER_RE.match(title))


def _looks_like_selectable_heading(title: str) -> bool:
    clean = _clean_chapter_title(title)
    if len(clean) < 4:
        return False
    if _looks_like_metadata_chapter_title(clean):
        return False
    if clean.endswith("-"):
        return False
    if _SECTION_CROSS_REFERENCE_RE.match(clean):
        return False
    if _DISCOURSE_NUMBERED_HEADING_RE.match(clean) and len(clean.split()) >= 8:
        return False
    if re.match(
        r"^\s*\d+(?:\.\d+)*\.?(?:\s+|(?=[A-Za-zÀ-ÿ]))(?:Figure|Fig\.?|Table|Tableau)\b",
        clean,
        re.I,
    ):
        return False
    if _SECTION_NUMBER_RE.match(clean):
        return True
    if re.match(r"^\s*(?:chapitre|chapter|partie|part|section|appendix|annexe)\b", clean, re.I):
        return True
    return _looks_like_back_matter_heading(clean)


def _looks_like_back_matter_heading(title: str) -> bool:
    return bool(
        re.match(
            r"^\s*(?:references|bibliography|bibliographie|acknowledg(?:e)?ments?|remerciements)\s*$",
            title,
            re.I,
        )
    )


def _merge_chapter_lists(existing: list[dict], extracted: list[dict], page_count: int) -> list[dict]:
    combined: list[dict] = []

    for chapter in [*existing, *extracted]:
        title = _clean_chapter_title(str(chapter.get("title") or ""))
        if not title:
            continue
        _append_or_replace_chapter(
            combined,
            {
                "title": title,
                "page_start": _coerce_positive_int(chapter.get("page_start"), 1),
                "toc_level": _heading_level_from_title(title)
                or _coerce_positive_int(chapter.get("toc_level"), 1),
            },
        )

    return normalize_chapter_list(combined, page_count)


def normalize_chapter_list(chapters: list[dict], page_count: int | None = None) -> list[dict]:
    """Clean, deduplicate and recompute chapter ranges.

    Old DB rows may still contain duplicate native/extracted TOC entries. When
    an unnumbered native title and a numbered extracted title point to the same
    label on the same page, the numbered title wins.
    """
    combined: list[dict] = []
    for chapter in chapters:
        title = _clean_chapter_title(str(chapter.get("title") or ""))
        if not title or _looks_like_metadata_chapter_title(title):
            continue
        _append_or_replace_chapter(
            combined,
            {
                "title": title,
                "page_start": _coerce_positive_int(chapter.get("page_start"), 1),
                "toc_level": _heading_level_from_title(title)
                or _coerce_positive_int(chapter.get("toc_level"), 1),
            },
        )

    combined = _drop_leading_document_title_candidate(combined)
    combined = _drop_toc_artifact_candidates(combined, page_count=page_count)
    combined = _drop_pseudo_chapters_when_real_headings_exist(combined)

    if not combined:
        return []

    inferred_page_count = page_count or max(
        _coerce_positive_int(chapter.get("page_end"), chapter.get("page_start", 1))
        for chapter in chapters
    )
    combined.sort(key=lambda item: (item["page_start"], _chapter_sort_number(item["title"]), item["toc_level"]))

    for index, entry in enumerate(combined):
        page_end = inferred_page_count
        for nxt in combined[index + 1 :]:
            if nxt["toc_level"] <= entry["toc_level"]:
                page_end = max(entry["page_start"], nxt["page_start"] - 1)
                break
        entry["page_end"] = page_end
    return combined


def _drop_pseudo_chapters_when_real_headings_exist(chapters: list[dict]) -> list[dict]:
    if not any(not _looks_like_pseudo_chapter(str(chapter.get("title") or "")) for chapter in chapters):
        return chapters
    return [
        chapter
        for chapter in chapters
        if not _looks_like_pseudo_chapter(str(chapter.get("title") or ""))
    ]


def _drop_toc_artifact_candidates(chapters: list[dict], page_count: int | None = None) -> list[dict]:
    """Remove physical table-of-contents headings exposed as selectable sections."""
    if not chapters:
        return chapters

    toc_pages = {
        _coerce_positive_int(chapter.get("page_start"), 1)
        for chapter in chapters
        if _looks_like_toc_heading(str(chapter.get("title") or ""))
    }

    page_entry_counts: dict[int, int] = {}
    for chapter in chapters:
        title = str(chapter.get("title") or "")
        if not _looks_like_toc_entry_title(title, page_count=page_count):
            continue
        page = _coerce_positive_int(chapter.get("page_start"), 1)
        page_entry_counts[page] = page_entry_counts.get(page, 0) + 1

    toc_pages.update(page for page, count in page_entry_counts.items() if count >= 3)

    return [
        chapter
        for chapter in chapters
        if not _looks_like_toc_heading(str(chapter.get("title") or ""))
        and not (
            _coerce_positive_int(chapter.get("page_start"), 1) in toc_pages
            and _looks_like_toc_entry_title(str(chapter.get("title") or ""), page_count=page_count)
        )
    ]


def _looks_like_toc_artifact(title: str, page: int, blocks: list[Any]) -> bool:
    if _looks_like_toc_heading(title):
        return True
    if not _looks_like_toc_entry_title(title):
        return False
    return any(
        _block_page(block) == page
        and _looks_like_toc_heading(str(_block_value(block, "text") or ""))
        for block in blocks
    )


def _looks_like_toc_heading(title: str) -> bool:
    return bool(_TOC_HEADING_RE.match(_clean_chapter_title(title)))


def _looks_like_toc_entry_title(title: str, page_count: int | None = None) -> bool:
    clean = _clean_chapter_title(title)
    if not clean:
        return False
    if _TOC_ENTRY_DOTTED_LEADER_RE.search(clean):
        return True

    match = _TOC_ENTRY_TRAILING_PAGE_RE.match(clean)
    if not match:
        return False

    label = re.sub(r"\s+", " ", match.group("label")).strip()
    if len(label) < 3:
        return False

    page_label = match.group("page")
    if page_label.isdigit() and page_count is not None and int(page_label) > page_count:
        return False
    return True


def _drop_leading_document_title_candidate(chapters: list[dict]) -> list[dict]:
    """Remove article-title bookmarks that some PDFs expose as a TOC entry.

    Scientific PDFs can have a native bookmark for the paper title before the
    real numbered sections. Keeping that title selectable creates a one-block
    reading scope, often made of a non-displayable semantic heading.
    """
    if len(chapters) < 2:
        return chapters

    first = chapters[0]
    title = _clean_chapter_title(str(first.get("title") or ""))
    if not _looks_like_native_document_title(title, first, chapters[1:]):
        return chapters
    return chapters[1:]


def _looks_like_native_document_title(title: str, chapter: dict, following: list[dict]) -> bool:
    if not title or _section_number(title) or _looks_like_back_matter_heading(title):
        return False
    if _COMMON_UNNUMBERED_SECTION_RE.match(title):
        return False
    if _coerce_positive_int(chapter.get("page_start"), 1) != 1:
        return False
    following_numbers = [_section_number(str(item.get("title") or "")) for item in following]
    if not any(number and "." not in number for number in following_numbers):
        return False
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", title)
    return ":" in title or len(words) >= 6 or len(title) >= 48


def _looks_like_metadata_chapter_title(title: str) -> bool:
    clean = re.sub(r"\s+", " ", str(title or "")).strip()
    if not clean:
        return False
    return bool(_METADATA_CHAPTER_RE.search(clean))


def _looks_like_pseudo_chapter(title: str) -> bool:
    return bool(_PSEUDO_CHAPTER_RE.match(str(title or "")))


def _dedupe_chapter_candidates(headings: list[dict]) -> list[dict]:
    result: list[dict] = []
    for heading in headings:
        _append_or_replace_chapter(result, heading)
    return result


def _append_or_replace_chapter(chapters: list[dict], candidate: dict) -> None:
    for index, current in enumerate(chapters):
        if not _chapters_equivalent(current, candidate):
            continue
        if _chapter_preference_score(candidate) > _chapter_preference_score(current):
            chapters[index] = candidate
        return
    chapters.append(candidate)


def _chapters_equivalent(left: dict, right: dict) -> bool:
    left_title = _clean_chapter_title(str(left.get("title") or ""))
    right_title = _clean_chapter_title(str(right.get("title") or ""))
    left_number = _section_number(left_title)
    right_number = _section_number(right_title)
    if left_number and right_number and left_number.casefold() == right_number.casefold():
        return True

    left_page = _coerce_positive_int(left.get("page_start"), 1)
    right_page = _coerce_positive_int(right.get("page_start"), 1)
    if left_page != right_page:
        return False

    left_label = _chapter_label_key(left_title)
    right_label = _chapter_label_key(right_title)
    if not left_label or not right_label:
        return False
    return left_label == right_label


def _chapter_preference_score(chapter: dict) -> tuple[int, int, int]:
    title = _clean_chapter_title(str(chapter.get("title") or ""))
    return (
        1 if _section_number(title) else 0,
        0 if _SECTION_CROSS_REFERENCE_RE.match(title) else 1,
        len(title),
    )


def _section_number(title: str) -> str | None:
    match = _SECTION_NUMBER_RE.match(_clean_chapter_title(title))
    if not match:
        return None
    return _normalize_section_number(match.group("number"))


def _chapter_sort_number(title: str) -> tuple:
    number = _section_number(title)
    if not number:
        return (1, _clean_chapter_title(str(title or "")).casefold())
    parts: list[Any] = []
    for part in number.split("."):
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part.casefold()))
    return (0, tuple(parts))


def _clean_chapter_title(title: str) -> str:
    clean = re.sub(r"\s+", " ", str(title or "")).strip()
    clean = _LEADING_JUNK_RE.sub("", clean).strip()
    match = _SECTION_NUMBER_PREFIX_RE.match(clean)
    if match:
        number = _normalize_section_number(match.group("number"))
        label = match.group("label").strip()
        if number and label:
            clean = f"{number}. {label}"
    clean = re.sub(r"^(\d+(?:\.\d+)+)\.(?=[A-Za-zÀ-ÿ])", r"\1. ", clean)
    clean = re.sub(r"^([A-Z])\.(?=[A-Za-zÀ-ÿ])", r"\1. ", clean, flags=re.I)
    clean = _trim_embedded_chapter_body(clean)
    return re.sub(r"\s+", " ", clean).strip()


def _normalize_section_number(number: str) -> str:
    raw = str(number or "").strip().rstrip(".")
    if not raw:
        return ""
    if re.fullmatch(r"[A-Z]\.?", raw, re.I):
        return raw.rstrip(".")
    parts = [part for part in re.split(r"\s*\.\s*", raw) if part]
    return ".".join(parts)


def _chapter_label_key(title: str) -> str:
    clean = _clean_chapter_title(title)
    match = _SECTION_NUMBER_PREFIX_RE.match(clean)
    if match:
        clean = match.group("label")
    clean = re.sub(
        r"^(?:chapitre|chapter|section|partie|part)\s+\d+(?:\.\d+)*\s*[:.\-–—]?\s*",
        "",
        clean,
        flags=re.I,
    )
    clean = re.sub(r"^[\.\-–—•·]+\s*", "", clean)
    clean = re.sub(r"[^\wÀ-ÿ]+", " ", clean, flags=re.I)
    return re.sub(r"\s+", " ", clean).strip().casefold()


def _trim_embedded_chapter_body(title: str) -> str:
    match = _SECTION_NUMBER_PREFIX_RE.match(title)
    if not match:
        return title
    number = _normalize_section_number(match.group("number"))
    words = match.group("label").split()
    if len(words) < 8:
        return title

    max_title_words = min(9, len(words) - 5)
    for split_at in range(2, max_title_words + 1):
        label = " ".join(words[:split_at]).strip()
        body = " ".join(words[split_at:]).strip()
        if not label or not body:
            continue
        if _bad_chapter_title_tail(label):
            continue
        if not _looks_like_embedded_chapter_body(body):
            continue
        return f"{number}. {label}".strip()
    return title


def _bad_chapter_title_tail(label: str) -> bool:
    words = re.findall(r"[A-Za-zÀ-ÿ]+", label.casefold())
    if not words:
        return True
    return words[-1] in {
        "a",
        "an",
        "the",
        "as",
        "of",
        "for",
        "to",
        "with",
        "in",
        "on",
        "and",
        "or",
        "de",
        "du",
        "des",
        "la",
        "le",
        "les",
        "un",
        "une",
        "et",
        "ou",
    }


def _looks_like_embedded_chapter_body(body: str) -> bool:
    clean = re.sub(r"\s+", " ", body or "").strip()
    if len(clean.split()) < 5:
        return False
    if clean[:1].islower():
        return False
    first_words = " ".join(clean.split()[:10])
    return bool(
        re.search(
            r"\b(can|may|must|should|will|is|are|was|were|means|depends|represents?|describes?|"
            r"shows?|uses?|requires?|allows?|gives?|has|have|does|do|peut|peuvent|est|sont|"
            r"signifie|depend|dépend|represente|représente)\b",
            first_words,
            re.I,
        )
    )


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        return max(1, int(value or default))
    except (TypeError, ValueError):
        return default
