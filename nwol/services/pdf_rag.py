# services/pdf_rag.py — Récupération de passages pertinents dans le document lu.
#
# Quand l'étudiant pose une question à la bulle Gemma, le contexte LLM ne contient
# que la page visible. Ce module fournit un RAG léger sur le MÊME document : on
# indexe le texte PDFium de toutes les pages, puis on renvoie les quelques
# passages (hors page courante) qui répondent le mieux aux mots-clés de la
# question — une table p.5 quand on lit la p.1, une définition du chapitre 2, etc.
#
# Recherche HYBRIDE, deux classements fusionnés par rangs réciproques (RRF) :
#
# - lexical : BM25 allégé en Python (IDF + saturation de fréquence +
#   normalisation par longueur) sur le texte plié, comme
#   services/brainstorm_search.py. Un terme rare (« implementation ») pèse
#   plus qu'un terme présent dans la moitié des chunks (« reptile »). < 1 ms.
# - sémantique : cosinus entre l'embedding de la question et celui de chaque
#   chunk (OLLAMA_EMBED_MODEL, multilingue). C'est lui qui relie « taux
#   d'apprentissage » à « learning rate » ou « hyperparamètres » à la table des
#   « configurations », ce que le lexical ne peut pas. Les vecteurs des chunks
#   sont calculés une fois (à l'ouverture du lecteur, en tâche de fond) et
#   persistés (db/embeddings) ; une question coûte un embedding (~50 ms) et un
#   produit scalaire par chunk. Couche OPTIONNELLE : sans le modèle, ou Ollama
#   arrêté, la recherche reste lexicale — jamais d'erreur remontée.
#
# Les deux listes se complètent : le lexical est exact sur les noms propres,
# les sigles et les valeurs (« FOMAML », « 7.75×10−6 ») là où un embedding
# les lisse ; le sémantique franchit la langue et les synonymes.
#
# La page visible a toujours la priorité. La profondeur de la recherche en
# dépend : si la page contient déjà les mots-clés de la question, les passages
# ne sont qu'un complément (peu nombreux) ; si elle ne les contient pas, la
# réponse est probablement ailleurs et la recherche s'élargit comme sur une
# demande explicite (« cherche dans tout l'article »). L'étudiant écrit souvent
# en français sur un document anglais, avec des fautes de frappe : un terme qui
# ne matche rien est rapproché du vocabulaire du document (distance d'édition
# bornée) avant d'être abandonné.
#
# Index gardé en mémoire (backend mono-process, long-vivant), invalidé par le
# mtime du fichier comme `library.page_text`, et pré-chauffé à l'ouverture du
# lecteur (`warm_index`). Best-effort : toute erreur dégrade vers « aucun
# passage » sans jamais casser la réponse de l'assistant.
from __future__ import annotations

import hashlib
import logging
import math
import operator
import os
import re
import threading
import time
from array import array
from collections import Counter

from config.settings import (
    ASSISTANT_RAG_CHUNK_CHARS,
    ASSISTANT_RAG_EMBED_BATCH,
    ASSISTANT_RAG_EMBED_RETRY_S,
    ASSISTANT_RAG_HISTORY_WEIGHT,
    ASSISTANT_RAG_MAX_CHARS,
    ASSISTANT_RAG_MIN_SIMILARITY,
    ASSISTANT_RAG_PAGE_COVERAGE,
    ASSISTANT_RAG_RRF_K,
    ASSISTANT_RAG_SEARCH_TOP_K,
    ASSISTANT_RAG_SYNONYM_WEIGHT,
    ASSISTANT_RAG_TABLE_CHUNK_CHARS,
    ASSISTANT_RAG_TOP_K,
    OLLAMA_EMBED_MODEL,
)
from db import embeddings as embeddings_db
from db.documents import get_document
from llm.ollama_client import embed_texts
from pdf_viewer.pdf_document import PdfDocument
from services.brainstorm_search import _fold, extract_terms
from services.rag_lexicon import synonyms, translations

logger = logging.getLogger("services.pdf_rag")

__all__ = [
    "retrieve", "rank_chunks", "resolve_terms", "expand_terms", "page_coverage",
    "fuse_rankings", "clear_index", "warm_index", "is_search_request",
    "semantic_available",
]

# Index par document : {doc_id: {"chunks", "vocab", "n", "avg_len", "mtime",
# "vectors"}}. Chaque chunk : {"page", "text", "folded", "len", "table"} ;
# `vocab` compte, pour chaque mot plié du document, le nombre de chunks qui le
# contiennent ; `vectors` (None tant que non calculés) aligne sur `chunks` un
# embedding normalisé par chunk.
_INDEX_CACHE: dict[int, dict] = {}

# Couche sémantique. EmbeddingGemma est entraîné avec des préfixes de tâche qui
# orientent le vecteur (une question d'un côté, un passage de l'autre) : les
# omettre dégrade nettement le classement.
_EMBED_QUERY_PREFIX = "task: search result | query: "
_EMBED_DOC_PREFIX = "title: none | text: "
# Après un échec (modèle absent, Ollama arrêté), pas de nouvel essai avant
# `retry_at` (horloge monotone) : une question ne doit pas payer un timeout.
_EMBED_STATE = {"retry_at": 0.0, "failure": ""}
# Documents dont les vecteurs sont en cours de calcul (indexation de fond) : une
# question posée pendant ce temps reste lexicale plutôt que de refaire le travail.
_EMBEDDING_IN_PROGRESS: set[int] = set()
_EMBED_LOCK = threading.Lock()
# Au-delà de ce nombre de chunks, une question posée AVANT la fin de
# l'indexation de fond n'attend pas les vecteurs (un livre : une minute) ; en
# deçà (un article : une seconde), elle les calcule elle-même.
_EMBED_SYNC_MAX_CHUNKS = 200
# Candidats retenus de chaque classement avant la fusion : au-delà, un rang
# n'apporte plus qu'un bruit de 1/(K+rang).
_FUSION_CANDIDATES = 20

