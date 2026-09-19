# services/brainstorm_search.py — Recherche de contexte dans la base utilisateur.
#
# C'est le « tool » de Gemma pour le brainstorming : à partir d'une requête en
# langage naturel décidée par le LLM, on fouille les contenus de l'utilisateur
# (PDFs importés, surlignages, flashcards, anciennes Q&R) et on renvoie des
# extraits normalisés que le prompt et l'UI peuvent citer.
#
# Pas de FTS5 ni d'embeddings ICI : la recherche est LEXICALE. Sur une base
# locale mono-utilisateur, on charge un lot borné par table et on filtre EN
# PYTHON avec repli d'accents + insensibilité à la casse — bien plus robuste que
# `LIKE` SQL (qui ne sait pas matcher « photosynthèse » ↔ « photosynthese »).
# (Seul services/pdf_rag.py, la recherche dans le document LU, ajoute une couche
# d'embeddings au lexical : là, la question est en français et le document en
# anglais, et la réponse fonde le contenu de Gemma, pas seulement sa couleur.)
#
# Le classement est un score de coordination : nombre de termes DISTINCTS trouvés
# d'abord, occurrences ensuite (`services.selection.relevance`). Pas d'IDF, pas de
# normalisation par longueur — inutiles à cette échelle, et un score qu'on peut
# lire à l'œil vaut mieux ici qu'un BM25 qu'on ne saurait pas déboguer.
#
# Ce score ne décide pas seul : il devient un POIDS DE TIRAGE (cf. `search_user_db`),
# pour que reposer la même question ne rende pas exactement les mêmes extraits.
from __future__ import annotations

import logging
import re

from config.settings import (
    BRAINSTORM_CITED_FLOOR,
    BRAINSTORM_PER_TYPE_CAP,
    BRAINSTORM_RECENCY_FLOOR,
    BRAINSTORM_RECENCY_HALF_LIFE_DAYS,
    BRAINSTORM_RELEVANCE_BASE,
)
from db import get_connection
from db.user import DEFAULT_USER_ID
from services import selection
from utils.text import fold

logger = logging.getLogger("services.brainstorm_search")

# Mots vides FR/EN à ignorer pour ne pas matcher sur du bruit.
_STOPWORDS = {
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "que", "qui",
    "quoi", "pour", "par", "sur", "dans", "avec", "sans", "est", "sont", "ce",
    "cette", "ces", "son", "sa", "ses", "mon", "ma", "mes", "ton", "ta", "tes",
    "il", "elle", "on", "nous", "vous", "ils", "comme", "plus", "moins", "the",
    "and", "or", "for", "with", "this", "that", "these", "those", "what", "how",
    "about", "idea", "idee", "idees", "brainstorm", "brainstorming",
    # Mots de question et de recherche : « quelle est la meilleure … », « cherche
    # dans tout l'article » ne disent rien du SUJET, ils ne doivent pas peser.
    "quel", "quelle", "quels", "quelles", "comment", "pourquoi", "combien",
    "est-ce", "peux", "peut", "cherche", "chercher", "trouve", "trouver",
    "regarde", "tout", "toute", "tous", "toutes", "article", "document",
    "papier", "texte", "page", "pages", "dit", "dis", "explique", "meilleur",
    "meilleure", "meilleurs", "meilleures", "which", "where", "when", "does",
    "can", "could", "would", "search", "find", "look", "whole", "entire",
    "paper", "says", "say", "tell", "explain", "best", "according",
    # Verbes et mots-outils fréquents dans une question (« combien de runs ont
    # divergé », « how many seeds were used ») : aucun poids non plus.
    "ont", "etre", "avoir", "fait", "faire", "aussi", "donc", "ainsi", "entre",
    "vers", "chez", "leur", "leurs", "notre", "votre", "cela", "ceci", "celui",
    "celle", "ceux", "celles", "utilise", "utilisee", "utilises", "utilisees",
    "utilisent", "utiliser", "utilisation", "quand", "sinon", "encore", "puis",
    "many", "much", "were", "was", "been", "being", "are", "have", "has",
    "had", "used", "use", "uses", "using", "why", "who", "whom", "there",
    "here", "then", "than", "also", "into", "from", "some", "such", "only",
    "very", "just", "its", "their", "they", "them", "our", "your", "you",
    "will", "should", "did", "done", "make", "made", "get", "got", "mean",
    "means", "meant",
}

