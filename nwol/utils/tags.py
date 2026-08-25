# utils/tags.py — Normalisation des étiquettes libres produites par le LLM.
#
# Deux consommateurs, mêmes règles : les tags de flashcards et les mots-clés de
# documents. Un mot-clé qui ne survivrait pas au même nettoyage qu'un tag rendrait
# la recherche incohérente d'un écran à l'autre.
from __future__ import annotations

import re
import unicodedata

from config.settings import DOCUMENT_KEYWORDS_MAX

VAGUE_TAGS = {"cours", "important", "divers", "general", "général", "notion", "chapitre"}
# Filtre élargi pour les documents : « introduction » ou « sommaire » ne permet
# de retrouver aucun PDF dans une bibliothèque de cours.
DOCUMENT_VAGUE_TAGS = VAGUE_TAGS | {
    "introduction", "conclusion", "document", "pdf", "livre", "support",
    "sommaire", "table des matieres", "table des matières", "resume", "résumé",
    "notes", "partie", "section", "page", "exercice", "exercices",
}
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


def normalize_document_keywords(
    keywords: list[str] | None,
    limit: int = DOCUMENT_KEYWORDS_MAX,
) -> list[str]:
    """Mots-clés d'un document : mêmes règles que les tags de flashcard, avec le
    filtre de vacuité élargi.

    Les accents sont CONSERVÉS dans le mot-clé stocké (« mathématiques », pas
    « mathematiques ») : c'est du texte affiché. L'insensibilité aux accents est
    appliquée au moment de la RECHERCHE, en pliant les deux côtés.
    """
    result: list[str] = []
    seen: set[str] = set()
    for keyword in keywords or []:
        clean = _clean_tag(keyword)
        if not clean or len(clean) < 2 or clean in seen:
            continue
        if _strip_accents(clean) in _FOLDED_DOCUMENT_VAGUE_TAGS:
            continue
        result.append(clean)
        seen.add(clean)
        if len(result) >= limit:
            break
    return result


def fallback_document_keywords(
    title: str,
    excerpt: str,
    limit: int = DOCUMENT_KEYWORDS_MAX,
) -> list[str]:
    """Mots-clés sans LLM : le titre d'abord (signal le plus dense), puis l'extrait."""
    return normalize_document_keywords(
        _keywords(title or "") + _keywords(excerpt or ""), limit=limit
    )


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
    # L'apostrophe est conservée : elle appartient au mot en français, et la
    # retirer donnait « droits de lhomme » sur une étiquette affichée.
    # L'apostrophe typographique est ramenée à la droite pour ne pas dédoubler
    # « l'homme » et « l’homme ».
    clean = clean.replace("’", "'")
    clean = re.sub(r"[^\wÀ-ÿ '-]", "", clean, flags=re.UNICODE)
    clean = clean.replace("_", " ").strip(" -'")
    if len(clean) > 32:
        # Coupe sur un mot : une étiquette est affichée telle quelle, et
        # « droits de l'homm » se lit comme un bug.
        cut = clean[:32]
        space = cut.rfind(" ")
        clean = (cut[:space] if space >= 12 else cut).strip(" -'")
    return clean


def _strip_accents(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


# Plié une seule fois au chargement, pas à chaque mot-clé examiné.
_FOLDED_DOCUMENT_VAGUE_TAGS = {_strip_accents(tag) for tag in DOCUMENT_VAGUE_TAGS}