# Pages ouvertes par prise de PDFIUM_LOCK. Le verrou est tenu pendant toute la
# vie d'un `PdfDocument` : indexer un livre de 300 pages d'un seul tenant
# bloquerait le rendu des pages pendant plusieurs secondes. Par lots, un rendu
# demandé pendant l'indexation n'attend jamais plus d'un lot.
_INDEX_BATCH_PAGES = 25

# BM25 : k1 sature la fréquence d'un terme dans un chunk, b dose la pénalité
# des chunks longs (0.5 : les tables, gardées entières, ne sont pas écrasées).
_BM25_K1 = 1.2
_BM25_B = 0.5
# En-tête d'un chunk : un terme qui s'y trouve dit de quoi parle le passage et
# pèse une occurrence de plus. Pour la prose, ce sont ses premiers caractères
# (l'attaque du paragraphe) ; pour une table, sa LÉGENDE entière (titre +
# description, cf. `head` du chunk).
_HEAD_CHARS = 150
# Prior structurel des tables légendées (« TABLE I … ») : une table est une
# réponse dense et autoportante (valeurs, configurations, comparaisons) que le
# BM25 sous-classe par construction — chaque fait n'y figure qu'une fois, là où
# la prose répète son sujet, et la saturation de fréquence plafonne ce qu'une
# légende peut rattraper. Sans ce facteur, un paragraphe qui cite trois fois
# « Reptile » passe toujours devant la table des configurations de Reptile.
# Un bloc chiffré sans légende (bibliographie, équations) n'en bénéficie pas.
_TABLE_BOOST = 1.5
# Même prior côté sémantique, additif sur le cosinus : un embedding lisse
# les chiffres et les majuscules d'une table, qui ressort donc moins
# « similaire » que la prose qui la commente. Mesuré sur un article : +0.05
# ramène la table des configurations dans les 6 premiers sans déplacer les
# réponses en prose ; +0.10 commence à les évincer.
_TABLE_SIMILARITY_BONUS = 0.05
# Passages max par page dans un résultat : la recherche doit couvrir le
# document, pas rendre quatre paragraphes voisins de la même page — sans pour
# autant évincer la seconde table d'une page de protocole expérimental.
_MAX_PER_PAGE = 3

# Longueur minimale d'un terme pour qu'on le tronque en radical (cf. _stem).
_STEM_MIN_LEN = 7

# Rapprochement d'un terme introuvable du vocabulaire du document (cf.
# resolve_terms) : en dessous de cette longueur, une faute près, tout se
# ressemble (« coute » / « conte(xt) ») — le terme est abandonné tel quel.
_FUZZY_MIN_LEN = 6
# Distance d'édition tolérée (Damerau-Levenshtein) : une faute jusqu'à 7
# caractères, deux au-delà (« aprametr » → « paramete », transposition +
# flexion FR/EN).
_FUZZY_MAX_EDITS_LONG = 2
_FUZZY_LONG_LEN = 8
# Mots du document retenus dans le vocabulaire (les plus courts ne se prêtent
# pas au rapprochement).
_VOCAB_WORD = re.compile(r"[a-z][a-z0-9]{3,}")

# Formulations qui demandent explicitement une recherche hors de la page visible.
# Ancrées en début de mot : « la recherche montre… » ou « researchers » ne sont
# pas des demandes de recherche.
_SEARCH_CUES = re.compile(
    r"\bcherch|dans tout|tout l['’ ]?article|tout le document|tout le papier|ailleurs"
    r"|whole (document|paper|article)|entire (document|paper|article)|\bsearch"
    r"|look in|rest of the",
    re.IGNORECASE,
)

# Fin de phrase : ponctuation forte suivie d'un blanc ou d'un retour à la ligne.
_SENTENCE_END = re.compile(r"(?<=[.!?:])\s+")

# Ligne de table : courte, et dense en chiffres/symboles de mesure. Le texte
# PDFium d'une table rend chaque rangée sur sa propre ligne (« Outer step (ε, β)
# 0.335 7.75×10−6 7.75×10−6 »), une ligne de prose en contient rarement autant.
_TABLE_CHARS = re.compile(r"[0-9±×%/−\-–.]")
_TABLE_LINE_MAX_LEN = 90
_TABLE_LINE_MIN_DENSITY = 0.18
_NUMERIC_TOKEN = re.compile(r"[\d.,%±×−\-/]*\d[\d.,%±×−\-/]*")
_TABLE_LINE_MIN_NUMERIC = 2
_UNTITLED_TABLE_MIN_ROWS = 3
_TABLE_TITLE = re.compile(r"^\s*(TABLE|TABLEAU)\s+[IVXLC0-9]+\b", re.IGNORECASE)
# Lignes de légende tolérées entre un titre « TABLE I » et sa première rangée ;
# au-delà, ce n'était pas une table et tout repart en prose.
_TABLE_CAPTION_MAX_LINES = 8
# Lignes non chiffrées tolérées ENTRE deux rangées (libellés de groupe).
_TABLE_GAP_MAX_LINES = 2
# Un bloc de prose plus court que ça (numéro de page…) est fondu dans le suivant.
_TINY_BLOCK_CHARS = 40