_MAX_SNIPPET = 280
# Lot chargé par source avant filtrage Python (base locale -> volumes faibles).
#
# ÉCHANTILLON, et non « les 400 plus récents » : `ORDER BY id DESC` faisait de ce
# plafond une fenêtre de récence, si bien qu'au-delà de 400 lignes le vieux
# matériel devenait définitivement introuvable — le défaut même que la sélection
# corrige un cran plus haut. Un tirage uniforme est sans biais (une ligne
# pertinente n'a aucune raison d'être récente) et fait tourner le vivier d'un tour
# à l'autre ; la préférence pour le récent est réintroduite, bornée, par le
# facteur de fraîcheur du poids.
_CANDIDATE_POOL = 400


# Repli d'accents : implémentation unique dans utils.text, réexportée ici parce
# que services.pdf_rag importe `_fold` depuis ce module.
_fold = fold


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


def source_key(item: dict) -> tuple:
    """Identité stable d'un extrait, pour reconnaître une source DÉJÀ CITÉE.

    Les extraits archivés avec les anciens messages (`brainstorm_messages.sources_json`)
    ne portent pas d'id de ligne : la clé se compose donc de champs que le
    stockage conserve tels quels, `snippet` compris (sa troncature est
    déterministe, cf. :func:`_truncate`).
    """
    return (
        item.get("source_type"),
        item.get("doc_id"),
        item.get("page"),
        item.get("snippet"),
    )


def search_user_db(
    query: str,
    limit: int = 6,
    user_id: int = DEFAULT_USER_ID,
    damp_keys: set | None = None,
) -> list[dict]:
    """Cherche dans la base de l'utilisateur. Renvoie des extraits normalisés.

    Chaque extrait : {source_type, snippet, doc_id?, doc_title?, page?}.
    Best-effort : toute source qui échoue est simplement ignorée.

    **Ce n'est plus « les 3 plus récents de chaque table ».** Chaque source rend
    TOUS ses matchs, on les pèse ensemble (pertinence × fraîcheur × amortissement
    des extraits déjà cités), on tire dedans, puis on répartit entre types de
    source. Trois défauts disparaissent d'un coup :

    - la concaténation à ordre fixe servait toujours « 3 surlignages + 3
      flashcards », si bien qu'une ancienne Q&R ou un document n'était jamais cité ;
    - garder les premiers dans l'ordre des id revenait à ne citer que le matériel
      le plus récent, et à rendre la MÊME liste à chaque fois qu'une question était
      reposée ;
    - rien n'empêchait de re-citer, tour après tour, les extraits déjà servis.

    ``damp_keys`` (cf. :func:`source_key`) porte ce dernier point : une source
    déjà citée dans la discussion voit son poids fondre sans être exclue — elle
    reste citable si elle est vraiment la seule pertinente.
    """
    terms = extract_terms(query)
    if not terms or limit <= 0:
        return []
    candidates: list[dict] = []
    candidates.extend(_search_highlights(terms, user_id))
    candidates.extend(_search_flashcards(terms, user_id))
    candidates.extend(_search_questions(terms))
    candidates.extend(_search_documents(terms))
    if not candidates:
        return []

    damp = damp_keys or set()
    weights = []
    for item in candidates:
        distinct, total = item.pop("_hits", (1, 1))
        # Pertinence d'abord, et de loin : la pente est exponentielle en nombre de
        # termes DISTINCTS trouvés, les occurrences ne servant qu'à départager.
        # Fraîcheur ensuite, et bornée : un surlignage d'il y a six mois reste
        # citable s'il répond mieux que celui d'hier.
        weight = (BRAINSTORM_RELEVANCE_BASE ** distinct) * (1.0 + 0.1 * min(total, 10)) * max(
            BRAINSTORM_RECENCY_FLOOR,
            selection.decay(item.pop("_age_days", None), BRAINSTORM_RECENCY_HALF_LIFE_DAYS),
        )
        if source_key(item) in damp:
            weight *= BRAINSTORM_CITED_FLOOR
        weights.append(weight)

    # Tirage sur TOUT le vivier (donc un ordre qui varie d'un tour à l'autre),
    # puis tour de rôle entre types de source sous plafond.
    ordered = selection.weighted_sample(candidates, weights, len(candidates))
    return selection.diversified_take(
        ordered,
        key_fn=lambda item: item.get("source_type"),
        per_key_cap=BRAINSTORM_PER_TYPE_CAP,
        total=limit,
    )


