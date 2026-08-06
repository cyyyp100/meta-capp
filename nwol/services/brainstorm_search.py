# services/brainstorm_search.py — Recherche de contexte dans la base utilisateur.
#
# C'est le « tool » de Gemma pour le brainstorming : à partir d'une requête en
# langage naturel décidée par le LLM, on fouille les contenus de l'utilisateur
# (PDFs importés, surlignages, flashcards, anciennes Q&R) et on renvoie des
# extraits normalisés que le prompt et l'UI peuvent citer.
#
# Pas de FTS5 ni d'embeddings dans le projet. Sur une base locale mono-utilisateur
# (au plus quelques centaines de lignes par source), on charge un lot récent borné
# et on filtre EN PYTHON avec repli d'accents + insensibilité à la casse — bien plus
# robuste que `LIKE` SQL (qui ne sait pas matcher « photosynthèse » ↔ « photosynthese »).
from __future__ import annotations

import logging
import re
import unicodedata

from db import get_connection
from db.user import DEFAULT_USER_ID

logger = logging.getLogger("services.brainstorm_search")

# Mots vides FR/EN à ignorer pour ne pas matcher sur du bruit.
_STOPWORDS = {
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "que", "qui",
    "quoi", "pour", "par", "sur", "dans", "avec", "sans", "est", "sont", "ce",
    "cette", "ces", "son", "sa", "ses", "mon", "ma", "mes", "ton", "ta", "tes",
    "il", "elle", "on", "nous", "vous", "ils", "comme", "plus", "moins", "the",
    "and", "or", "for", "with", "this", "that", "these", "those", "what", "how",
    "about", "idea", "idee", "idees", "brainstorm", "brainstorming",
}

_MAX_SNIPPET = 280
# Lot récent chargé par source avant filtrage Python (base locale -> volumes faibles).
_CANDIDATE_POOL = 400


def _fold(text: str) -> str:
    """Minuscule + suppression des accents (comparaison robuste)."""
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def extract_terms(query: str, max_terms: int = 6) -> list[str]:
    """Découpe une requête en mots-clés significatifs (repliés, dédupliqués)."""
    words = re.findall(r"[\wàâäéèêëîïôöùûüç-]{3,}", (query or "").lower())
    terms: list[str] = []
    seen: set[str] = set()
    for w in words:
        if w in _STOPWORDS:
            continue
        folded = _fold(w)
        if not folded or folded in seen:
            continue
        seen.add(folded)
        terms.append(folded)
        if len(terms) >= max_terms:
            break
    return terms


def _matches(text: str, folded_terms: list[str]) -> bool:
    folded = _fold(text)
    return any(term in folded for term in folded_terms)


def search_user_db(
    query: str,
    limit_per_source: int = 3,
    user_id: int = DEFAULT_USER_ID,
) -> list[dict]:
    """Cherche dans la base de l'utilisateur. Renvoie des extraits normalisés.

    Chaque extrait : {source_type, snippet, doc_id?, doc_title?, page?}.
    Best-effort : toute source qui échoue est simplement ignorée.
    """
    terms = extract_terms(query)
    if not terms:
        return []
    results: list[dict] = []
    results.extend(_search_highlights(terms, limit_per_source, user_id))
    results.extend(_search_flashcards(terms, limit_per_source, user_id))
    results.extend(_search_questions(terms, limit_per_source))
    results.extend(_search_documents(terms, limit_per_source))
    return results


def _truncate(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= _MAX_SNIPPET else text[: _MAX_SNIPPET - 1] + "…"


def _search_highlights(terms: list[str], limit: int, user_id: int) -> list[dict]:
    try:
        conn = get_connection()
        rows = conn.execute(
            """SELECT h.quote, h.page, h.document_id, d.filename AS doc_title
               FROM reader_highlights h
               LEFT JOIN documents d ON d.id = h.document_id
               WHERE h.user_id=?
               ORDER BY h.id DESC LIMIT ?""",
            (user_id, _CANDIDATE_POOL),
        ).fetchall()
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Recherche surlignages échouée : %s", exc)
        return []
    out = []
    for r in rows:
        if not _matches(r["quote"] or "", terms):
            continue
        out.append({
            "source_type": "highlight",
            "doc_id": r["document_id"],
            "doc_title": r["doc_title"],
            "page": r["page"],
            "snippet": _truncate(r["quote"] or ""),
        })
        if len(out) >= limit:
            break
    return out


def _search_questions(terms: list[str], limit: int) -> list[dict]:
    try:
        conn = get_connection()
        rows = conn.execute(
            """SELECT q.question, q.answer, q.page_start, q.document_id, d.filename AS doc_title
               FROM questions q
               LEFT JOIN documents d ON d.id = q.document_id
               WHERE q.scope_type IN ('assistant_follow_up', 'qa_follow_up')
               ORDER BY q.id DESC LIMIT ?""",
            (_CANDIDATE_POOL,),
        ).fetchall()
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Recherche Q&R échouée : %s", exc)
        return []
    out = []
    for r in rows:
        q = (r["question"] or "").strip()
        a = (r["answer"] or "").strip()
        if not _matches(f"{q} {a}", terms):
            continue
        out.append({
            "source_type": "qa",
            "doc_id": r["document_id"],
            "doc_title": r["doc_title"],
            "page": r["page_start"],
            "snippet": _truncate(f"Q : {q} — R : {a}"),
        })
        if len(out) >= limit:
            break
    return out


def _search_flashcards(terms: list[str], limit: int, user_id: int) -> list[dict]:
    try:
        conn = get_connection()
        rows = conn.execute(
            """SELECT f.front, f.back, f.tags, f.document_id, d.filename AS doc_title
               FROM flashcards f
               LEFT JOIN documents d ON d.id = f.document_id
               WHERE f.user_id=?
               ORDER BY f.id DESC LIMIT ?""",
            (user_id, _CANDIDATE_POOL),
        ).fetchall()
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Recherche flashcards échouée : %s", exc)
        return []
    out = []
    for r in rows:
        front = (r["front"] or "").strip()
        back = (r["back"] or "").strip()
        if not _matches(f"{front} {back} {r['tags'] or ''}", terms):
            continue
        out.append({
            "source_type": "flashcard",
            "doc_id": r["document_id"],
            "doc_title": r["doc_title"],
            "page": None,
            "snippet": _truncate(f"{front} → {back}"),
        })
        if len(out) >= limit:
            break
    return out


def _search_documents(terms: list[str], limit: int) -> list[dict]:
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, filename FROM documents ORDER BY last_opened DESC LIMIT ?",
            (_CANDIDATE_POOL,),
        ).fetchall()
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Recherche documents échouée : %s", exc)
        return []
    out = []
    for r in rows:
        if not _matches(r["filename"] or "", terms):
            continue
        out.append({
            "source_type": "document",
            "doc_id": r["id"],
            "doc_title": r["filename"],
            "page": None,
            "snippet": _truncate(f"Document importé : {r['filename']}"),
        })
        if len(out) >= limit:
            break
    return out
