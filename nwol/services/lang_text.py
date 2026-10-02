# services/lang_text.py — Découpage et comparaison de textes, toutes écritures.
#
# Un épisode est affiché jeton par jeton (c'est l'unité du tap, § 10.2) : chaque
# réplique est stockée comme une liste de jetons dont la concaténation redonne
# EXACTEMENT le texte. Pour les écritures à espaces (latin, arabe), le découpage
# est calculé ici ; pour le mandarin, Clikoda fournit les jetons et G5 vérifie
# qu'ils recollent (services/lang_mandarin.py).
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Apostrophes et traits d'union internes à un mot (« don't », « porte-monnaie »).
_JOINERS = {"'", "’", "-", "‐"}


def _wordy(ch: str) -> bool:
    """Lettre, chiffre ou marque combinante (voyelles brèves arabes comprises :
    `\\w` des regex Python ne les reconnaît pas, d'où ce test explicite)."""
    return unicodedata.category(ch)[0] in ("L", "N", "M")


def segment(text: str) -> list[dict]:
    """Jetons d'une réplique : {"text", "w"} où `w` = mot tapable. Les espaces et
    la ponctuation forment des jetons non tapables ; tout recolle à l'identique."""
    tokens: list[dict] = []
    i, n = 0, len(text or "")
    while i < n:
        j = i
        if _wordy(text[i]):
            while j < n and (_wordy(text[j]) or (
                text[j] in _JOINERS and j + 1 < n and _wordy(text[j + 1]) and j > i
            )):
                j += 1
            tokens.append({"text": text[i:j], "w": True})
        else:
            while j < n and not _wordy(text[j]):
                j += 1
            tokens.append({"text": text[i:j], "w": False})
        i = j
    return tokens


def words(text: str) -> list[str]:
    return [t["text"] for t in segment(text) if t["w"]]


def fold(text: str) -> str:
    """Minuscules sans accents ni voyelles brèves."""
    norm = unicodedata.normalize("NFD", (text or "").strip().lower())
    return "".join(c for c in norm if unicodedata.category(c) != "Mn")


# Mots-outils ignorés par `jaccard` : les résumés d'épisodes sont écrits dans la
# langue d'explication (français ou anglais), et « dans », « avec », « pour »
# rapprochaient deux résumés sans rapport.
_FR_STOP = {
    "les", "des", "une", "dans", "pour", "avec", "qui", "que", "est", "sont", "son", "sa", "ses",
    "leur", "leurs", "sur", "par", "pas", "plus", "mais", "elle", "ils", "elles", "lui", "aux",
    "cette", "ces", "tout", "tous", "fait", "font", "entre", "chez", "vers", "sans", "sous",
}
_EN_STOP = {
    "the", "and", "for", "with", "who", "that", "this", "these", "those", "are", "was", "were", "his",
    "her", "hers", "their", "they", "them", "she", "him", "has", "have", "had", "not", "but", "from",
    "into", "onto", "about", "all", "its", "when", "while", "then", "than", "out", "some", "does",
}


def jaccard(a: str, b: str, ignore: set[str] | None = None) -> float:
    """Similarité de deux textes sur leurs mots repliés (G9 : redites). `ignore`
    retire des mots attendus partout (les prénoms des personnages)."""
    skip = _FR_STOP | _EN_STOP | {fold(w) for w in (ignore or set())}
    sa = {fold(w) for w in words(a) if len(w) > 2} - skip
    sb = {fold(w) for w in words(b) if len(w) > 2} - skip
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return len(a or b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_for_compare(text: str) -> str:
    """Casse, ponctuation et espaces neutralisés (N5) — les accents comptent :
    « esta » et « está » ne sont pas la même réponse."""
    lowered = unicodedata.normalize("NFC", (text or "")).casefold()
    return " ".join(_PUNCT_RE.sub(" ", lowered).split())


def word_diff(original: str, typed: str) -> list[dict]:
    """Différences mot à mot entre l'original et la retraduction saisie (N5),
    pour un affichage côte à côte. Opérations : equal | missing | extra."""
    ref = normalize_for_compare(original).split()
    got = normalize_for_compare(typed).split()
    ops: list[dict] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=ref, b=got, autojunk=False).get_opcodes():
        if tag == "equal":
            ops.append({"op": "equal", "text": " ".join(ref[i1:i2])})
            continue
        if i2 > i1:
            ops.append({"op": "missing", "text": " ".join(ref[i1:i2])})
        if j2 > j1:
            ops.append({"op": "extra", "text": " ".join(got[j1:j2])})
    return ops


def find_token_span(tokens: list[dict], needle: str) -> list[int]:
    """Indices des jetons couvrant la sous-chaîne `needle` (première occurrence),
    ou [] si elle n'est pas alignée sur des jetons. Sert à surligner un exemple
    ou une ancre de note dans une réplique."""
    if not needle:
        return []
    text = "".join(t["text"] for t in tokens)
    start = text.find(needle)
    if start < 0:
        return []
    end = start + len(needle)
    out, pos = [], 0
    for idx, tok in enumerate(tokens):
        t_start, t_end = pos, pos + len(tok["text"])
        pos = t_end
        if t_end <= start or t_start >= end:
            continue
        if tok.get("w"):
            out.append(idx)
    return out
