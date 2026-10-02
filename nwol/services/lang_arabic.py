# services/lang_arabic.py — Arabe littéraire : voyelles brèves, translittération.
#
# Code maison sur les plages Unicode, sans dépendance (L3) : les vocaliseurs
# existants (Mishkal et équivalents) sont sous GPL et écartés (L4). Ce module
# ne VOCALISE rien — Clikoda écrit un texte entièrement vocalisé, et d'ici on :
#   * mesure que la vocalisation est complète (validateur G6) ;
#   * retire tout ou partie des voyelles brèves (effacement des aides, § 13.2) ;
#   * calcule la translittération depuis le texte vocalisé (A5), selon le schéma
#     de nwol/data/lang/scripts/arabic_translit.json ;
#   * extrait le « radical vocalisé » d'un mot (tout sauf la dernière lettre,
#     qui porte les terminaisons) pour le comparer aux formes validées (A7).
from __future__ import annotations

import unicodedata
from functools import lru_cache

from services.lang_text import segment

FATHA, DAMMA, KASRA = "َ", "ُ", "ِ"
FATHATAN, DAMMATAN, KASRATAN = "ً", "ٌ", "ٍ"
SHADDA, SUKUN = "ّ", "ْ"
DAGGER_ALIF = "ٰ"
TATWEEL = "ـ"
SHORT_VOWELS = {FATHA, DAMMA, KASRA}
TANWIN = {FATHATAN, DAMMATAN, KASRATAN}
VOWEL_MARKS = SHORT_VOWELS | TANWIN | {SUKUN}

ALIF, ALIF_MADDA, ALIF_WASLA = "ا", "آ", "ٱ"
ALIF_MAQSURA, TA_MARBUTA = "ى", "ة"
WAW, YA, LAM = "و", "ي", "ل"
HAMZA_FORMS = {"ء", "أ", "إ", "ؤ", "ئ"}
ALIFS = {ALIF, ALIF_MADDA, ALIF_WASLA}


def is_arabic_letter(ch: str) -> bool:
    return "ء" <= ch <= "ي" and ch != TATWEEL or ch == ALIF_WASLA


def is_harakat(ch: str) -> bool:
    """Voyelles brèves, tanwīn, šadda, sukūn, alif suscrit et marques coraniques."""
    o = ord(ch)
    return 0x064B <= o <= 0x065F or o == 0x0670 or 0x06D6 <= o <= 0x06ED


def strip_harakat(text: str) -> str:
    """Texte sans aucune marque vocalique (ni tatwīl)."""
    return "".join(ch for ch in (text or "") if not is_harakat(ch) and ch != TATWEEL)


def clusters(word: str) -> list[tuple[str, set[str]]]:
    """(lettre, marques qui la suivent) pour chaque lettre d'un mot."""
    out: list[tuple[str, set[str]]] = []
    for ch in word:
        if is_harakat(ch):
            if out:
                out[-1][1].add(ch)
        elif ch != TATWEEL:
            out.append((ch, set()))
    return out


def _is_article(cl: list[tuple[str, set[str]]], start: int) -> bool:
    return (
        len(cl) > start + 2 and cl[start][0] in (ALIF, ALIF_WASLA) and cl[start][1].isdisjoint(SHORT_VOWELS)
        and cl[start + 1][0] == LAM
    )


def vocalization_ratio(text: str) -> float:
    """Part des lettres porteuses d'une voyelle, d'un tanwīn ou d'un sukūn (G6).

    Dispensées : les alifs, l'alif maqṣūra, la dernière lettre de chaque mot
    (forme pausale), l'alif et le lām de l'article, et wāw/yāʾ de prolongation
    (après ḍamma/kasra). Texte sans lettre arabe -> 0."""
    carriers = marked = 0
    for tok in segment(text):
        if not tok["w"]:
            continue
        cl = clusters(tok["text"])
        letters = [i for i, (ch, _m) in enumerate(cl) if is_arabic_letter(ch)]
        if not letters:
            continue
        skip: set[int] = {letters[-1]}
        for start in range(min(2, len(cl))):
            if _is_article(cl, start):
                skip |= {start, start + 1}
        for i in letters:
            ch, marks = cl[i]
            if i in skip or ch in ALIFS or ch == ALIF_MAQSURA:
                continue
            prev_marks = cl[i - 1][1] if i > 0 else set()
            if not marks & (VOWEL_MARKS | {SHADDA}) and (
                (ch == WAW and DAMMA in prev_marks) or (ch == YA and KASRA in prev_marks)
            ):
                continue
            carriers += 1
            if marks & (VOWEL_MARKS | {SHADDA, DAGGER_ALIF}):
                marked += 1
    return marked / carriers if carriers else (1.0 if any(is_arabic_letter(c) for c in text or "") else 0.0)


def is_fully_vocalized(text: str, min_ratio: float) -> bool:
    return vocalization_ratio(text) >= min_ratio


def partial_vocalization(text: str, keep) -> str:
    """Retire les voyelles brèves des mots pour lesquels `keep(index_mot, mot_nu)`
    est faux (index = rang du mot tapable dans la réplique). La šadda est
    retirée avec elles : l'effacement est total pour un mot acquis."""
    out: list[str] = []
    idx = 0
    for tok in segment(text):
        if not tok["w"]:
            out.append(tok["text"])
            continue
        bare = strip_harakat(tok["text"])
        out.append(tok["text"] if keep(idx, bare) else bare)
        idx += 1
    return "".join(out)


def to_pausal(text: str) -> str:
    """Met le DERNIER mot de la réplique en forme pausale (A3) : la voyelle
    brève ou le tanwīn -un / -in de sa dernière lettre devient un sukūn (la
    šadda reste) ; -an, porté par un alif, ne change pas. Calculé ici plutôt que
    demandé : au banc, Clikoda laisse la voyelle finale dans deux textes sur trois."""
    tokens = segment(text)
    for tok in reversed(tokens):
        if not tok["w"]:
            continue
        if not any(is_arabic_letter(c) for c in tok["text"]):
            return text  # réplique finie par un nombre : rien à mettre en pause
        cl = clusters(tok["text"])
        ch, marks = cl[-1]
        if not marks & (SHORT_VOWELS | {DAMMATAN, KASRATAN}):
            return text
        kept = marks - SHORT_VOWELS - {DAMMATAN, KASRATAN}
        word = "".join(c + "".join(sorted(m)) for c, m in cl[:-1])
        tok["text"] = word + ch + "".join(sorted(kept | {SUKUN}))
        return "".join(t["text"] for t in tokens)
    return text


def stem_vocalized(word: str) -> str:
    """Le mot vocalisé, marques de la DERNIÈRE lettre retirées (elle porte les
    désinences casuelles, qui changent légitimement d'une phrase à l'autre)."""
    cl = clusters(word)
    if not cl:
        return ""
    return "".join(ch + "".join(sorted(m)) for ch, m in cl[:-1]) + cl[-1][0]


# ── Translittération (A5) ─────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _scheme() -> dict:
    from services.lang_static import script_registry

    scheme = script_registry("arabic_translit")
    if not scheme:
        raise RuntimeError("nwol/data/lang/scripts/arabic_translit.json manquant")
    return scheme


def sun_letters() -> set[str]:
    return set(_scheme()["sun_letters"])


def _vowel(marks: set[str], scheme: dict) -> str:
    for mark in (FATHA, DAMMA, KASRA, FATHATAN, DAMMATAN, KASRATAN):
        if mark in marks:
            return scheme["vowels"][mark]
    return ""


# Exception lexicale (pas de règle possible : أُولَى se lit bien ūlā).
_SILENT_WAW_WORDS = frozenset({"أولئك", "أولو", "أولي", "أولات"})


def transliterate_word(word: str) -> str:
    """Translittération d'UN mot vocalisé.

    Rendu tel qu'écrit : un mot en forme pausale (dernière lettre nue ou au
    sukūn) perd sa désinence, un tanwīn écrit est rendu (-un, -an, -in). La
    hamza initiale n'est pas notée ; l'article s'assimile devant une lettre
    solaire marquée de la šadda (aš-šams)."""
    scheme = _scheme()
    cons: dict[str, str] = scheme["consonants"]
    long_v: dict[str, str] = scheme["long_vowels"]
    sun = set(scheme["sun_letters"])
    cl = clusters(word)
    if strip_harakat(word) in _SILENT_WAW_WORDS and len(cl) > 1 and cl[1][0] == WAW:
        del cl[1]  # أُولٰئِكَ ulāʾika : wāw d'orthographe, jamais prononcé
    out: list[str] = []
    i = 0
    article_at: int | None = None
    if len(cl) > 3 and cl[0][0] in scheme["proclitics"] and cl[0][1] & SHORT_VOWELS and _is_article(cl, 1):
        out.append(cons.get(cl[0][0], "") + _vowel(cl[0][1], scheme) + "-")
        article_at = 1
    elif _is_article(cl, 0):
        article_at = 0
    elif len(cl) > 3 and cl[0][0] == LAM and KASRA in cl[0][1] and cl[1][0] == LAM:
        # li- + article, dont l'alif tombe à l'écrit : لِلْبَيْتِ -> li-l-bayti
        out.append(cons[LAM] + scheme["vowels"][KASRA] + "-")
        nxt_ch, nxt_marks = cl[2]
        if nxt_ch in sun and SHADDA in nxt_marks:
            out.append(cons.get(nxt_ch, nxt_ch) + "-")
            cl[2] = (nxt_ch, nxt_marks - {SHADDA})
        else:
            out.append(cons[LAM] + "-")
        i = 2
    if article_at is not None:
        nxt_ch, nxt_marks = cl[article_at + 2]
        if nxt_ch in sun and SHADDA in nxt_marks:
            out.append(("a" if article_at == 0 else "") + cons.get(nxt_ch, nxt_ch) + "-")
            cl[article_at + 2] = (nxt_ch, nxt_marks - {SHADDA})
        else:
            out.append(("a" if article_at == 0 else "") + cons[LAM] + "-")
        i = article_at + 2
    first_letter = i
    while i < len(cl):
        ch, marks = cl[i]
        nxt = cl[i + 1] if i + 1 < len(cl) else None
        if ch in (ALIF, ALIF_WASLA):
            # Initiale : attaque vocalique (hamza non notée). Ailleurs, un alif nu
            # n'allonge qu'une fatḥa : il est muet après une kasra ou une ḍamma
            # (مِائَةٌ miʾatun) et, en fin de mot, après un wāw sans voyelle (alif
            # du pluriel verbal : كَتَبُوا katabū, دَعَوْا daʿaw).
            prev_ch, prev_marks = cl[i - 1] if i > 0 else ("", set())
            silent = not marks and i > first_letter and (
                prev_marks & {KASRA, DAMMA}
                or (i == len(cl) - 1 and prev_ch == WAW and not prev_marks & (SHORT_VOWELS | TANWIN))
            )
            if i == first_letter:
                out.append(_vowel(marks, scheme))
            elif not silent:
                out.append(long_v["alif"])
            i += 1
            continue
        if ch == WAW and not marks and i > first_letter and cl[i - 1][1] & TANWIN:
            i += 1  # wāw muet après le tanwīn : عَمْرٌو ʿamrun
            continue
        if ch == ALIF_MADDA:
            out.append(("" if i == first_letter else cons["\u0621"]) + long_v["alif"])
            i += 1
            continue
        if ch == ALIF_MAQSURA:
            out.append(cons[YA] + _vowel(marks, scheme) if marks & SHORT_VOWELS else long_v["alif"])
            i += 1
            continue
        if ch == TA_MARBUTA:
            vowel = _vowel(marks, scheme)
            out.append(cons[TA_MARBUTA] + vowel if vowel else "")
            i += 1
            continue
        base = cons.get(ch)
        if base is None:
            out.append(ch)
            i += 1
            continue
        if ch in HAMZA_FORMS and i == first_letter:
            base = ""
        out.append(base * 2 if SHADDA in marks else base)
        vowel = _vowel(marks, scheme)
        consumed = 0
        bare_next = nxt is not None and not nxt[1] & (SHORT_VOWELS | TANWIN | {SHADDA})
        if DAGGER_ALIF in marks:
            vowel = long_v["alif"]
        elif bare_next and FATHA in marks and nxt[0] in (ALIF, ALIF_MAQSURA):
            vowel, consumed = long_v["alif"], 1
        elif bare_next and DAMMA in marks and nxt[0] == WAW:
            vowel, consumed = long_v[WAW], 1
        elif bare_next and KASRA in marks and nxt[0] == YA:
            vowel, consumed = long_v[YA], 1
        elif FATHATAN in marks and nxt is not None and nxt[0] in (ALIF, ALIF_MAQSURA):
            consumed = 1  # ًا : l'alif ne fait que porter le tanwīn
        out.append(vowel)
        i += 1 + consumed
    return "".join(out)


def transliterate(vocalized: str) -> str:
    """Translittération d'un texte entièrement vocalisé ; la ponctuation arabe
    devient la ponctuation latine correspondante."""
    punct = _scheme().get("punctuation", {})
    out: list[str] = []
    for tok in segment(vocalized):
        if tok["w"]:
            out.append(transliterate_word(tok["text"]))
        else:
            out.append("".join(punct.get(ch, ch) for ch in tok["text"]))
    return "".join(out)


def letters_of(word: str) -> list[str]:
    """Lettres de base d'un mot (formes de la hamza ramenées à leur support
    pour le registre : أ -> ا n'est PAS fait, chaque graphème compte)."""
    return [ch for ch, _m in clusters(word) if is_arabic_letter(ch)]


def contextual_form(word: str, index: int) -> str:
    """Position d'une lettre dans son mot : isolated | initial | medial | final,
    selon les lettres qui ne se lient pas à gauche (registre arabic.json)."""
    from services.lang_static import script_registry

    non_joining = {
        letter["char"] for letter in script_registry("arabic").get("letters") or []
        if not letter.get("connects_left", True)
    }
    letters = letters_of(word)
    if not 0 <= index < len(letters):
        return "isolated"
    joins_prev = index > 0 and letters[index - 1] not in non_joining
    joins_next = index < len(letters) - 1 and letters[index] not in non_joining
    if joins_prev and joins_next:
        return "medial"
    if joins_prev:
        return "final"
    if joins_next:
        return "initial"
    return "isolated"


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")
