# services/lang_scripts.py — Écritures non latines : signes acquis, aides qui s'effacent.
#
# Une aide (translittération, voyelles brèves, pinyin) disparaît quand le signe
# ou le mot qu'elle soutient est acquis (C6, § 13.2, M4). Ce module dit, pour un
# jeton donné, quels signes il contient et quelles aides l'apprenant voit
# encore ; l'assembleur de séance (services/lang_runs.py) s'en sert pour
# préparer l'affichage, le front ne fait que rendre.
from __future__ import annotations

from functools import lru_cache

from config.settings import LANG_AR_VOCALIZATION_LEVELS, LANG_SCRIPT_FAMILY
from db import lang_episode_db as store
from services import lang_arabic as arabic
from services.lang_mandarin import han_chars
from services.lang_static import script_registry

ARABIC_SCRIPT = "arabic"
HANZI_SCRIPT = "hanzi"
COMPONENTS_SCRIPT = "mandarin_components"
TONES_SCRIPT = "mandarin_sounds"


@lru_cache(maxsize=1)
def _arabic_char_units() -> dict[str, str]:
    """Caractère arabe -> id du registre (les formes de la hamza pointent la hamza)."""
    reg = script_registry("arabic")
    out = {letter["char"]: letter["id"] for letter in reg.get("letters") or []}
    for mark in reg.get("marks") or []:
        if mark.get("kind") == "lettre":
            out[mark["char"]] = mark["id"]
            for support in mark.get("supports") or []:
                out[support] = mark["id"]
    return out


def script_units_of_token(language: str, text: str) -> list[tuple[str, str]]:
    """Signes d'un jeton, sans doublon : lettres arabes (id du registre) ou
    caractères chinois (le caractère lui-même)."""
    fam = LANG_SCRIPT_FAMILY.get(language)
    if fam == "arabe":
        units = _arabic_char_units()
        seen: list[tuple[str, str]] = []
        for ch in arabic.letters_of(text):
            unit = units.get(ch)
            if unit and (ARABIC_SCRIPT, unit) not in seen:
                seen.append((ARABIC_SCRIPT, unit))
        return seen
    if fam == "hanzi":
        return [(HANZI_SCRIPT, ch) for ch in dict.fromkeys(han_chars(text))]
    return []


def acquired_units(profile_id: int, script: str) -> set[str]:
    return {k for k, row in store.get_script_progress(profile_id, script).items() if row.get("acquired_at")}


def seen_units(profile_id: int, script: str) -> set[str]:
    return set(store.get_script_progress(profile_id, script))


def arabic_aid_level(cefr: str, fraction: float) -> int:
    """§ 13.2 : 1 = translittération sous les lettres non acquises + vocalisation
    complète ; 2 = vocalisation complète ; 3 = vocalisation des mots non acquis ;
    4 = vocalisation au tap. Lu depuis LANG_AR_VOCALIZATION_LEVELS."""
    from config.settings import LANG_CEFR_ORDER

    rank = LANG_CEFR_ORDER.index(cefr) if cefr in LANG_CEFR_ORDER else 0
    level = 1
    for level_cefr, from_fraction, value in LANG_AR_VOCALIZATION_LEVELS:
        lrank = LANG_CEFR_ORDER.index(level_cefr)
        if rank > lrank or (rank == lrank and fraction >= from_fraction):
            level = value
    return level


def arabic_word_display(vocalized: str, *, level: int, word_acquired: bool,
                        letters_acquired: set[str]) -> dict:
    """Affichage d'un mot arabe selon le niveau d'aide : `display` (texte montré),
    `translit` (sous le mot, ou None), `tap_vocalized` (révélé au tap)."""
    bare = arabic.strip_harakat(vocalized)
    units = _arabic_char_units()
    letters = [units.get(ch) for ch in arabic.letters_of(vocalized)]
    all_letters_known = all(u in letters_acquired for u in letters if u)
    if level <= 1:
        display, translit = vocalized, (None if all_letters_known else arabic.transliterate_word(vocalized))
    elif level == 2:
        display, translit = vocalized, None
    elif level == 3:
        display, translit = (bare if word_acquired else vocalized), None
    else:
        display, translit = bare, None
    return {"display": display, "translit": translit, "tap_vocalized": vocalized, "bare": bare}
