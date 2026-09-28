# services/lang_static.py — Données statiques du module langues (plan § 4).
#
# Tout ce qui est fini, connu ou doit être fiable est écrit une fois, relu,
# versionné dans nwol/data/lang/, puis réinjecté en base au démarrage — même
# mécanisme que le catalogue des types de session (db/lang_db.SESSION_TYPES_SEED) :
#
#   program/<langue>.json      le programme A1 → C1 (un point = une notion)
#   placement/<langue>.json    le test de niveau, clés écrites à la main
#   onboarding/<langue>.json   phrases de survie, aperçu de l'écriture, bible par défaut
#   helpers/faux_amis_<langue>.json
#   scripts/*.json             registres d'écriture (lettres arabes, sons et clés du mandarin)
#
# Les validateurs d'ici sont LA définition des invariants (S2) : la suite de
# tests les rejoue sur chaque fichier (tests/services/test_lang_static.py, V11)
# et `python tools/validate_lang_data.py` les rejoue à la main après une relecture.
# Un fichier invalide n'est jamais injecté : le démarrage le journalise et garde
# la version précédente en base.
from __future__ import annotations

import hashlib
import json
import logging
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path

from config.settings import (
    LANG_ALL_TEXT_FORMATS,
    LANG_AR_MIN_VOCALIZED_RATIO,
    LANG_BILAN_EVERY,
    LANG_CEFR_ORDER,
    LANG_EXPLAIN_LANGUAGES,
    LANG_PILOT_LANGUAGES,
)

logger = logging.getLogger("services.lang_static")

if getattr(sys, "frozen", False):
    LANG_DATA_DIR = Path(getattr(sys, "_MEIPASS", ".")) / "data" / "lang"
else:
    LANG_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "lang"

# Préfixe des identifiants de points et d'items (« es.a1.ser_estar_1 »).
LANG_ISO: dict[str, str] = {
    "espagnol": "es", "anglais": "en", "allemand": "de", "mandarin": "zh", "arabe": "ar",
}
POINT_KINDS = ("grammaire", "signes", "sons", "usage")
PLACEMENT_KINDS = ("qcm", "lecture", "signes")
EXPLANATION_SEED_MAX = 400
# Un groupe de bilan = les points joués entre deux bilans.
BILAN_GROUP_SIZE = LANG_BILAN_EVERY - 1
ONBOARDING_PHRASES = 10


def _path(*parts: str) -> Path:
    return LANG_DATA_DIR.joinpath(*parts)


@lru_cache(maxsize=64)
def _read(path_str: str) -> tuple[str, object] | None:
    path = Path(path_str)
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8")
    return raw, json.loads(raw)


def load_json(*parts: str):
    """Contenu d'un fichier de nwol/data/lang/, ou None s'il n'existe pas."""
    got = _read(str(_path(*parts)))
    return got[1] if got else None


def source_version(*parts: str) -> str | None:
    """Empreinte du fichier : change dès qu'une relecture le modifie (D23)."""
    got = _read(str(_path(*parts)))
    return hashlib.sha256(got[0].encode("utf-8")).hexdigest()[:16] if got else None


def clear_cache() -> None:
    _read.cache_clear()


# ── Validateurs (S2 et équivalents) ───────────────────────────────────────────