# Rendu d'une table pour le LLM : jusqu'à ce nombre de colonnes, une rangée
# « Outer step (ε, β) 0.335 7.75×10−6 7.75×10−6 » sous l'en-tête « Reptile
# FOMAML MAML » devient « Outer step (ε, β): Reptile=0.335 · FOMAML=7.75×10−6 ·
# MAML=7.75×10−6 ». Un modèle 4B aligne mal les colonnes par position (mesuré :
# il attribuait à Reptile l'inner lr de FOMAML) ; nommées, il ne se trompe plus.
_TABLE_MAX_COLUMNS = 6
_CELL_JOINERS = ("±", "/", "×")


def _table_cells(line: str) -> list[str]:
    """Jetons d'une rangée, « 75.9 ± 26.0 » et « 5 / 20 » recollés en une cellule."""
    tokens = line.split()
    cells: list[str] = []
    for token in tokens:
        if cells and (token in _CELL_JOINERS or cells[-1].split()[-1] in _CELL_JOINERS):
            cells[-1] = f"{cells[-1]} {token}"
        else:
            cells.append(token)
    return cells


def _is_value_cell(cell: str) -> bool:
    return all(_NUMERIC_TOKEN.fullmatch(part) or part in _CELL_JOINERS for part in cell.split())


def _render_table(text: str) -> str:
    """Rangées d'une table avec leurs colonnes nommées quand un en-tête est
    identifiable (dernière ligne avant la première rangée chiffrée, 2 à
    _TABLE_MAX_COLUMNS mots, aucun numérique). Une rangée dont le nombre de
    valeurs ne correspond pas à l'en-tête est laissée telle quelle : mieux vaut
    une ligne brute qu'un mauvais alignement."""
    lines = [" ".join(ln.split()) for ln in text.splitlines() if ln.strip()]
    first_row = next((i for i, ln in enumerate(lines) if _is_table_line(ln, lenient=True)), None)
    if not first_row:
        return "\n".join(lines)
    header = lines[first_row - 1].split()
    if not (2 <= len(header) <= _TABLE_MAX_COLUMNS) or any(_is_value_cell(h) for h in header):
        return "\n".join(lines)
    rendered = lines[:first_row]
    for line in lines[first_row:]:
        cells = _table_cells(line)
        values: list[str] = []
        while cells and _is_value_cell(cells[-1]):
            values.insert(0, cells.pop())
        label = " ".join(cells)
        if label and len(values) == len(header):
            rendered.append(f"{label}: " + " · ".join(f"{h}={v}" for h, v in zip(header, values)))
        else:
            rendered.append(line)
    return "\n".join(rendered)


def _truncate(text: str, max_chars: int, keep_lines: bool = False) -> str:
    """Espaces normalisés ; `keep_lines` conserve les retours à la ligne (rangées
    d'une table : aplatie, « Outer step 0.335 7.75×10−6 Inner lr 5.75×10−4 … »
    devient illisible pour le LLM)."""
    if keep_lines:
        text = "\n".join(" ".join(ln.split()) for ln in (text or "").splitlines() if ln.strip())
    else:
        text = " ".join((text or "").split())
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def _mtime(path: str | None) -> float:
    try:
        return os.path.getmtime(str(path))
    except OSError:
        return 0.0


def _stem(term: str) -> str:
    """Radical grossier : « configurations » et « configuration », « implémentation »
    et « implementation » doivent se rejoindre. On tronque la fin des mots longs
    (les flexions FR/EN sont en fin de mot) ; les mots courts restent entiers, une
    troncature les rendrait ambigus — et un mot de 7-8 lettres ne perd qu'un ou
    deux caractères (« interne » → « intern », pas « inter » qui matcherait
    « intermediate »). Le matching est ensuite par SOUS-CHAÎNE."""
    if len(term) < _STEM_MIN_LEN:
        return term
    return term[: len(term) - min(3, len(term) - 6)]


def is_search_request(question: str) -> bool:
    """L'étudiant demande-t-il explicitement de chercher dans tout le document ?"""
    return bool(_SEARCH_CUES.search(question or ""))


# ── Découpage ────────────────────────────────────────────────────────────────

def _is_table_line(line: str, lenient: bool = False) -> bool:
    """Rangée chiffrée ? `lenient` (à l'intérieur d'une table titrée) accepte
    aussi une rangée à libellé long et valeurs courtes (« Meta-gradient clipping
    none 5 5 ») — critère trop lâche pour la prose d'un article plein de chiffres,
    d'où sa restriction aux tables déjà ouvertes par un titre « TABLE n »."""
    stripped = line.strip()
    if not stripped or len(stripped) > _TABLE_LINE_MAX_LEN:
        return False
    density = len(_TABLE_CHARS.findall(stripped)) / len(stripped)
    if density >= _TABLE_LINE_MIN_DENSITY:
        return True
    if not lenient:
        return False
    numeric = sum(1 for tok in stripped.split() if _NUMERIC_TOKEN.fullmatch(tok.strip("(),;:")))
    return numeric >= _TABLE_LINE_MIN_NUMERIC


