# services/pdf_rag.py — Récupération de passages pertinents dans le document lu.
#
# Quand l'étudiant pose une question à la bulle Gemma, le contexte LLM ne contient
# que la page visible. Ce module fournit un RAG léger sur le MÊME document : on
# indexe paresseusement le texte PyMuPDF de toutes les pages, puis on renvoie les
# quelques passages (hors page courante) qui matchent les mots-clés de la question.
#
# Cohérent avec services/brainstorm_search.py : pas d'embeddings ni de FTS5 — on
# replie les accents et on filtre EN PYTHON. Index gardé en mémoire (backend
# mono-process, long-vivant). Best-effort : toute erreur dégrade vers « aucun
# passage » sans jamais casser la réponse de l'assistant.
from __future__ import annotations

import logging
import re

from db.documents import get_document
from pdf_viewer.pdf_document import PdfDocument
from services.brainstorm_search import _fold, extract_terms

logger = logging.getLogger("services.pdf_rag")

__all__ = ["retrieve", "rank_chunks", "clear_index"]

# Découpe du texte de page en passages : on vise des morceaux assez longs pour
# porter du sens, assez courts pour rester citables dans le prompt.
_MAX_CHUNK = 700
_DEFAULT_MAX_CHARS = 400

# Index par document : {doc_id: [{"page", "text", "folded"}, ...]}.
_INDEX_CACHE: dict[int, list[dict]] = {}


def _truncate(text: str, max_chars: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def _chunk_page_text(text: str) -> list[str]:
    """Découpe le texte brut d'une page en passages (~paragraphes regroupés).

    Split sur les lignes vides, fusion des fragments courts jusqu'à _MAX_CHUNK,
    fenêtrage des paragraphes trop longs. Espaces normalisés.
    """
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text or "")]
    paragraphs = [p for p in paragraphs if p]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        # Un paragraphe géant est découpé en tranches autonomes.
        while len(para) > _MAX_CHUNK:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(para[:_MAX_CHUNK])
            para = para[_MAX_CHUNK:]
        if not para:
            continue
        if not buf:
            buf = para
        elif len(buf) + 1 + len(para) <= _MAX_CHUNK:
            buf = f"{buf} {para}"
        else:
            chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c.strip()]


def _build_index(doc_id: int) -> list[dict]:
    """Index mémoire (paresseux) des passages du document. Best-effort.

    Un index vide légitime (PDF sans texte extractible) est mis en cache ; une
    erreur transitoire renvoie [] SANS cacher, pour réessayer au prochain appel.
    """
    cached = _INDEX_CACHE.get(doc_id)
    if cached is not None:
        return cached
    try:
        doc = get_document(doc_id)
        if not doc or not doc.get("path"):
            return []
        chunks: list[dict] = []
        if doc.get("extraction_engine") == "code":
            # Fichier de code : pas de PDF à ouvrir, le texte vient des pages
            # découpées par services/code_reader.
            from services.library import page_text as _page_text

            for page in range(1, int(doc.get("page_count") or 0) + 1):
                for piece in _chunk_page_text(_page_text(doc_id, page)):
                    chunks.append({"page": page, "text": piece, "folded": _fold(piece)})
        else:
            with PdfDocument(doc["path"]) as pdf:
                for page in range(1, pdf.page_count() + 1):
                    for piece in _chunk_page_text(pdf.raw_text(page)):
                        chunks.append({"page": page, "text": piece, "folded": _fold(piece)})
    except Exception as exc:  # pragma: no cover - défensif
        logger.debug("Index RAG doc %s échoué : %s", doc_id, exc)
        return []
    _INDEX_CACHE[doc_id] = chunks
    return chunks


def rank_chunks(
    chunks: list[dict],
    terms: list[str],
    current_page: int,
    top_k: int = 3,
) -> list[dict]:
    """Classe les passages par pertinence (termes pliés déjà fournis).

    Score = nb de termes DISTINCTS présents (primaire), occurrences totales
    (départage). La page courante est exclue (déjà dans le contexte page visible).
    """
    if not terms:
        return []
    scored: list[tuple[int, int, dict]] = []
    for chunk in chunks:
        if chunk.get("page") == current_page:
            continue
        folded = chunk.get("folded") or ""
        distinct = sum(1 for term in terms if term in folded)
        if distinct == 0:
            continue
        total = sum(folded.count(term) for term in terms)
        scored.append((distinct, total, chunk))
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    return [chunk for (_distinct, _total, chunk) in scored[:top_k]]


def retrieve(
    doc_id: int,
    question: str,
    current_page: int,
    top_k: int = 3,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> list[dict]:
    """Passages du document pertinents pour la question → [{"page", "text"}].

    Renvoie [] si aucun mot-clé exploitable ou aucun match (prompt inchangé).
    """
    terms = extract_terms(question)
    if not terms:
        return []
    chunks = _build_index(doc_id)
    if not chunks:
        return []
    return [
        {"page": chunk["page"], "text": _truncate(chunk["text"], max_chars)}
        for chunk in rank_chunks(chunks, terms, current_page, top_k)
    ]


def clear_index(doc_id: int | None = None) -> None:
    """Purge l'index mémoire (un document, ou tout). Utile en test / réimport."""
    if doc_id is None:
        _INDEX_CACHE.clear()
    else:
        _INDEX_CACHE.pop(doc_id, None)