def _truncate(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= _MAX_SNIPPET else text[: _MAX_SNIPPET - 1] + "…"


def _scored(text: str, terms: list[str]) -> tuple[int, int] | None:
    """``(distincts, total)`` si le texte touche la requête, ``None`` sinon.

    Remplace le booléen `_matches` : la sélection a besoin de savoir À QUEL POINT
    une ligne répond, pas seulement qu'elle répond — sans quoi il ne reste que
    l'ordre des id pour départager, c'est-à-dire la récence.
    """
    distinct, total = selection.relevance(_fold(text), terms)
    return (distinct, total) if distinct else None


def _search_highlights(terms: list[str], user_id: int) -> list[dict]:
    try:
        conn = get_connection()
        rows = conn.execute(
            """SELECT h.quote, h.page, h.document_id, h.created_at, d.filename AS doc_title
               FROM reader_highlights h
               LEFT JOIN documents d ON d.id = h.document_id
               WHERE h.user_id=?
               ORDER BY RANDOM() LIMIT ?""",
            (user_id, _CANDIDATE_POOL),
        ).fetchall()
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Recherche surlignages échouée : %s", exc)
        return []
    out = []
    for r in rows:
        hits = _scored(r["quote"] or "", terms)
        if hits is None:
            continue
        out.append({
            "source_type": "highlight",
            "doc_id": r["document_id"],
            "doc_title": r["doc_title"],
            "page": r["page"],
            "snippet": _truncate(r["quote"] or ""),
            "_hits": hits,
            "_age_days": selection.age_days(r["created_at"]),
        })
    return out


def _search_questions(terms: list[str]) -> list[dict]:
    try:
        conn = get_connection()
        rows = conn.execute(
            """SELECT q.question, q.answer, q.page_start, q.document_id, q.created_at,
                      d.filename AS doc_title
               FROM questions q
               LEFT JOIN documents d ON d.id = q.document_id
               WHERE q.scope_type IN ('assistant_follow_up', 'qa_follow_up')
               ORDER BY RANDOM() LIMIT ?""",
            (_CANDIDATE_POOL,),
        ).fetchall()
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Recherche Q&R échouée : %s", exc)
        return []
    out = []
    for r in rows:
        q = (r["question"] or "").strip()
        a = (r["answer"] or "").strip()
        hits = _scored(f"{q} {a}", terms)
        if hits is None:
            continue
        out.append({
            "source_type": "qa",
            "doc_id": r["document_id"],
            "doc_title": r["doc_title"],
            "page": r["page_start"],
            "snippet": _truncate(f"Q : {q} — R : {a}"),
            "_hits": hits,
            "_age_days": selection.age_days(r["created_at"]),
        })
    return out


def _search_flashcards(terms: list[str], user_id: int) -> list[dict]:
    try:
        conn = get_connection()
        rows = conn.execute(
            """SELECT f.front, f.back, f.tags, f.document_id, f.created_at,
                      d.filename AS doc_title
               FROM flashcards f
               LEFT JOIN documents d ON d.id = f.document_id
               WHERE f.user_id=?
               ORDER BY RANDOM() LIMIT ?""",
            (user_id, _CANDIDATE_POOL),
        ).fetchall()
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Recherche flashcards échouée : %s", exc)
        return []
    out = []
    for r in rows:
        front = (r["front"] or "").strip()
        back = (r["back"] or "").strip()
        hits = _scored(f"{front} {back} {r['tags'] or ''}", terms)
        if hits is None:
            continue
        out.append({
            "source_type": "flashcard",
            "doc_id": r["document_id"],
            "doc_title": r["doc_title"],
            "page": None,
            "snippet": _truncate(f"{front} → {back}"),
            "_hits": hits,
            "_age_days": selection.age_days(r["created_at"]),
        })
    return out


def _search_documents(terms: list[str]) -> list[dict]:
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, filename, last_opened FROM documents ORDER BY RANDOM() LIMIT ?",
            (_CANDIDATE_POOL,),
        ).fetchall()
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Recherche documents échouée : %s", exc)
        return []
    out = []
    for r in rows:
        hits = _scored(r["filename"] or "", terms)
        if hits is None:
            continue
        out.append({
            "source_type": "document",
            "doc_id": r["id"],
            "doc_title": r["filename"],
            "page": None,
            "snippet": _truncate(f"Document importé : {r['filename']}"),
            "_hits": hits,
            "_age_days": selection.age_days(r["last_opened"]),
        })
    return out
