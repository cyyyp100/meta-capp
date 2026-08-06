from __future__ import annotations

import re
import unicodedata

VAGUE_TAGS = {"cours", "important", "divers", "general", "général", "notion", "chapitre"}
STOPWORDS = {
    "avec",
    "dans",
    "des",
    "du",
    "elle",
    "est",
    "les",
    "leur",
    "pour",
    "que",
    "qui",
    "quoi",
    "sur",
    "une",
    "un",
    "the",
    "and",
    "or",
    "of",
}


def normalize_flashcard_tags(tags: list[str] | None, limit: int = 6) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags or []:
        clean = _clean_tag(tag)
        if not clean or clean in seen or clean in VAGUE_TAGS:
            continue
        normalized.append(clean)
        seen.add(clean)
        if len(normalized) >= limit:
            break
    return normalized


def fallback_flashcard_tags(
    front: str,
    back: str,
    existing_tags: list[str] | None = None,
    existing_sections: list[str] | None = None,
    minimum: int = 2,
    limit: int = 6,
) -> list[str]:
    text = f"{front or ''} {back or ''}"
    tokens = _keywords(text)
    candidates: list[str] = []

    known = normalize_flashcard_tags((existing_sections or []) + (existing_tags or []), limit=50)
    plain_text = _strip_accents(text.lower())
    for tag in known:
        if _strip_accents(tag) in plain_text:
            candidates.append(tag)

    candidates.extend(tokens)
    tags = normalize_flashcard_tags(candidates, limit=limit)
    if len(tags) >= minimum:
        return tags[:limit]
    for token in tokens:
        if token not in tags:
            tags.append(token)
        if len(tags) >= minimum:
            break
    return tags[:limit] or ["memoire"]


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[\wÀ-ÿ]{4,}", (text or "").lower(), flags=re.UNICODE)
    ranked: list[str] = []
    seen: set[str] = set()
    for word in words:
        clean = _clean_tag(word)
        if not clean or clean in seen or clean in STOPWORDS or clean in VAGUE_TAGS:
            continue
        ranked.append(clean)
        seen.add(clean)
        if len(ranked) >= 8:
            break
    return ranked


def _clean_tag(tag: str) -> str:
    clean = " ".join(str(tag or "").strip().lower().split())
    clean = re.sub(r"[^\wÀ-ÿ -]", "", clean, flags=re.UNICODE)
    clean = clean.replace("_", " ").strip(" -")
    if len(clean) > 32:
        clean = clean[:32].strip()
    return clean


def _strip_accents(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )
