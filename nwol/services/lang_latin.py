# services/lang_latin.py — Aides déterministes des langues latines (§ 12.1).
#
# Anglais, espagnol, allemand : ce que l'apprenant reconnaît déjà (mots
# transparents, comparés à la traduction dans SA langue d'explication), ce qui
# piège un francophone (faux-amis), ce qu'il doit apprendre avec chaque nom (le
# genre). Rien ici n'appelle Clikoda.
from __future__ import annotations

import re

from config.settings import LANG_TRANSPARENT_MAX_DISTANCE
from services.lang_static import faux_amis
from services.lang_text import fold, levenshtein

# Articles et déterminants retirés d'une traduction avant comparaison, par
# langue d'explication (« to » : l'infinitif anglais, « to speak »).
_DETERMINERS = {
    "fr": re.compile(r"^(?:le|la|les|l'|l’|un|une|des|du|de la|de l'|se|s')\s*", re.I),
    "en": re.compile(r"^(?:the|a|an|to)\s+", re.I),
}
_ALTERNATIVES = {"fr": re.compile(r"[,/;()]|\bou\b"), "en": re.compile(r"[,/;()]|\bor\b")}
_MIN_LEN = 4


def _candidates(translation: str, explain_lang: str = "fr") -> list[str]:
    lang = explain_lang if explain_lang in _DETERMINERS else "fr"
    parts = _ALTERNATIVES[lang].split(translation or "")
    out = []
    for part in parts:
        cleaned = _DETERMINERS[lang].sub("", part.strip())
        if cleaned:
            out.append(fold(cleaned))
    return out


def is_transparent(lemma: str, translation: str, explain_lang: str = "fr") -> bool:
    """N1 : distance d'édition normalisée lemme ↔ traduction sous le seuil.
    « familia » / « famille » (ou « family ») oui ; « perro » / « chien » non ;
    mots de moins de quatre lettres jamais (« de », « la » se ressemblent sans
    rien signifier)."""
    word = fold(lemma)
    if len(word) < _MIN_LEN:
        return False
    for cand in _candidates(translation, explain_lang):
        if len(cand) < _MIN_LEN or " " in cand:
            continue
        distance = levenshtein(word, cand) / max(len(word), len(cand))
        if distance <= LANG_TRANSPARENT_MAX_DISTANCE:
            return True
    return False


def faux_ami(language: str, lemma: str, explain_lang: str = "fr") -> dict | None:
    """N2 : entrée de la liste S17 correspondant au lemme, ou None. Les listes
    sont écrites pour un francophone (« ressemble à embarrassée ») : elles ne
    s'appliquent qu'à une langue d'explication française."""
    if explain_lang != "fr":
        return None
    return faux_amis(language).get(fold(lemma))


# ── Allemand : genre et article (N3) ──────────────────────────────────────────
# Seuls les articles SANS ambiguïté servent de preuve : « der » est masculin au
# nominatif mais aussi féminin au datif ; « die » est féminin ou pluriel. Une
# vérification qui refuserait « die Kinder » (pluriel d'un neutre) ferait rejouer
# une génération correcte.
_DE_ARTICLE_GENDERS: dict[str, set[str]] = {
    "das": {"n"},
    "ein": {"m", "n"},
    "einen": {"m"},
    "eine": {"f"},
    "dem": {"m", "n"},
    "einem": {"m", "n"},
    "des": {"m", "n"},
    "eines": {"m", "n"},
}
_DE_ARTICLES_FOR_GENDER = {"m": "der", "f": "die", "n": "das"}


def de_article(gender: str | None) -> str | None:
    return _DE_ARTICLES_FOR_GENDER.get((gender or "").lower()[:1])


def de_gender_conflict_pairs(tokens: list[str], glossary: list[dict]) -> list[tuple[str, str, str]]:
    """(article, nom, genre déclaré) pour chaque nom du glossaire dont l'article
    présent dans le texte contredit le genre. Ne compare que la forme de base
    (forme == lemme) : une forme fléchie ou plurielle ne prouve rien."""
    nouns = {
        g["form"]: (g.get("gender") or "").lower()[:1]
        for g in glossary
        if (g.get("pos") or "").startswith("n") and g.get("gender") and g.get("form") == g.get("lemma")
    }
    conflicts: list[tuple[str, str, str]] = []
    words = [t for t in tokens if t.strip()]
    for prev, word in zip(words, words[1:]):
        allowed = _DE_ARTICLE_GENDERS.get(prev.lower())
        gender = nouns.get(word)
        if allowed and gender and gender not in allowed:
            conflicts.append((prev, word, gender))
    return conflicts


def de_gender_conflicts(tokens: list[str], glossary: list[dict]) -> list[str]:
    """Les mêmes, lisibles (« eine Haus (n) »). Liste vide = rien à redire."""
    return [f"{prev} {word} ({gender})" for prev, word, gender in de_gender_conflict_pairs(tokens, glossary)]
