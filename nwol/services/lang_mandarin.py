# services/lang_mandarin.py — Mandarin : jetons, pinyin, caractères, sandhi.
#
# Ce qui est vérifiable ne vient pas de Clikoda (plan § 1.2) : Clikoda découpe le
# texte en mots (les jetons, unité du tap), et d'ici on
#   * vérifie que les jetons recollent exactement la phrase et que le texte est
#     en caractères simplifiés (G5) ;
#   * calcule le pinyin de chaque jeton (G11) avec pypinyin, en signalant
#     `suspect` un caractère à plusieurs lectures que ni le dictionnaire de mots
#     ni la table des lectures isolées ne résout ;
#   * repère les sandhis (3e ton, 一, 不) pour une note automatique (M6) et les
#     clés du registre que contient un mot (M8).
#
# pypinyin est une dépendance OPTIONNELLE (L1, déclarée dans requirements.txt :
# code MIT, dictionnaires dérivés d'Unihan, de CC-CEDICT (CC BY-SA) et de zdic).
# Sans elle, `token_pinyin` renvoie None : le mandarin reste lisible, sans aide
# de prononciation, et la porte V17 refuse d'ouvrir la langue.
from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger("services.lang_mandarin")

try:  # pragma: no cover - dépend de l'environnement
    from pypinyin import Style, pinyin as _pypinyin
    from pypinyin.constants import PHRASES_DICT as _PHRASES
    from pypinyin.constants import PINYIN_DICT as _CHARS
    PINYIN_AVAILABLE = True
except ImportError:  # pragma: no cover
    PINYIN_AVAILABLE = False
    _PHRASES, _CHARS = {}, {}

_TONE_MARKS = {
    "a": "āáǎà", "e": "ēéěè", "i": "īíǐì", "o": "ōóǒò", "u": "ūúǔù", "ü": "ǖǘǚǜ",
}
_MAX_PHRASE = 6


def is_han(ch: str) -> bool:
    o = ord(ch)
    return 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0x20000 <= o <= 0x2A6DF or 0xF900 <= o <= 0xFAFF


def han_chars(text: str) -> list[str]:
    return [c for c in text or "" if is_han(c)]


@lru_cache(maxsize=1)
def traditional_chars() -> frozenset[str]:
    """Caractères traditionnels à rejeter (G5) : présents dans Big5 (jeu
    traditionnel) mais absents de GB2312 (jeu simplifié). Calculé depuis les
    codecs de la bibliothèque standard : aucune table à maintenir. Limite
    connue : quelques caractères rares, identiques dans les deux systèmes mais
    hors GB2312 (喆, 堃), seraient refusés — ils n'ont rien à faire en A1-B2."""
    out: set[str] = set()
    for code in range(0x8140, 0xFA00):
        try:
            ch = bytes([code >> 8, code & 0xFF]).decode("big5")
        except UnicodeDecodeError:
            continue
        if len(ch) == 1 and is_han(ch):
            try:
                ch.encode("gb2312")
            except UnicodeEncodeError:
                out.add(ch)
    return frozenset(out)


def traditional_in(text: str) -> list[str]:
    table = traditional_chars()
    return sorted({c for c in text or "" if c in table})


def tokens_rebuild(text: str, tokens: list[str]) -> bool:
    """G5 : la concaténation des jetons redonne exactement la phrase."""
    return isinstance(tokens, list) and all(isinstance(t, str) for t in tokens) and "".join(tokens) == text


@lru_cache(maxsize=1)
def _standalone_readings() -> dict[str, str]:
    from services.lang_static import script_registry

    return dict((script_registry("mandarin_readings") or {}).get("standalone") or {})


@lru_cache(maxsize=1)
def _ambiguous() -> frozenset[str]:
    from services.lang_static import script_registry

    return frozenset((script_registry("mandarin_readings") or {}).get("ambiguous") or [])


def _is_heteronym(ch: str) -> bool:
    """Plusieurs lectures COURANTES (table relue), pas seulement au dictionnaire."""
    return ch in _ambiguous() and "," in _CHARS.get(ord(ch), "")


def _covered_by_phrases(token: str) -> list[bool]:
    """Pour chaque caractère : sa lecture est-elle fixée par un mot du
    dictionnaire (plus long appariement à gauche) ?"""
    covered = [False] * len(token)
    i = 0
    while i < len(token):
        for size in range(min(_MAX_PHRASE, len(token) - i), 1, -1):
            if token[i:i + size] in _PHRASES:
                for k in range(i, i + size):
                    covered[k] = True
                i += size
                break
        else:
            i += 1
    return covered


def _tone_of(numbered: str) -> int:
    return int(numbered[-1]) if numbered and numbered[-1].isdigit() else 5


def mark_to_number(syllable: str) -> str:
    """nǐ -> ni3 ; de -> de5 (ton neutre)."""
    base, tone = [], 5
    for ch in syllable:
        for vowel, marks in _TONE_MARKS.items():
            if ch in marks:
                base.append(vowel)
                tone = marks.index(ch) + 1
                break
        else:
            base.append(ch)
    return "".join(base).replace("ü", "v") + str(tone)


def token_pinyin(token: str) -> dict | None:
    """Pinyin d'un jeton : {"syllables": [{"hanzi","mark","num","tone"}], "suspect"}.

    None si pypinyin est absent. Les caractères non han (ponctuation, chiffres)
    n'ont pas de syllabe."""
    if not PINYIN_AVAILABLE:
        return None
    hanzi = [c for c in token if is_han(c)]
    if not hanzi:
        return {"syllables": [], "suspect": False}
    standalone = _standalone_readings()
    if len(token) == 1 and token in standalone:
        marks = [standalone[token]]
        suspect = False
    else:
        marks = [p[0] for p in _pypinyin(token, style=Style.TONE, heteronym=False, errors="ignore")]
        covered = _covered_by_phrases(token)
        suspect = any(
            is_han(c) and _is_heteronym(c) and not covered[i] and c not in standalone
            for i, c in enumerate(token)
        )
        if len(token) > 1:
            # Un caractère isolé DANS un jeton garde sa lecture isolée connue
            # (的, 了, 们…) quand aucun mot ne le couvre.
            idx = 0
            for i, c in enumerate(token):
                if not is_han(c):
                    continue
                if not covered[i] and c in standalone and idx < len(marks):
                    marks[idx] = standalone[c]
                idx += 1
    if len(marks) != len(hanzi):
        return {"syllables": [], "suspect": True}
    syllables = []
    for ch, mark in zip(hanzi, marks):
        num = mark_to_number(mark)
        syllables.append({"hanzi": ch, "mark": mark, "num": num, "tone": _tone_of(num)})
    return {"syllables": syllables, "suspect": suspect}


# ── Sandhi (M6) ───────────────────────────────────────────────────────────────

def sandhi_notes(line_tokens: list[str], pinyins: list[dict | None]) -> list[dict]:
    """Sandhis qui s'appliquent dans une réplique : [{"rule", "token_idx",
    "hanzi", "from", "to"}]. Le pinyin affiché garde le ton du dictionnaire ;
    la note dit ce qui se prononce (M6). Règles :
      * 3e + 3e : le premier passe au 2e ;
      * 一 : 2e devant un 4e ton, 4e devant un 1er, 2e ou 3e (sauf en fin de
        groupe, après 第 et dans un nombre, où il reste yī) ;
      * 不 : 2e devant un 4e ton."""
    flat: list[tuple[int, dict]] = []
    for idx, (tok, py) in enumerate(zip(line_tokens, pinyins)):
        if not py or not py.get("syllables"):
            if not any(is_han(c) for c in tok):
                flat.append((idx, {"hanzi": "", "tone": 0, "mark": ""}))  # frontière de groupe
            continue
        for syl in py["syllables"]:
            flat.append((idx, syl))
    notes: list[dict] = []
    digits = set("零一二三四五六七八九十百千万两")
    for k, (idx, syl) in enumerate(flat):
        nxt = flat[k + 1][1] if k + 1 < len(flat) else None
        prev = flat[k - 1][1] if k > 0 else None
        if not syl["hanzi"] or not nxt or not nxt["hanzi"]:
            continue
        if syl["hanzi"] == "一":
            if (prev and prev["hanzi"] in digits | {"第"}) or nxt["hanzi"] in digits:
                continue
            to = "yí" if nxt["tone"] == 4 else ("yì" if nxt["tone"] in (1, 2, 3) else None)
            if to:
                notes.append({"rule": "yi", "token_idx": idx, "hanzi": "一", "from": "yī", "to": to})
        elif syl["hanzi"] == "不" and nxt["tone"] == 4:
            notes.append({"rule": "bu", "token_idx": idx, "hanzi": "不", "from": "bù", "to": "bú"})
        elif syl["tone"] == 3 and nxt["tone"] == 3:
            to = syl["num"][:-1]
            notes.append({
                "rule": "tone3", "token_idx": idx, "hanzi": syl["hanzi"], "from": syl["mark"],
                "to": _with_tone(to, 2),
            })
    return notes


def _with_tone(bare: str, tone: int) -> str:
    """ni + 2 -> ní (voyelle portant le ton selon la règle usuelle a/e/ou, sinon la dernière)."""
    word = bare.replace("v", "ü")
    for target in ("a", "e"):
        if target in word:
            i = word.index(target)
            return word[:i] + _TONE_MARKS[target][tone - 1] + word[i + 1:]
    if "ou" in word:
        i = word.index("o")
        return word[:i] + _TONE_MARKS["o"][tone - 1] + word[i + 1:]
    for i in range(len(word) - 1, -1, -1):
        if word[i] in _TONE_MARKS:
            return word[:i] + _TONE_MARKS[word[i]][tone - 1] + word[i + 1:]
    return word


# ── Clés (M8) ─────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _components() -> list[dict]:
    from services.lang_static import script_registry

    return list((script_registry("mandarin_components") or {}).get("components") or [])


def components_in(word: str) -> list[dict]:
    """Clés du registre S12 présentes dans les caractères d'un mot."""
    chars = set(han_chars(word))
    return [c for c in _components() if chars & set(c.get("chars") or [])]