def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_program(data, language: str) -> list[str]:
    """Invariants d'un programme : ids uniques et préfixés, ordre continu,
    CECR croissant, prérequis antérieurs, groupes de bilan par blocs de 6."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["le fichier n'est pas un objet JSON"]
    if data.get("language") != language:
        errors.append(f"language = {data.get('language')!r}, attendu {language!r}")
    points = data.get("points")
    if not isinstance(points, list) or not points:
        return errors + ["aucun point"]
    prefix = f"{LANG_ISO.get(language, language)}."
    seen: dict[str, int] = {}
    last_cefr = 0
    for i, p in enumerate(points, start=1):
        where = f"point n°{i}"
        if not isinstance(p, dict):
            errors.append(f"{where} : pas un objet")
            continue
        pid = p.get("id")
        where = f"point {pid or i}"
        if not _nonempty(pid) or not pid.startswith(prefix):
            errors.append(f"{where} : id absent ou sans le préfixe {prefix!r}")
        elif pid in seen:
            errors.append(f"{where} : id en double")
        if p.get("order") != i:
            errors.append(f"{where} : order = {p.get('order')!r}, attendu {i} (ordre continu)")
        cefr = p.get("cefr")
        if cefr not in LANG_CEFR_ORDER:
            errors.append(f"{where} : cefr invalide {cefr!r}")
        else:
            rank = LANG_CEFR_ORDER.index(cefr)
            if rank < last_cefr:
                errors.append(f"{where} : le niveau recule ({cefr} après {LANG_CEFR_ORDER[last_cefr]})")
            last_cefr = max(last_cefr, rank)
        if p.get("kind") not in POINT_KINDS:
            errors.append(f"{where} : kind invalide {p.get('kind')!r}")
        for field in ("title", "learner_goal", "notice", "dialogue_constraint", "explanation_seed"):
            if not _nonempty(p.get(field)):
                errors.append(f"{where} : {field} vide")
        if _nonempty(p.get("learner_goal")) and not p["learner_goal"].startswith("Peut "):
            errors.append(f"{where} : learner_goal doit être formulé « Peut … »")
        # Version anglaise, facultative (§ 14, n° 14) : affichée à un profil dont
        # la langue d'explication est l'anglais, le français sinon.
        for field in ("title_en", "learner_goal_en"):
            if field in p and not _nonempty(p.get(field)):
                errors.append(f"{where} : {field} vide")
        if _nonempty(p.get("learner_goal_en")) and not p["learner_goal_en"].startswith("Can "):
            errors.append(f"{where} : learner_goal_en doit être formulé « Can … »")
        if _nonempty(p.get("explanation_seed")) and len(p["explanation_seed"]) > EXPLANATION_SEED_MAX:
            errors.append(f"{where} : explanation_seed > {EXPLANATION_SEED_MAX} caractères")
        prereqs = p.get("prerequisites", [])
        if not isinstance(prereqs, list):
            errors.append(f"{where} : prerequisites n'est pas une liste")
        else:
            for req in prereqs:
                if req not in seen:
                    errors.append(f"{where} : prérequis {req!r} absent ou postérieur")
        expected_group = (i - 1) // BILAN_GROUP_SIZE + 1
        if p.get("bilan_group") != expected_group:
            errors.append(f"{where} : bilan_group = {p.get('bilan_group')!r}, attendu {expected_group}")
        formats = p.get("formats_allowed")
        if not isinstance(formats, list) or not formats:
            errors.append(f"{where} : formats_allowed vide")
        else:
            bad = [f for f in formats if f not in LANG_ALL_TEXT_FORMATS]
            if bad:
                errors.append(f"{where} : formats inconnus {bad}")
        if _nonempty(pid) and pid not in seen:
            seen[pid] = i
    return errors


def validate_placement(data, language: str, program_ids: set[str]) -> list[str]:
    """Test de niveau : clés écrites à la main, chaque item pointe un point du
    programme, difficulté croissante."""
    errors: list[str] = []
    if not isinstance(data, dict) or data.get("language") != language:
        return ["fichier absent ou language incorrect"]
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return ["aucun item"]
    seen: set[str] = set()
    last_rank = 0
    for i, it in enumerate(items, start=1):
        where = f"item {it.get('id') if isinstance(it, dict) else i}"
        if not isinstance(it, dict):
            errors.append(f"{where} : pas un objet")
            continue
        if not _nonempty(it.get("id")) or it["id"] in seen:
            errors.append(f"{where} : id absent ou en double")
        seen.add(it.get("id"))
        cefr = it.get("cefr")
        if cefr not in LANG_CEFR_ORDER:
            errors.append(f"{where} : cefr invalide")
        else:
            rank = LANG_CEFR_ORDER.index(cefr)
            if rank < last_rank:
                errors.append(f"{where} : difficulté décroissante")
            last_rank = max(last_rank, rank)
        if it.get("program_point") not in program_ids:
            errors.append(f"{where} : program_point {it.get('program_point')!r} hors programme")
        if it.get("kind") not in PLACEMENT_KINDS:
            errors.append(f"{where} : kind invalide")
        if not _nonempty(it.get("prompt")):
            errors.append(f"{where} : prompt vide")
        choices = it.get("choices")
        if not isinstance(choices, list) or len(choices) < 2 or not all(_nonempty(c) for c in choices):
            errors.append(f"{where} : au moins deux choix non vides")
        elif not isinstance(it.get("answer"), int) or not 0 <= it["answer"] < len(choices):
            errors.append(f"{where} : answer doit être l'index d'un choix")
        elif len({c.strip() for c in choices}) != len(choices):
            errors.append(f"{where} : choix en double")
        # Version anglaise d'un item rédigé en français : la clé reste l'index,
        # les choix traduits doivent donc garder le même ordre.
        if "prompt_en" in it and not _nonempty(it.get("prompt_en")):
            errors.append(f"{where} : prompt_en vide")
        if "choices_en" in it:
            en = it.get("choices_en")
            if not isinstance(en, list) or not isinstance(choices, list) or len(en) != len(choices) \
                    or not all(_nonempty(c) for c in en) or len({c.strip() for c in en}) != len(en):
                errors.append(f"{where} : choices_en doit traduire les choix un à un, dans le même ordre")
    return errors


def validate_onboarding(data, language: str) -> list[str]:
    from services.lang_arabic import vocalization_ratio

    errors: list[str] = []
    if not isinstance(data, dict) or data.get("language") != language:
        return ["fichier absent ou language incorrect"]
    phrases = data.get("phrases")
    if not isinstance(phrases, list) or len(phrases) != ONBOARDING_PHRASES:
        errors.append(f"il faut exactement {ONBOARDING_PHRASES} phrases de survie")
        phrases = phrases if isinstance(phrases, list) else []
    for i, ph in enumerate(phrases, start=1):
        if not isinstance(ph, dict) or not _nonempty(ph.get("target")) or not _nonempty(ph.get("translation")):
            errors.append(f"phrase {i} : target et translation requis")
            continue
        if language == "arabe":
            if not _nonempty(ph.get("vocalized")):
                errors.append(f"phrase {i} : vocalisation écrite à la main requise")
            elif vocalization_ratio(ph["vocalized"]) < LANG_AR_MIN_VOCALIZED_RATIO:
                errors.append(f"phrase {i} : vocalisation incomplète")
        if language == "mandarin" and not _nonempty(ph.get("pinyin")):
            errors.append(f"phrase {i} : pinyin vérifié requis")
    bible = data.get("default_bible")
    if not isinstance(bible, dict) or len(bible.get("characters") or []) < 3:
        errors.append("default_bible : au moins trois personnages")
    if language in ("mandarin", "arabe") and not isinstance(data.get("script_preview"), dict):
        errors.append("script_preview requis pour une écriture non latine")
    # Langue d'explication anglaise : une langue qui déclare ses paramètres de
    # prompt anglais doit fournir TOUT ce qu'un profil anglais voit ou envoie à
    # Gemma, sinon il recevrait du français au milieu de l'anglais.
    if "prompt_params_en" in data:
        params_en = data.get("prompt_params_en")
        if not isinstance(params_en, dict) or not all(_nonempty(params_en.get(k)) for k in ("language_label", "line_schema")):
            errors.append("prompt_params_en : language_label et line_schema requis")
        for i, ph in enumerate(phrases, start=1):
            if not isinstance(ph, dict):
                continue
            if not _nonempty(ph.get("translation_en")):
                errors.append(f"phrase {i} : translation_en requise (prompt_params_en présent)")
            if ph.get("note") and not _nonempty(ph.get("note_en")):
                errors.append(f"phrase {i} : note_en requise")
            # Une phrase cible propre à l'anglais porte ses propres aides.
            if "target_en" in ph:
                if language == "arabe" and (not _nonempty(ph.get("vocalized_en"))
                                            or vocalization_ratio(ph["vocalized_en"]) < LANG_AR_MIN_VOCALIZED_RATIO):
                    errors.append(f"phrase {i} : vocalized_en complète requise avec target_en")
                if language == "mandarin" and not _nonempty(ph.get("pinyin_en")):
                    errors.append(f"phrase {i} : pinyin_en requis avec target_en")
        bible_en = data.get("default_bible_en")
        if not isinstance(bible_en, dict) or len(bible_en.get("characters") or []) < 3:
            errors.append("default_bible_en : au moins trois personnages (prompt_params_en présent)")
        if isinstance(data.get("script_preview"), dict) and not isinstance(data.get("script_preview_en"), dict):
            errors.append("script_preview_en requis (prompt_params_en présent)")
    return errors


def validate_faux_amis(data, language: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict) or data.get("language") != language:
        return ["fichier absent ou language incorrect"]
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        return ["aucune entrée"]
    seen: set[str] = set()
    for e in entries:
        lemma = (e or {}).get("lemma")
        if not _nonempty(lemma) or not _nonempty(e.get("note")) or not _nonempty(e.get("looks_like")):
            errors.append(f"entrée {lemma!r} : lemma, looks_like et note requis")
        elif fold(lemma) in seen:
            errors.append(f"entrée {lemma!r} en double")
        else:
            seen.add(fold(lemma))
    return errors


def fold(text: str) -> str:
    """Minuscules sans accents (comparaison de lemmes)."""
    norm = unicodedata.normalize("NFD", (text or "").strip().lower())
    return "".join(c for c in norm if unicodedata.category(c) != "Mn")


# ── Lecture (services) ────────────────────────────────────────────────────────

def onboarding(language: str) -> dict:
    return load_json("onboarding", f"{language}.json") or {}


# ── Langue d'explication (§ 14, n° 14) ────────────────────────────────────────
# Les données sont écrites en français ; une version anglaise vit à côté, dans
# le même fichier, sous `<champ>_en` (ou `<bloc>_en` pour un bloc entier). Un
# profil dont la langue d'explication est l'anglais la reçoit, le français
# sinon — et le français quand la traduction manque encore.

def explain_languages(language: str) -> tuple[str, ...]:
    """Langues d'explication possibles pour une langue cible : le français
    toujours ; l'anglais si ses données le prévoient (`prompt_params_en`) et si
    la langue cible n'est pas l'anglais lui-même."""
    out = [LANG_EXPLAIN_LANGUAGES[0]]
    if "en" in LANG_EXPLAIN_LANGUAGES and LANG_ISO.get(language) != "en" and onboarding(language).get("prompt_params_en"):
        out.append("en")
    return tuple(out)


def localized(obj: dict | None, field: str, explain_lang: str):
    """Champ `field` d'une donnée écrite à la main, dans la langue d'explication."""
    obj = obj or {}
    if explain_lang == "en" and obj.get(f"{field}_en"):
        return obj[f"{field}_en"]
    return obj.get(field)


def onboarding_prompt_params(language: str, explain_lang: str) -> dict:
    """`prompt_params` de la langue, remplacés champ par champ par
    `prompt_params_en` pour une explication en anglais."""
    data = onboarding(language)
    params = dict(data.get("prompt_params") or {})
    if explain_lang == "en":
        params.update(data.get("prompt_params_en") or {})
    return params


def faux_amis(language: str) -> dict[str, dict]:
    data = load_json("helpers", f"faux_amis_{language}.json") or {}
    return {fold(e["lemma"]): e for e in data.get("entries") or [] if _nonempty(e.get("lemma"))}


def script_registry(name: str) -> dict:
    return load_json("scripts", f"{name}.json") or {}


# ── Injection en base (D23) ───────────────────────────────────────────────────

def _script_units() -> list[tuple[str, list[dict], str]]:
    """(script, unités, version) à injecter dans lang_script_units."""
    out: list[tuple[str, list[dict], str]] = []
    arabic = script_registry("arabic")
    if arabic:
        units = []
        for letter in arabic.get("letters") or []:
            units.append({**letter, "kind": "lettre", "display": letter["char"]})
        for mark in arabic.get("marks") or []:
            units.append({**mark, "kind": mark.get("kind", "voyelle"), "display": mark["char"]})
        out.append(("arabic", units, source_version("scripts", "arabic.json")))
    sounds = script_registry("mandarin_sounds")
    if sounds:
        units = []
        for kind, key in (("initiale", "initials"), ("finale", "finals"), ("ton", "tones")):
            for u in sounds.get(key) or []:
                units.append({**u, "kind": kind, "display": u.get("display") or u["pinyin"]})
        out.append(("mandarin_sounds", units, source_version("scripts", "mandarin_sounds.json")))
    components = script_registry("mandarin_components")
    if components:
        units = [{**c, "kind": "cle", "display": c["char"]} for c in components.get("components") or []]
        out.append(("mandarin_components", units, source_version("scripts", "mandarin_components.json")))
    return out


def seed_lang_reference() -> dict:
    """Réinjecte programmes, registres et tests de niveau quand leur fichier a
    changé. Jamais bloquant : un fichier invalide est journalisé et ignoré."""
    from db import lang_episode_db as store

    report: dict[str, str] = {}
    for language in LANG_PILOT_LANGUAGES:
        data = load_json("program", f"{language}.json")
        if data is None:
            report[f"program:{language}"] = "absent"
            continue
        version = source_version("program", f"{language}.json")
        errors = validate_program(data, language)
        if errors:
            logger.error("Programme %s invalide, non injecté : %s", language, errors[:5])
            report[f"program:{language}"] = "invalide"
            continue
        if store.reference_version("lang_program_points", "language", language) != version:
            store.replace_program(language, data["points"], version)
            logger.info("Programme %s injecté (%d points)", language, len(data["points"]))
        report[f"program:{language}"] = "ok"
        placement = load_json("placement", f"{language}.json")
        if placement is None:
            report[f"placement:{language}"] = "absent"
            continue
        pversion = source_version("placement", f"{language}.json")
        perrors = validate_placement(placement, language, {p["id"] for p in data["points"]})
        if perrors:
            logger.error("Test de niveau %s invalide, non injecté : %s", language, perrors[:5])
            report[f"placement:{language}"] = "invalide"
            continue
        if store.reference_version("lang_placement_items", "language", language) != pversion:
            store.replace_placement(language, placement["items"], pversion)
        report[f"placement:{language}"] = "ok"
    for script, units, version in _script_units():
        if store.reference_version("lang_script_units", "script", script) != version:
            store.replace_script_units(script, units, version)
        report[f"script:{script}"] = "ok"
    return report