def _split_blocks(text: str) -> list[tuple[str, bool]]:
    """Regroupe les lignes en blocs (texte, est_table).

    PDFium ne rend PAS de ligne vide entre paragraphes : une page est une suite
    de lignes. On isole les suites de lignes tabulaires (avec leur ligne de titre
    « TABLE I … » qui précède) pour les garder entières ; tout le reste est de la
    prose, recollée en un seul bloc que le découpage par phrases traitera.
    """
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    blocks: list[tuple[str, bool]] = []
    prose: list[str] = []
    table: list[str] = []
    rows = 0  # rangées chiffrées vues dans `table` (le titre et la légende n'en sont pas)

    def flush_prose() -> None:
        if prose:
            blocks.append((" ".join(prose), False))
            prose.clear()

    def flush_table() -> None:
        nonlocal rows
        # Sans titre, il faut plusieurs rangées denses : deux lignes chiffrées
        # (une équation, un numéro de page) ne font pas une table. Un titre
        # sans aucune rangée n'est qu'une légende : prose.
        if rows >= _UNTITLED_TABLE_MIN_ROWS or (rows and _TABLE_TITLE.match(table[0])):
            flush_prose()
            blocks.append(("\n".join(table), True))
        else:
            prose.extend(table)
        table.clear()
        rows = 0

    # Lignes non chiffrées au milieu d'une table (libellé de groupe sur deux
    # lignes, « Conventional† » / « {liver, spleen, kidneys} ») : gardées en
    # attente ; la table continue si une rangée chiffrée suit, sinon elle se
    # termine AVANT ces lignes, qui repartent en prose.
    pending: list[str] = []

    def close_table() -> None:
        # Termine la table en cours AVANT les lignes en attente (qui sont de la prose).
        if table:
            flush_table()
        prose.extend(pending)
        pending.clear()

    for line in lines:
        if not line.strip():
            continue
        if _TABLE_TITLE.match(line):
            # Le titre d'une table ouvre un bloc tabulaire : on le tient en
            # réserve avec sa légende et les rangées qui suivent.
            close_table()
            flush_prose()
            table.append(line)
            continue
        titled = bool(table) and bool(_TABLE_TITLE.match(table[0]))
        if _is_table_line(line, lenient=titled):
            table.extend(pending)
            pending.clear()
            table.append(line)
            rows += 1
            continue
        if table and rows and len(pending) < _TABLE_GAP_MAX_LINES:
            pending.append(line)
            continue
        if table and not rows and len(table) < _TABLE_CAPTION_MAX_LINES:
            table.append(line)  # légende entre le titre et les rangées
            continue
        close_table()
        prose.append(line)
    close_table()
    flush_prose()
    return _merge_tiny_blocks(blocks)


def _merge_tiny_blocks(blocks: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    """Absorbe les blocs minuscules (numéro de page, ligne orpheline) dans la
    prose voisine — un chunk d'un caractère ne sert à rien et fausse la longueur
    moyenne du BM25. Jamais dans une table : un « 5 » collé devant « TABLE I »
    en cacherait le titre (cf. _caption_chars) ; il rejoint le bloc précédent
    ou, en tête de page, disparaît (le texte de page du LLM le garde)."""
    merged: list[tuple[str, bool]] = []
    carry = ""
    for text, is_table in blocks:
        if carry and is_table:
            if merged:
                previous, previous_is_table = merged[-1]
                merged[-1] = (f"{previous}\n{carry}" if previous_is_table else f"{previous} {carry}", previous_is_table)
            carry = ""
        elif carry:
            text, carry = f"{carry} {text}", ""
        if len(text) < _TINY_BLOCK_CHARS and not is_table:
            carry = text
            continue
        merged.append((text, is_table))
    if carry:
        if merged:
            text, is_table = merged[-1]
            merged[-1] = (f"{text}\n{carry}" if is_table else f"{text} {carry}", is_table)
        else:
            merged.append((carry, False))
    return merged


def _pack_sentences(sentences: list[str], max_chars: int, sep: str = " ") -> list[str]:
    """Empaquette des phrases en chunks ≤ max_chars, avec un recouvrement d'une
    phrase pour qu'une idée à cheval sur deux chunks reste trouvable. `sep`
    vaut "\n" pour des rangées de table (structure conservée jusqu'au prompt)."""
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for sentence in sentences:
        # Une phrase géante (liste sans ponctuation) est tranchée sur un blanc.
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            head, sentence = sentence[:cut].strip(), sentence[cut:].strip()
            if buf:
                chunks.append(sep.join(buf))
                buf, size = [], 0
            chunks.append(head)
        if not sentence:
            continue
        if buf and size + 1 + len(sentence) > max_chars:
            chunks.append(sep.join(buf))
            last = buf[-1]
            buf, size = [last], len(last)
            if size + 1 + len(sentence) > max_chars:
                buf, size = [], 0
        buf.append(sentence)
        size += len(sentence) + (1 if size else 0)
    if buf:
        joined = sep.join(buf)
        # Un reliquat qui n'est que le recouvrement du chunk précédent n'apporte rien.
        if not chunks or joined not in chunks[-1]:
            chunks.append(joined)
    return chunks


def _chunk_page_text(text: str) -> list[str]:
    """Découpe le texte brut d'une page en passages citables → [(texte, est_table)].

    Prose : phrases entières empaquetées jusqu'à ASSISTANT_RAG_CHUNK_CHARS avec
    recouvrement d'une phrase. Tables : gardées entières (jusqu'à
    ASSISTANT_RAG_TABLE_CHUNK_CHARS), sinon tranchées par rangées.
    """
    chunks: list[tuple[str, bool]] = []
    for block, is_table in _split_blocks(text):
        if is_table:
            rows = [" ".join(r.split()) for r in block.splitlines()]
            chunks.extend((c, True) for c in _pack_sentences(rows, ASSISTANT_RAG_TABLE_CHUNK_CHARS, sep="\n"))
        else:
            sentences = [" ".join(s.split()) for s in _SENTENCE_END.split(block)]
            chunks.extend((c, False) for c in _pack_sentences([s for s in sentences if s], ASSISTANT_RAG_CHUNK_CHARS))
    return [(c, t) for (c, t) in chunks if c.strip()]


# ── Index ────────────────────────────────────────────────────────────────────

def _make_chunk(page: int, text: str, is_table: bool = False) -> dict:
    folded = _fold(text)
    chunk = {"page": page, "text": text, "folded": folded, "len": len(folded), "table": is_table}
    if is_table:
        chunk["head"] = _caption_chars(text)
    return chunk


def _caption_chars(table_text: str) -> int:
    """Longueur de la légende d'une table titrée (« TABLE I » + description,
    avant la première rangée chiffrée). 0 pour un bloc chiffré sans titre ou
    une tranche de table sans légende : ni en-tête, ni prior de table."""
    lines = table_text.splitlines()
    if not lines or not _TABLE_TITLE.match(lines[0]):
        return 0
    caption = 0
    for line in lines:
        if _is_table_line(line, lenient=True):
            break
        caption += len(line) + 1
    return caption


def _page_texts(doc: dict) -> list[tuple[int, str]]:
    """(page, texte) pour tout le document, par lots pour relâcher PDFIUM_LOCK."""
    if doc.get("extraction_engine") == "code":
        # Fichier de code : pas de PDF à ouvrir, le texte vient des pages
        # découpées par services/code_reader.
        from services.library import page_text as _page_text

        return [(p, _page_text(int(doc["id"]), p)) for p in range(1, int(doc.get("page_count") or 0) + 1)]
    texts: list[tuple[int, str]] = []
    with PdfDocument(doc["path"]) as pdf:
        page_count = pdf.page_count()
    for start in range(1, page_count + 1, _INDEX_BATCH_PAGES):
        with PdfDocument(doc["path"]) as pdf:
            for page in range(start, min(start + _INDEX_BATCH_PAGES, page_count + 1)):
                texts.append((page, pdf.raw_text(page)))
    return texts


def _build_index(doc_id: int) -> dict | None:
    """Index mémoire du document (chunks + fréquences documentaires). Best-effort.

    Un index vide légitime (PDF sans texte extractible) est mis en cache ; une
    erreur transitoire renvoie None SANS cacher, pour réessayer au prochain appel.
    """
    try:
        doc = get_document(doc_id)
        if not doc or not doc.get("path"):
            return None
        mtime = _mtime(doc.get("path"))
        cached = _INDEX_CACHE.get(doc_id)
        if cached is not None and cached.get("mtime") == mtime:
            return cached
        doc = dict(doc, id=doc_id)
        chunks = [
            _make_chunk(page, piece, is_table)
            for page, text in _page_texts(doc)
            for piece, is_table in _chunk_page_text(text)
        ]
    except Exception as exc:  # pragma: no cover - défensif
        logger.debug("Index RAG doc %s échoué : %s", doc_id, exc)
        return None
    n = len(chunks)
    index = {
        "chunks": chunks,
        "vocab": _vocabulary(chunks),
        "n": n,
        "avg_len": (sum(c["len"] for c in chunks) / n) if n else 1.0,
        "mtime": mtime,
        "vectors": None,
    }
    _INDEX_CACHE[doc_id] = index
    return index


def _vocabulary(chunks: list[dict]) -> Counter:
    """Mots pliés du document → nombre de chunks qui les contiennent."""
    vocab: Counter = Counter()
    for chunk in chunks:
        vocab.update(set(_VOCAB_WORD.findall(chunk.get("folded") or "")))
    return vocab


def warm_index(doc_id: int) -> None:
    """Pré-construit l'index (à l'ouverture du lecteur) pour que la première
    question ne paie ni l'extraction du texte ni l'embedding des passages.
    Silencieux ; à appeler hors de la boucle asyncio (executor)."""
    index = _build_index(doc_id)
    if index and index["chunks"]:
        _ensure_vectors(doc_id, index)


# ── Couche sémantique ────────────────────────────────────────────────────────

def semantic_available() -> bool:
    """La couche sémantique a-t-elle répondu (ou n'a-t-elle pas encore échoué) ?"""
    return time.monotonic() >= _EMBED_STATE["retry_at"]


def _normalize(vector) -> array:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return array("f", [x / norm for x in vector])


def _cosine(a: array, b: array) -> float:
    # Vecteurs normalisés : le produit scalaire est le cosinus. `sum(map(mul))`
    # tient en ~25 µs pour 768 dimensions — assez pour des milliers de chunks
    # sans dépendance numérique.
    return sum(map(operator.mul, a, b))


def _embed(texts: list[str]) -> list[array] | None:
    """Embeddings normalisés, ou None si la couche sémantique est indisponible
    (l'échec est mémorisé ASSISTANT_RAG_EMBED_RETRY_S secondes)."""
    if not texts or not semantic_available():
        return None
    try:
        raw = embed_texts(texts)
    except Exception as exc:
        _EMBED_STATE["retry_at"] = time.monotonic() + ASSISTANT_RAG_EMBED_RETRY_S
        _EMBED_STATE["failure"] = str(exc)
        logger.info(
            "Recherche sémantique indisponible (%s) : lexical seul pendant %s s",
            exc, ASSISTANT_RAG_EMBED_RETRY_S,
        )
        return None
    return [_normalize(v) for v in raw]


def _chunk_hash(chunks: list[dict]) -> str:
    digest = hashlib.sha1()
    for chunk in chunks:
        digest.update(chunk["text"].encode("utf-8", "replace"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _ensure_vectors(doc_id: int, index: dict, *, sync_max: int | None = None) -> None:
    """Attache à l'index les vecteurs de ses chunks : depuis la base si le
    fichier, le découpage et le modèle n'ont pas changé, sinon calculés par
    lots et persistés. `sync_max` : au-delà de ce nombre de chunks, on ne
    calcule pas (une question n'attend pas l'indexation d'un livre) — la tâche
    de fond, sans limite, s'en charge. Un seul calcul à la fois par document."""
    if index.get("vectors") is not None or not semantic_available():
        return
    chunks = index["chunks"]
    chunk_hash = _chunk_hash(chunks)
    try:
        stored = embeddings_db.load_vectors(doc_id, index["mtime"], OLLAMA_EMBED_MODEL, chunk_hash)
    except Exception as exc:  # pragma: no cover - défensif
        logger.debug("Lecture des embeddings doc %s échouée : %s", doc_id, exc)
        stored = None
    if stored is not None and len(stored) == len(chunks):
        index["vectors"] = stored
        return
    if sync_max is not None and len(chunks) > sync_max:
        return
    with _EMBED_LOCK:
        if doc_id in _EMBEDDING_IN_PROGRESS:
            return
        _EMBEDDING_IN_PROGRESS.add(doc_id)
    try:
        started = time.monotonic()
        vectors: list[array] = []
        for start in range(0, len(chunks), ASSISTANT_RAG_EMBED_BATCH):
            batch = _embed([_EMBED_DOC_PREFIX + c["text"] for c in chunks[start:start + ASSISTANT_RAG_EMBED_BATCH]])
            if batch is None:
                return
            vectors.extend(batch)
        index["vectors"] = vectors
        logger.info(
            "Embeddings doc %s : %s chunks en %.1f s", doc_id, len(vectors), time.monotonic() - started,
        )
        try:
            embeddings_db.save_vectors(doc_id, index["mtime"], OLLAMA_EMBED_MODEL, chunk_hash, vectors)
        except Exception as exc:  # pragma: no cover - défensif
            logger.debug("Écriture des embeddings doc %s échouée : %s", doc_id, exc)
    finally:
        with _EMBED_LOCK:
            _EMBEDDING_IN_PROGRESS.discard(doc_id)


def _semantic_order(index: dict, query: str, current_page: int) -> list[dict]:
    """Chunks (hors page courante) par similarité décroissante à la question ;
    [] sans vecteurs ou sans embedding de la question."""
    vectors = index.get("vectors")
    if not vectors:
        return []
    embedded = _embed([_EMBED_QUERY_PREFIX + query])
    if not embedded:
        return []
    query_vector = embedded[0]
    scored = [
        (_cosine(query_vector, vector) + (_TABLE_SIMILARITY_BONUS if chunk.get("head") else 0.0), chunk)
        for chunk, vector in zip(index["chunks"], vectors)
        if chunk.get("page") != current_page
    ]
    scored.sort(key=lambda s: s[0], reverse=True)
    return [chunk for (score, chunk) in scored if score >= ASSISTANT_RAG_MIN_SIMILARITY]


def fuse_rankings(*rankings: list[dict], k: int = ASSISTANT_RAG_RRF_K) -> list[dict]:
    """Fusion par rangs réciproques : score(chunk) = Σ 1 / (k + rang dans chaque
    liste). Indifférente aux échelles des scores d'origine — c'est ce qui permet
    de marier un BM25 et un cosinus sans les calibrer. Un chunk présent dans
    une seule liste garde sa contribution ; à égalité, l'ordre de la première
    liste prévaut."""
    scores: dict[int, float] = {}
    order: dict[int, dict] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking[:_FUSION_CANDIDATES], 1):
            key = id(chunk)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            order.setdefault(key, chunk)
    return [order[key] for key in sorted(order, key=lambda key: scores[key], reverse=True)]


def clear_index(doc_id: int | None = None) -> None:
    """Purge l'index mémoire (un document, ou tout). Utile en test / réimport."""
    if doc_id is None:
        _INDEX_CACHE.clear()
    else:
        _INDEX_CACHE.pop(doc_id, None)


# ── Classement ───────────────────────────────────────────────────────────────

def _weighted(terms: list[str], weight: float) -> list[tuple[str, float]]:
    return [(t, weight) for t in terms]


def rank_chunks(
    chunks: list[dict],
    terms: list[str] | list[tuple[str, float]],
    current_page: int,
    top_k: int = ASSISTANT_RAG_TOP_K,
) -> list[dict]:
    """Classement lexical seul, diversifié et tronqué : `top_k` meilleurs
    passages au sens BM25-lite (cf. `_lexical_order`)."""
    return _diversify(_lexical_order(chunks, terms, current_page), top_k)


def _lexical_order(
    chunks: list[dict],
    terms: list[str] | list[tuple[str, float]],
    current_page: int,
) -> list[dict]:
    """Passages par score BM25-lite décroissant (termes pliés déjà fournis).

    `terms` : radicaux, ou couples (radical, poids). Score d'un chunk =
    Σ poids × idf(terme) × tf saturée, où l'idf est calculée sur `chunks` (un
    terme présent partout ne discrimine rien). Matching par sous-chaîne sur le
    texte plié. La page courante est exclue (déjà dans le contexte page visible).
    """
    weighted: list[tuple[str, float]] = [
        (t, 1.0) if isinstance(t, str) else (t[0], float(t[1])) for t in terms
    ]
    weighted = [(t, w) for (t, w) in weighted if t]
    if not weighted or not chunks:
        return []
    n = len(chunks)
    avg_len = sum(c.get("len") or len(c.get("folded") or "") for c in chunks) / n
    idf: dict[str, float] = {}
    for term, _w in weighted:
        if term in idf:
            continue
        df = sum(1 for c in chunks if term in (c.get("folded") or ""))
        idf[term] = math.log(1 + (n - df + 0.5) / (df + 0.5))

    scored: list[tuple[float, int, dict]] = []
    for chunk in chunks:
        if chunk.get("page") == current_page:
            continue
        folded = chunk.get("folded") or ""
        length = chunk.get("len") or len(folded)
        norm = _BM25_K1 * (1 - _BM25_B + _BM25_B * length / (avg_len or 1.0))
        caption = int(chunk.get("head") or 0) if chunk.get("table") else 0
        head = folded[: caption or _HEAD_CHARS]
        score = 0.0
        distinct = 0
        for term, weight in weighted:
            tf = folded.count(term)
            if not tf:
                continue
            distinct += 1
            # Un terme dans l'en-tête (légende de table, attaque de paragraphe)
            # dit de quoi parle le passage : il compte pour une occurrence de plus.
            if term in head:
                tf += 1
            score += weight * idf[term] * tf * (_BM25_K1 + 1) / (tf + norm)
        if distinct:
            scored.append((score * (_TABLE_BOOST if caption else 1.0), distinct, chunk))
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    return [chunk for (_score, _distinct, chunk) in scored]


def _diversify(ordered: list[dict], top_k: int) -> list[dict]:
    """Diversité : au plus _MAX_PER_PAGE passages par page, pour que le résultat
    couvre le document ; ceux écartés reviennent si les autres pages ne
    suffisent pas à remplir top_k."""
    kept: list[dict] = []
    overflow: list[dict] = []
    per_page: dict = {}
    for chunk in ordered:
        page = chunk.get("page")
        if per_page.get(page, 0) < _MAX_PER_PAGE:
            per_page[page] = per_page.get(page, 0) + 1
            kept.append(chunk)
        else:
            overflow.append(chunk)
        if len(kept) >= top_k:
            break
    return (kept + overflow)[:top_k]


def _edit_distance(a: str, b: str, limit: int) -> int:
    """Damerau-Levenshtein (alignement optimal), coupée dès que `limit` est dépassé."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            best = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                best = min(best, prev2[j - 2] + 1)
            cur.append(best)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


def _nearest_word(term: str, vocab: Counter) -> str | None:
    """Préfixe du mot du document le plus proche de `term`, ou None.

    Comparé sur les `len(term)` premiers caractères de chaque mot, puisque le
    matching est ensuite par sous-chaîne : « aprametr » se rapproche de
    « paramete(rs) », qui retrouvera aussi « hyperparameters ». À distance égale,
    le mot le plus répandu dans le document l'emporte."""
    if len(term) < _FUZZY_MIN_LEN:
        return None
    limit = _FUZZY_MAX_EDITS_LONG if len(term) >= _FUZZY_LONG_LEN else 1
    head = term[:2]
    best: tuple[int, int, str] | None = None
    for word, df in vocab.items():
        # Pré-filtre bon marché : une faute de frappe ne change pas les deux
        # premières lettres à la fois (une transposition les échange).
        if len(word) < len(term) - limit or (word[0] not in head and word[1] not in head):
            continue
        prefix = word[: len(term)]
        distance = _edit_distance(term, prefix, limit)
        if distance > limit:
            continue
        candidate = (distance, -df, prefix)
        if best is None or candidate < best:
            best = candidate
    return best[2] if best else None


def resolve_terms(
    terms: list[tuple[str, float]], chunks: list[dict], vocab: Counter | None = None,
) -> list[tuple[str, float]]:
    """Mots de la question → radicaux effectivement présents dans le document.

    Chaque mot est réduit à son radical (`_stem`). S'il n'apparaît nulle part,
    deux replis dans l'ordre : son équivalent dans l'autre langue
    (services/rag_lexicon : « taux » → « rate »), puis le mot du document le
    plus proche à une faute près (« aprametrage » → « paramete(rs) »). Un mot
    sans repli garde son radical : il ne pèsera rien dans le classement, mais
    ne compte pas non plus dans la couverture de la page."""
    if vocab is None:
        vocab = _vocabulary(chunks)

    def present(stem: str) -> bool:
        return any(stem in (c.get("folded") or "") for c in chunks)

    resolved: list[tuple[str, float]] = []
    seen: set[str] = set()
    for word, weight in terms:
        stem = _stem(word)
        if not present(stem):
            candidates = [_stem(t) for t in translations(word)]
            stem = next((c for c in candidates if present(c)), None) or _nearest_word(stem, vocab) or stem
        if stem not in seen:
            seen.add(stem)
            resolved.append((stem, weight))
    return resolved


def expand_terms(
    terms: list[tuple[str, float]], resolved: list[tuple[str, float]], chunks: list[dict],
) -> list[tuple[str, float]]:
    """Ajoute aux radicaux résolus les quasi-synonymes présents dans le document
    (services/rag_lexicon), à poids réduit : « hyperparamètres de Reptile »
    atteint aussi la table des « configurations », sans que le synonyme puisse
    supplanter le mot de l'étudiant. Ces expansions ne comptent pas dans la
    couverture de la page (cf. retrieve)."""
    expanded = list(resolved)
    for word, weight in terms:
        for synonym in synonyms(word):
            stem = _stem(synonym)
            # Un radical emboîté dans un radical déjà retenu (« parame » dans
            # « hyperparamet ») compterait les mêmes occurrences deux fois.
            if any(stem in kept or kept in stem for (kept, _w) in expanded):
                continue
            if any(stem in (c.get("folded") or "") for c in chunks):
                expanded.append((stem, weight * ASSISTANT_RAG_SYNONYM_WEIGHT))
    return expanded


def page_coverage(chunks: list[dict], terms: list[tuple[str, float]], current_page: int) -> float:
    """Part des termes de la question (parmi ceux présents dans le document)
    que la page visible contient déjà — 1.0 : la page parle du sujet, les
    passages ne sont qu'un complément ; 0.0 : la réponse est ailleurs."""
    present = [t for (t, _w) in terms if any(t in (c.get("folded") or "") for c in chunks)]
    if not present:
        return 0.0
    page = " ".join(c.get("folded") or "" for c in chunks if c.get("page") == current_page)
    return sum(1 for t in present if t in page) / len(present)


def _query_terms(question: str, recent_questions: list[str] | None) -> tuple[list[tuple[str, float]], bool]:
    """Mots-clés pondérés de la requête (pliés, non radicalisés : voir
    `resolve_terms`) + drapeau « recherche élargie ».

    Un suivi (« cherche dans tout l'article ») ou une question trop pauvre en
    mots-clés emprunte les termes des dernières questions, à poids réduit.
    """
    current = extract_terms(question)
    search = is_search_request(question)
    weighted = _weighted(current, 1.0)
    if search or len(current) < 2:
        seen = {t for (t, _w) in weighted}
        for previous in reversed(list(recent_questions or [])[-2:]):
            for term, weight in _weighted(extract_terms(previous), ASSISTANT_RAG_HISTORY_WEIGHT):
                if term not in seen:
                    seen.add(term)
                    weighted.append((term, weight))
    return weighted, search


def retrieve(
    doc_id: int,
    question: str,
    current_page: int,
    top_k: int | None = None,
    max_chars: int = ASSISTANT_RAG_MAX_CHARS,
    *,
    recent_questions: list[str] | None = None,
) -> list[dict]:
    """Passages du document pertinents pour la question → [{"page", "text", "table"}].

    Renvoie [] si aucun mot-clé exploitable ou aucun match (prompt inchangé).
    """
    index = _build_index(doc_id)
    if not index or not index["chunks"]:
        return []
    ranked, depth = _ranked_candidates(doc_id, index, question, current_page, recent_questions)
    chosen = _diversify(ranked, top_k if top_k is not None else depth)
    # Une ligne par question : de quoi juger la recherche depuis les logs sans
    # relire le prompt (pages citées, tables, profondeur, couche sémantique).
    logger.info(
        "RAG doc %s (page %s) : %s extrait(s) [%s] profondeur=%s sémantique=%s",
        doc_id, current_page, len(chosen),
        ", ".join(f"p.{c['page']}{'T' if c.get('table') else ''}" for c in chosen) or "-",
        depth, "oui" if index.get("vectors") else "non",
    )
    # Une table tronquée perd ses valeurs : elle garde son plafond propre.
    return [
        {
            "page": chunk["page"],
            "table": bool(chunk.get("table")),
            "text": _truncate(
                _render_table(chunk["text"]) if chunk.get("table") else chunk["text"],
                max(max_chars, ASSISTANT_RAG_TABLE_CHUNK_CHARS) if chunk.get("table") else max_chars,
                keep_lines=bool(chunk.get("table")),
            ),
        }
        for chunk in chosen
    ]


def _ranked_candidates(
    doc_id: int,
    index: dict,
    question: str,
    current_page: int,
    recent_questions: list[str] | None,
) -> tuple[list[dict], int]:
    """Candidats fusionnés (lexical ⊕ sémantique), du meilleur au moins bon, et
    profondeur de recherche recommandée (nombre de passages à citer)."""
    chunks = index["chunks"]
    terms, search = _query_terms(question, recent_questions)
    resolved = resolve_terms(terms, chunks, index.get("vocab")) if terms else []
    # La page visible d'abord : la recherche ne s'élargit que si l'étudiant le
    # demande ou si la page ne parle pas du sujet de la question.
    wide = search or page_coverage(chunks, resolved, current_page) < ASSISTANT_RAG_PAGE_COVERAGE
    depth = ASSISTANT_RAG_SEARCH_TOP_K if wide else ASSISTANT_RAG_TOP_K

    lexical = _lexical_order(chunks, expand_terms(terms, resolved, chunks), current_page) if resolved else []
    # Un suivi (« cherche dans tout l'article ») ne dit pas de quoi il parle :
    # la question précédente entre dans l'embedding.
    query = question
    if (search or len(terms) < 2) and recent_questions:
        query = f"{recent_questions[-1]} {question}"
    _ensure_vectors(doc_id, index, sync_max=_EMBED_SYNC_MAX_CHUNKS)
    semantic = _semantic_order(index, query, current_page)
    return fuse_rankings(lexical, semantic), depth
