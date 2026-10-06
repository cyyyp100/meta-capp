# services/lang_episodes.py — Génération des épisodes du feuilleton (plan § 8).
#
# L'épisode N+1 est écrit PENDANT la séance N, en tâche de fond : une séance
# n'attend jamais Clikoda (principe 1). Le flux :
#
#   bible (une fois par langue)   arc (au démarrage, puis à chaque bilan)
#   épisode :  1. texte        -> validation (G4-G6, G9)
#              2. glossaire    -> validation (G7)
#              3. notes + point -> validation (G8)
#              -> calculs déterministes (G11-G13) -> status = ready
#
# Chaque appel est rejoué SEUL, avec la raison du refus, jusqu'à
# LANG_GEN_MAX_ATTEMPTS_PER_CALL ; au-delà l'épisode passe `failed`, la séance
# suivante se joue sans lui (relecture) et une nouvelle tentative part à la
# séance d'après. Tout échec de validation est journalisé dans
# `generation_json` (G10), avec les mesures réelles de chaque appel (G19).
from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from datetime import datetime

from config.settings import (
    LANG_AR_MIN_VOCALIZED_RATIO,
    LANG_ARC_LENGTH,
    LANG_EXPLANATION_MAX_CHARS,
    LANG_EXTRA_SPEAKER_SHARE,
    LANG_EXTRA_SPEAKERS_MAX,
    LANG_GEN_MAX_ATTEMPTS_PER_CALL,
    LANG_GLOSSARY_CHUNK,
    LANG_GLOSSARY_MAX_ENTRIES,
    LANG_GLOSSARY_MAX_MISSING,
    LANG_LINES_SLACK,
    LANG_MAX_UNITS_PER_EPISODE,
    LANG_MAX_UNITS_PER_LINE,
    LANG_NEW_WORDS_CHECK_MIN_LEXICON,
    LANG_NEW_WORDS_TOLERANCE,
    LANG_NOTE_MAX_CHARS,
    LANG_NOTES_PER_EPISODE,
    LANG_POINT_EXAMPLES,
    LANG_PREGEN_BUFFER,
    LANG_REPEAT_MAX_JACCARD,
    LANG_REPEAT_WINDOW,
    LANG_SUMMARY_MAX_CHARS,
    LANG_TEASER_MAX_CHARS,
    LANG_TITLE_MAX_CHARS,
    LANG_WORDS_SLACK,
    OLLAMA_BACKGROUND_QUEUE_WAIT_S,
)
from db import lang_episode_db as store
from db.lang_db import get_lang_profile_by_id
from llm import ollama_client as llm
from services import lang_arabic as arabic
from services import lang_mandarin as mandarin
from services import lang_progress as progress
from services.lang_inflight import InflightRegistry
from services.lang_latin import de_article, de_gender_conflict_pairs, faux_ami, is_transparent
from services.lang_static import LANG_ISO, localized, onboarding, onboarding_prompt_params
from services.lang_text import fold, jaccard, normalize_for_compare, segment, words
from services.llm_bridge import run_llm_sync

logger = logging.getLogger("services.lang_episodes")

# Génération en thread démon ; les tests la passent à False pour la jouer inline.
RUN_IN_BACKGROUND = True
# Banc d'évaluation (tools/lang_bench.py) : garder chaque sortie brute de Clikoda
# dans le journal, pour en faire des fixtures rejouées par les tests (V2).
KEEP_RAW = False
_GENERATIONS = InflightRegistry()

NARRATOR = "Narrateur"
# Le locuteur d'un récit, tel que le prompt anglais le nomme.
NARRATOR_EN = "Narrator"
# Marqueurs de français dans un texte cible latin : mots-outils fréquents en
# français et absents de la langue cible (« du » est allemand, « son » espagnol).
_FR_MARKERS = {
    "est", "et", "je", "nous", "vous", "pas", "avec", "dans", "c'est", "tres", "mais", "ou",
    "sont", "elle", "cette", "etre", "avoir", "qui", "aussi", "toujours", "maintenant", "oui",
    "une", "du", "au", "aux", "il", "ils", "leur", "petite", "quand",
}
_FR_MARKERS_EXCLUDED = {"allemand": {"du"}, "anglais": set(), "espagnol": set()}
# Anglicismes dans un texte espagnol ou allemand (mesuré au banc : une bible
# au personnage « jargon » en truffait chaque réplique).
_EN_MARKERS = {
    "the", "and", "you", "my", "your", "with", "this", "that", "what", "is", "are", "of", "cool",
    "okay", "game", "changer", "trendy", "content", "showcase", "business", "marketing", "networking",
    "branding", "pitch", "feedback", "meeting", "deadline",
}
# Mots-outils anglais : une traduction ou une note qui doit être en français
# et qui en porte au moins deux a été écrite en anglais (consigne système en
# anglais, document anglais…). Pas les anglicismes de `_EN_MARKERS` : « cool »,
# « content » ou « business » s'écrivent aussi en français.
_EN_FUNCTION_WORDS = {
    "the", "and", "you", "your", "with", "this", "that", "what", "is", "are", "of", "it", "we",
    "they", "have", "not", "to", "was", "were", "he", "she", "his", "her", "there", "for",
}
# Un travers de personnage qui porte sur la LANGUE contamine tous les textes.
_LINGUISTIC_TRAITS = ("anglicisme", "jargon", "grammaire", "grammatical", "vocabulaire", "mots compliqués",
                      "langue étrangère", "accent", "argot",
                      # la même chose dans une bible écrite en anglais
                      "anglicism", "grammar", "vocabulary", "big words", "foreign language", "slang")


class GenerationFailed(RuntimeError):
    pass


# ── Contexte d'une langue ─────────────────────────────────────────────────────

def prompt_params(language: str, explain_lang: str = "fr") -> dict:
    """Variantes de prompt propres à la langue (registre, règles d'écriture,
    forme d'une réplique), lues dans onboarding/<langue>.json — dans la langue
    d'explication du profil (`prompt_params_en` pour l'anglais)."""
    params = onboarding_prompt_params(language, explain_lang)
    params.setdefault("language_label", language)
    params.setdefault("line_schema", '{"speaker": "first name", "text": "line", "translation": "English translation"}'
                      if explain_lang == "en" else
                      '{"speaker": "prénom", "text": "réplique", "translation": "traduction française"}')
    params["explain_lang"] = explain_lang
    return params


def explain_lang_of(profile: dict) -> str:
    """Langue dans laquelle Clikoda écrit pour ce profil (v36, défaut français)."""
    return "en" if (profile or {}).get("explain_lang") == "en" else "fr"


def _tr(lang: str, fr: str, en: str) -> str:
    """Raison d'un refus dans la langue du prompt : elle est renvoyée telle
    quelle à Clikoda (`rejected`), qui ne doit pas changer de langue en route."""
    return en if lang == "en" else fr


def _leak_markers(explain_lang: str, text: str, language: str) -> list[str]:
    """Mots-outils de l'AUTRE langue d'explication dans un texte qui doit être
    écrit dans `explain_lang` (traduction, résumé, note, explication). Rien à
    chercher quand la langue cible EST cette autre langue : des notes en
    français sur l'anglais citent de l'anglais."""
    other = "fr" if explain_lang == "en" else "en"
    if LANG_ISO.get(language) == other:
        return []
    if explain_lang == "en":
        markers = _FR_MARKERS - _FR_MARKERS_EXCLUDED.get(language, set())
        return [w for w in (fold(x) for x in words(text)) if w in markers]
    # Sans repli : « thé » n'est pas « the ».
    return [w for w in (x.lower() for x in words(text)) if w in _EN_FUNCTION_WORDS]


def _written_in_other_language(explain_lang: str, text: str, language: str) -> bool:
    """Deux marqueurs au moins : un mot isolé peut être une citation."""
    return len(_leak_markers(explain_lang, text, language)) >= 2


# « 老李 (Lǎo Lǐ) », « Xiao Wang (小王) » : Clikoda double souvent un prénom de sa
# transcription (mesuré au banc mandarin : 9 textes sur 9 refusés, les répliques
# disant « 老李 » et la bible « 老李 (Lǎo Lǐ) »).
_NAME_GLOSS = re.compile(r"^\s*(.*?)\s*[(（]\s*(.*?)\s*[)）]\s*$")


def _name_parts(name: str) -> list[str]:
    m = _NAME_GLOSS.match(name or "")
    return [p for p in m.groups() if p] if m else [(name or "").strip()]


def _in_target_script(language: str, text: str) -> bool:
    fam = progress.family(language)
    if fam == "hanzi":
        return any(mandarin.is_han(c) for c in text)
    if fam == "arabe":
        return any(arabic.is_arabic_letter(c) for c in text)
    return True


def clean_character_name(language: str, name: str) -> str:
    """Le prénom tel qu'il s'écrit dans le texte : pour une écriture non latine,
    la partie écrite dans cette écriture ; sinon la partie hors parenthèses."""
    parts = _name_parts(name)
    native = [p for p in parts if _in_target_script(language, p)]
    return (native or parts)[0]


def _speaker_names(bible: dict) -> set[str]:
    names: set[str] = {fold(NARRATOR), fold(NARRATOR_EN)}
    for c in bible.get("characters") or []:
        if c.get("name"):
            names |= {fold(c["name"])} | {fold(p) for p in _name_parts(c["name"])}
    return names


def _llm(fn, params: dict, log: list[dict], metrics: list[dict], task: str):
    """Un appel LLM bloquant (thread de fond) ; les mesures vont dans `metrics`."""
    started = time.monotonic()
    try:
        # Tâche de fond : le budget de l'appel ne court qu'une fois parti chez
        # Ollama, pas pendant qu'il attend derrière le lecteur (§ 14, n° 6).
        return run_llm_sync(lambda ok, err: fn(params, ok, err, on_metrics=metrics.extend),
                            queue_wait_s=OLLAMA_BACKGROUND_QUEUE_WAIT_S)
    except Exception as exc:  # panne d'Ollama, timeout, JSON inexploitable
        log.append({"task": task, "ok": False, "errors": [f"appel : {exc}"[:300]],
                    "duration_s": round(time.monotonic() - started, 2)})
        return None


def _attempts(task: str, fn, build_params, validate, log: list[dict], metrics: list[dict]):
    """Rejoue un appel jusqu'à LANG_GEN_MAX_ATTEMPTS_PER_CALL ; chaque refus
    alimente le prompt suivant (`rejected`) et le journal (G10)."""
    rejected = ""
    for attempt in range(1, LANG_GEN_MAX_ATTEMPTS_PER_CALL + 1):
        result = _llm(fn, build_params(rejected), log, metrics, task)
        if result is None:
            continue
        value, errors = validate(result)
        entry = {"task": task, "attempt": attempt, "ok": not errors, "errors": errors[:8],
                 "excerpt": _excerpt(result)}
        if KEEP_RAW:
            entry["raw"] = result
        log.append(entry)
        if not errors:
            return value
        rejected = " ; ".join(errors[:5])
    raise GenerationFailed(f"{task} : {LANG_GEN_MAX_ATTEMPTS_PER_CALL} tentatives refusées")


def _excerpt(result) -> str:
    if isinstance(result, dict):
        if result.get("lines"):
            return str(result["lines"][0].get("text", ""))[:120]
        if result.get("entries"):
            return str(result["entries"][0])[:120]
        if result.get("point"):
            return str(result["point"].get("explanation", ""))[:120]
    return str(result)[:120]


# ── Bible et arc ──────────────────────────────────────────────────────────────

def ensure_bible(profile: dict, language: str, log: list[dict] | None = None,
                 metrics: list[dict] | None = None) -> dict:
    """La bible du feuilleton : générée une fois (centres d'intérêt de
    l'apprenant), bible par défaut de la langue si Clikoda échoue. Ses appels
    rejoignent le journal de l'épisode qui l'a déclenchée."""
    existing = store.get_latest_bible(profile["id"])
    if existing:
        return existing
    lang = explain_lang_of(profile)
    params = prompt_params(language, lang)
    interests = store.decode_profile(profile).get("interests") or []
    log = log if log is not None else []
    metrics = metrics if metrics is not None else []
    result = None
    for _ in range(LANG_GEN_MAX_ATTEMPTS_PER_CALL):
        result = _llm(llm.generate_lang_story_bible_async, {
            "language_label": params["language_label"], "interests": interests,
            "register": params.get("register", ""), "characters_min": 3, "characters_max": 4,
            "explain_lang": lang,
        }, log, metrics, "bible")
        problems = _bible_problems(result, language, lang) if result else []
        if result and not problems:
            log.append({"task": "bible", "ok": True, "errors": []})
            result["characters"] = [{**c, "name": clean_character_name(language, c.get("name") or "")}
                                    for c in result.get("characters") or []]
            break
        if result:
            log.append({"task": "bible", "ok": False, "errors": problems})
        result = None
    if result:
        store.save_bible(profile["id"], {**result, "interests": interests}, "gemma")
    else:
        default = localized(onboarding(language), "default_bible", lang) or {}
        store.save_bible(profile["id"], {**default, "interests": interests}, "defaut")
        logger.info("Bible par défaut pour %s (profil %s)", language, profile["id"])
    return store.get_latest_bible(profile["id"]) or {}


def _bible_problems(bible: dict, language: str | None = None, lang: str = "fr") -> list[str]:
    problems = []
    if len(bible.get("characters") or []) < 3:
        problems.append(_tr(lang, "moins de trois personnages", "fewer than three characters"))
    for c in bible.get("characters") or []:
        blob = fold(f"{c.get('role', '')} {c.get('trait', '')}")
        if any(fold(word) in blob for word in _LINGUISTIC_TRAITS):
            problems.append(_tr(lang, f"travers linguistique pour {c.get('name')} : un travers de caractère est attendu",
                                f"language quirk for {c.get('name')}: a character quirk is expected"))
        if language and not _in_target_script(language, c.get("name") or ""):
            # Le texte ne peut pas contenir de lettres latines : un prénom en
            # transcription seule ne serait jamais celui des répliques.
            problems.append(_tr(lang, f"prénom « {c.get('name')} » : écris-le dans l'écriture de la langue, sans transcription",
                                f"name \"{c.get('name')}\": write it in the script of the language, without transcription"))
    return problems


def arc_number(episode_n: int) -> int:
    return (int(episode_n) - 1) // LANG_ARC_LENGTH + 1


def ensure_arc(profile: dict, language: str, arc_n: int, bible: dict, log: list[dict] | None = None,
               metrics: list[dict] | None = None) -> dict:
    """Arc narratif de LANG_ARC_LENGTH épisodes ; repli déterministe (un temps
    fort par point à venir) si Clikoda échoue."""
    existing = store.get_arc(profile["id"], arc_n)
    if existing:
        return existing
    start_n = (arc_n - 1) * LANG_ARC_LENGTH + 1
    order = int(profile.get("program_order") or 0)
    upcoming = [p for p in progress.program(language) if p["order"] > order][:LANG_ARC_LENGTH]
    while len(upcoming) < LANG_ARC_LENGTH and progress.program(language):
        upcoming.append(progress.program(language)[-1])
    recent = [e["summary"] for e in store.played_episodes(profile["id"], limit=LANG_ARC_LENGTH) if e["summary"]]
    lang = explain_lang_of(profile)
    params = prompt_params(language, lang)
    log = log if log is not None else []
    metrics = metrics if metrics is not None else []
    beats = None
    best: list[dict] = []
    for _ in range(LANG_GEN_MAX_ATTEMPTS_PER_CALL):
        result = _llm(llm.generate_lang_story_arc_async, {
            "language_label": params["language_label"], "characters": bible.get("characters") or [],
            "setting": bible.get("setting", ""), "comic_springs": bible.get("comic_springs", ""),
            "recent": list(reversed(recent)), "explain_lang": lang,
            "points": [{"title": localized(p, "title", lang), "notice": p["notice"]} for p in upcoming],
        }, log, metrics, "arc")
        if result and len(result.get("beats") or []) > len(best):
            best = result["beats"][: len(upcoming)]
        if result and len(result.get("beats") or []) >= len(upcoming):
            beats = result["beats"][: len(upcoming)]
            log.append({"task": "arc", "ok": True, "errors": []})
            break
        if result:
            log.append({"task": "arc", "ok": False,
                        "errors": [f"{len(result.get('beats') or [])} temps forts au lieu de {len(upcoming)}"]})
    source = "gemma"
    if not beats and best:
        # Mesuré au banc : le modèle s'arrête souvent à trois temps forts sur six.
        # On garde ce qu'il a écrit et on complète, plutôt que de tout jeter.
        source = "gemma+defaut"
        beats = best + [_default_beat(i, p, lang) for i, p in enumerate(upcoming, start=1)][len(best):]
    if not beats:
        source = "defaut"
        beats = [_default_beat(i, p, lang) for i, p in enumerate(upcoming, start=1)]
    store.save_arc(profile["id"], arc_n, start_n, beats, source)
    return store.get_arc(profile["id"], arc_n) or {}


def _default_beat(n: int, point: dict, lang: str = "fr") -> dict:
    title = localized(point, "title", lang)
    return {"n": n, "beat": _tr(lang, f"L'histoire continue autour de : {title}.",
                                f"The story goes on around: {title}."), "hook": ""}


def beat_for(arc: dict, episode_n: int) -> dict:
    beats = arc.get("beats") or []
    if not beats:
        return {"beat": "", "hook": ""}
    idx = max(0, min(len(beats) - 1, int(episode_n) - int(arc.get("start_episode_n") or 1)))
    return beats[idx]


# ── Validateurs déterministes (G4-G9) ─────────────────────────────────────────

def _line_units(language: str, text: str) -> int:
    if progress.family(language) == "hanzi":
        return len(mandarin.han_chars(text))
    return len(words(text))


def _script_problems(language: str, text: str, lang: str = "fr") -> list[str]:
    fam = progress.family(language)
    has_han = any(mandarin.is_han(c) for c in text)
    has_arabic = any(arabic.is_arabic_letter(c) for c in text)
    has_latin = any("a" <= c.lower() <= "z" for c in text)
    if fam == "hanzi":
        if not has_han:
            return [_tr(lang, "texte sans caractères chinois", "text without Chinese characters")]
        if has_latin:
            return [_tr(lang, "lettres latines (pinyin ?) dans le texte chinois",
                        "Latin letters (pinyin?) in the Chinese text")]
        trad = mandarin.traditional_in(text)
        if trad:
            return [_tr(lang, f"caractères traditionnels interdits : {''.join(trad[:8])}",
                        f"traditional characters are not allowed: {''.join(trad[:8])}")]
        return []
    if fam == "arabe":
        if not has_arabic:
            return [_tr(lang, "texte sans lettres arabes", "text without Arabic letters")]
        if has_latin:
            return [_tr(lang, "lettres latines dans le texte arabe", "Latin letters in the Arabic text")]
        return []
    if has_han or has_arabic:
        return [_tr(lang, "écriture inattendue dans le texte", "unexpected script in the text")]
    folded = [fold(x) for x in words(text)]
    markers = [w for w in folded if w in _FR_MARKERS - _FR_MARKERS_EXCLUDED.get(language, set())]
    if len(markers) >= 2:
        return [_tr(lang, f"du français dans le texte cible ({', '.join(markers[:3])})",
                    f"French in the target text ({', '.join(markers[:3])})")]
    if language != "anglais":
        english = [w for w in folded if w in _EN_MARKERS]
        if english:
            return [_tr(lang, f"mots anglais interdits ({', '.join(english[:3])}) : écris tout dans la langue cible",
                        f"English words are not allowed ({', '.join(english[:3])}): write everything in the target language")]
    return []


def _arabic_problems(text: str, pausal: bool, lang: str = "fr") -> list[str]:
    problems = []
    if arabic.vocalization_ratio(text) < LANG_AR_MIN_VOCALIZED_RATIO:
        problems.append(_tr(lang, "vocalisation incomplète : chaque consonne doit porter sa voyelle, son sukūn ou sa šadda",
                            "incomplete vocalization: every consonant must carry its vowel, its sukūn or its šadda"))
    for word in words(text):
        for ch, marks in arabic.clusters(word):
            if len(marks & arabic.SHORT_VOWELS) > 1 or len(marks & arabic.TANWIN) > 1:
                problems.append(_tr(lang, f"voyelles contradictoires sur « {word} »",
                                    f"contradictory vowels on \"{word}\""))
                break
    if pausal:
        last = next((w for w in reversed(words(text)) if arabic.clusters(w)), "")
        cl = arabic.clusters(last)
        if cl:
            ch, marks = cl[-1]
            if marks & (arabic.SHORT_VOWELS | {arabic.DAMMATAN, arabic.KASRATAN}):
                problems.append(_tr(lang, f"forme pausale attendue en fin de phrase (« {last} » : sukūn sur la dernière lettre)",
                                    f"pausal form expected at the end of the sentence (\"{last}\": sukūn on the last letter)"))
    return problems[:3]


def _known(word: str, known: set[str]) -> bool:
    if word in known:
        return True
    if len(word) < 4:
        return False
    for k in known:
        common = 0
        for a, b in zip(word, k):
            if a != b:
                break
            common += 1
        if common >= max(4, min(len(word), len(k)) - 3):
            return True
    return False


def estimate_new_words(language: str, lines: list[dict], ctx: dict) -> int:
    """Mots (caractères pour le mandarin) du texte absents des acquis connus :
    estimation au stade du texte, pour pouvoir rejouer CET appel (G4). Les mots
    sont comparés par leur clé d'identité, accents compris : connaître « el »
    ne rend pas « él » connu (§ 14, n° 4)."""
    names = ctx.get("speakers") or set()
    if progress.family(language) == "hanzi":
        seen = ctx.get("seen_chars") or set()
        return len({c for ln in lines for c in mandarin.han_chars(ln["text"])} - seen)
    known = ctx.get("lexicon_forms") or set()
    fresh = set()
    for ln in lines:
        for w in words(ln["text"]):
            if fold(arabic.strip_harakat(w)) in names or w[:1].isupper() and fold(w) in names:
                continue
            key = _match_key(language, w)
            if not _known(key, known):
                fresh.add(key)
    return len(fresh)


def validate_text(language: str, result: dict, ctx: dict) -> tuple[dict, list[str]]:
    """G4 (bornes, traductions, locuteurs, langue, forme), G5 (mandarin),
    G6 (arabe), G9 (redites), estimation des mots nouveaux. Les raisons de
    refus sont écrites dans la langue du prompt (`ctx["explain_lang"]`)."""
    lang = ctx.get("explain_lang") or "fr"
    errors: list[str] = []
    # Une sortie coupée par num_predict perd sa ou ses dernières répliques
    # (traduction absente) : on les retire, et on juge le texte qui reste.
    lines = list(result.get("lines") or [])
    while lines and not lines[-1].get("translation"):
        lines.pop()
    if progress.family(language) == "arabe" and ctx.get("pausal", True):
        # A3 : la forme pausale se calcule, on ne la redemande pas à Clikoda.
        lines = [{**ln, "text": arabic.to_pausal(ln["text"])} if isinstance(ln.get("text"), str) else ln
                 for ln in lines]
    result = {**result, "lines": lines}
    params = ctx["params"]
    hanzi = progress.family(language) == "hanzi"
    unit = _tr(lang, "caractères", "characters") if hanzi else _tr(lang, "mots", "words")
    lo, hi = params["lines"]
    if not lo - LANG_LINES_SLACK[0] <= len(lines) <= hi + LANG_LINES_SLACK[1]:
        errors.append(_tr(lang, f"{len(lines)} répliques au lieu de {lo} à {hi}", f"{len(lines)} lines instead of {lo} to {hi}"))
    wpl = params.get("words_per_line")
    if wpl and lines:
        counts = [_line_units(language, ln["text"]) for ln in lines]
        avg = sum(counts) / len(counts)
        if avg < wpl[0] - LANG_WORDS_SLACK[0] or avg > wpl[1] + LANG_WORDS_SLACK[1]:
            errors.append(_tr(lang, f"répliques de {avg:.0f} {unit} en moyenne au lieu de {wpl[0]} à {wpl[1]}",
                              f"lines of {avg:.0f} {unit} on average instead of {wpl[0]} to {wpl[1]}"))
        too_long = [i + 1 for i, c in enumerate(counts) if c > 2 * wpl[1] + LANG_WORDS_SLACK[1]]
        if too_long:
            errors.append(_tr(lang, f"répliques trop longues : n° {', '.join(map(str, too_long[:4]))}",
                              f"lines too long: no. {', '.join(map(str, too_long[:4]))}"))
    elif lines:
        too_long = [i + 1 for i, ln in enumerate(lines) if _line_units(language, ln["text"]) > LANG_MAX_UNITS_PER_LINE]
        if too_long:
            errors.append(_tr(lang, f"répliques trop longues (une phrase par réplique) : n° {', '.join(map(str, too_long[:4]))}",
                              f"lines too long (one sentence per line): no. {', '.join(map(str, too_long[:4]))}"))
    total = sum(_line_units(language, ln["text"]) for ln in lines)
    cap = LANG_MAX_UNITS_PER_EPISODE[progress.family(language)]
    if total > cap:
        errors.append(_tr(lang, f"texte trop long ({total} {unit}, {cap} au plus) : raccourcis",
                          f"text too long ({total} {unit}, {cap} at most): shorten it"))
    speakers = ctx.get("speakers") or set()
    unknown = sorted({ln["speaker"] for ln in lines if fold(ln["speaker"]) not in speakers})
    extra_lines = sum(1 for ln in lines if fold(ln["speaker"]) not in speakers)
    if len(unknown) > LANG_EXTRA_SPEAKERS_MAX or (lines and extra_lines / len(lines) > LANG_EXTRA_SPEAKER_SHARE):
        errors.append(_tr(lang, f"locuteurs hors de la bible : {', '.join(unknown[:3])} (un seul personnage secondaire, "
                                "et peu de répliques)",
                          f"speakers outside the bible: {', '.join(unknown[:3])} (a single secondary character, "
                          "with few lines)"))
    missing_tr = [i + 1 for i, ln in enumerate(lines) if not ln.get("translation") or ln["translation"] == ln["text"]]
    if missing_tr:
        errors.append(_tr(lang, f"traduction française manquante : répliques {', '.join(map(str, missing_tr[:4]))}",
                          f"English translation missing: lines {', '.join(map(str, missing_tr[:4]))}"))
    # Langue d'explication : des traductions écrites dans l'autre langue
    # (consigne système, référence en français glissée dans un prompt anglais)
    # sont refusées. Jugé sur l'ensemble : une réplique courte n'a souvent
    # qu'un mot-outil.
    leaks = [(i + 1, _leak_markers(lang, ln.get("translation") or "", language)) for i, ln in enumerate(lines)]
    if sum(len(m) for _i, m in leaks) >= 3 or any(len(m) >= 2 for _i, m in leaks):
        wrong_tr = [str(i) for i, m in leaks if m]
        errors.append(_tr(lang, f"traductions qui ne sont pas en français : répliques {', '.join(wrong_tr[:4])}",
                          f"translations not written in English: lines {', '.join(wrong_tr[:4])}"))
    if ctx.get("format") == "dialogue" and len({fold(ln['speaker']) for ln in lines}) < 2:
        errors.append(_tr(lang, "un dialogue demande au moins deux personnages qui parlent",
                          "a dialogue needs at least two characters speaking"))
    for i, ln in enumerate(lines, start=1):
        if any(mark in ln["text"] for mark in ("*", "`", "#", "_")):
            errors.append(_tr(lang, f"réplique {i} : astérisques ou mise en forme interdits — aucun mot étranger à souligner, "
                                    "écris tout en langue cible",
                              f"line {i}: asterisks or formatting are not allowed — no foreign word to highlight, "
                              "write everything in the target language"))
        for problem in _script_problems(language, ln["text"], lang):
            errors.append(_tr(lang, f"réplique {i} : {problem}", f"line {i}: {problem}"))
            break
        if hanzi and not mandarin.tokens_rebuild(ln["text"], ln.get("tokens")):
            errors.append(_tr(lang, f"réplique {i} : les \"tokens\" ne recollent pas exactement \"text\"",
                              f"line {i}: the \"tokens\" do not rebuild \"text\" exactly"))
        if progress.family(language) == "arabe":
            for problem in _arabic_problems(ln["text"], ctx.get("pausal", True), lang):
                errors.append(_tr(lang, f"réplique {i} : {problem}", f"line {i}: {problem}"))
    for field, limit in (("title", LANG_TITLE_MAX_CHARS), ("summary", LANG_SUMMARY_MAX_CHARS),
                         ("teaser", LANG_TEASER_MAX_CHARS)):
        if not result.get(field):
            errors.append(_tr(lang, f"\"{field}\" manquant", f"\"{field}\" missing"))
        elif len(result[field]) > limit:
            errors.append(_tr(lang, f"\"{field}\" trop long ({len(result[field])} caractères, {limit} au plus)",
                              f"\"{field}\" too long ({len(result[field])} characters, {limit} at most)"))
    signature = f"{result.get('title', '')} {result.get('summary', '')}"
    if _written_in_other_language(lang, f"{signature} {result.get('teaser', '')}", language):
        errors.append(_tr(lang, "\"title\", \"summary\" et \"teaser\" doivent être écrits en français",
                          "\"title\", \"summary\" and \"teaser\" must be written in English"))
    names = {c for c in ctx.get("speaker_names") or []}
    for title, summary in ctx.get("recent") or []:
        if jaccard(signature, f"{title} {summary}", ignore=names) > LANG_REPEAT_MAX_JACCARD:
            errors.append(_tr(lang, f"trop proche d'un épisode déjà écrit (« {title} ») : invente une autre situation",
                              f"too close to an episode already written (\"{title}\"): invent another situation"))
            break
    if ctx.get("lexicon_size", 0) >= LANG_NEW_WORDS_CHECK_MIN_LEXICON:
        new_max = params["new_words"][1]
        if ctx.get("kind") == "respiration":
            from config.settings import LANG_RESPIRATION_NEW_WORDS_FACTOR
            new_max = max(1, round(new_max * LANG_RESPIRATION_NEW_WORDS_FACTOR))
        fresh = estimate_new_words(language, lines, ctx)
        if fresh > new_max * LANG_NEW_WORDS_TOLERANCE:
            errors.append(_tr(lang, f"environ {fresh} mots nouveaux pour l'apprenant, {new_max} au plus : réemploie des mots déjà vus",
                              f"about {fresh} new words for the learner, {new_max} at most: reuse words already seen"))
    return result, errors


def _match_key(language: str, text: str) -> str:
    """Clé d'IDENTITÉ d'un mot (glossaire, lexique, mots nouveaux).

    Minuscules, accents GARDÉS : « él » n'est pas « el », « schön » n'est pas
    « schon » (§ 14, n° 4 — le repli sans accents reliait « él » à l'entrée de
    « el » et affichait « le »). En arabe, sans voyelles brèves : la même forme
    écrite, vocalisée ou non, est le même mot. Exacte en mandarin."""
    fam = progress.family(language)
    if fam == "hanzi":
        return text.strip()
    if fam == "arabe":
        return fold(arabic.strip_harakat(text))
    return unicodedata.normalize("NFC", text.strip().replace("’", "'")).lower()


def _loose_key(language: str, text: str) -> str:
    """Clé TOLÉRANTE (sans accents) : ne sert qu'à rattraper une entrée de Clikoda
    dont l'accent manque, quand elle ne peut désigner qu'un seul mot demandé."""
    if progress.family(language) == "hanzi":
        return text.strip()
    return fold(arabic.strip_harakat(text))


def _line_word_keys(language: str, line: dict) -> list[str]:
    return [_match_key(language, t["text"]) for t in line["tokens"] if t.get("w")]


def glossary_request(language: str, lines: list[dict], ctx: dict) -> tuple[list[str], list[dict]]:
    """Mots du texte à faire gloser par Clikoda, et entrées déjà connues.

    Un mot dont la forme est au lexique de l'apprenant est glosé depuis le
    lexique (même traduction d'un épisode à l'autre, et un appel plus court) ;
    les autres, dans l'ordre d'apparition et sans les prénoms, sont demandés —
    au plus LANG_GLOSSARY_MAX_ENTRIES du palier. Deux mots qui ne diffèrent que
    par un accent sont deux mots. Un mot au lexique sans la prononciation que
    Clikoda doit écrire (inscrit avant qu'on la lui demande) est redemandé : il
    ne pourrait sinon jamais devenir une carte."""
    names = ctx.get("speakers") or set()
    known = {}
    for row in (ctx.get("lexicon") or {}).values():
        if pron_from_clikoda(language) and not row.get("pron"):
            continue
        known.setdefault(_match_key(language, row["form"]), row)
    tier = ctx["params"]["tier_index"]
    limit = LANG_GLOSSARY_MAX_ENTRIES[min(tier, len(LANG_GLOSSARY_MAX_ENTRIES) - 1)]
    asked: list[str] = []
    from_lexicon: list[dict] = []
    seen: set[str] = set()
    for ln in lines:
        for tok in ln["tokens"]:
            if not tok.get("w"):
                continue
            key = _match_key(language, tok["text"])
            if not key or key in seen or fold(arabic.strip_harakat(tok["text"])) in names or key.isdigit():
                continue
            seen.add(key)
            row = known.get(key)
            if row:
                from_lexicon.append({"form": tok["text"], "lemma": row["lemma"], "translation": row["translation"],
                                     "pos": row.get("pos") or "expression", "gender": row.get("gender"),
                                     "pron": row.get("pron"), "from_lexicon": True})
            elif len(asked) < limit:
                asked.append(tok["text"])
    return asked, from_lexicon


def _is_common_noun(entry: dict) -> bool:
    return (entry.get("pos") or "").startswith("nom") and entry.get("pos") != "nom propre"


def pron_from_clikoda(language: str) -> bool:
    """La prononciation d'une entrée vient-elle de Clikoda ? Oui pour les
    langues latines, dont rien ne la calcule ici ; le pinyin et la
    translittération arabe, eux, sont calculés (`enrich_glossary`)."""
    return progress.family(language) == "latin"


def check_glossary(language: str, result: dict, lines: list[dict], ctx: dict, requested: list[str]) -> dict:
    """G7, détaillé : `kept` (entrées valides, formes remplacées par le mot
    demandé), `missing` (mots demandés sans entrée valide), `errors` (raisons,
    dans la langue du prompt), `missing_error` (« il manque… », qui n'est pas
    bloquant : le lot est relancé).

    Allemand : un nom sans genre, ou dont le genre est contredit par un article
    sans ambiguïté du texte, est REFUSÉ seul — son mot redevient manquant et
    sera redemandé avec la raison, au lieu de faire échouer l'épisode entier
    (§ 14, n° 5). Langues latines : de même pour une entrée sans prononciation
    (une expression sans prononciation, facultative, est simplement écartée)."""
    lang = ctx.get("explain_lang") or "fr"
    needs_pron = pron_from_clikoda(language)
    errors: list[str] = []
    line_keys = [_line_word_keys(language, ln) for ln in lines]
    joined = [" ".join(keys) for keys in line_keys]
    wanted = {_match_key(language, w): w for w in requested}
    loose: dict[str, list[str]] = {}
    for key in wanted:
        loose.setdefault(_loose_key(language, key), []).append(key)
    kept: list[dict] = []
    seen: set[str] = set()
    for e in result.get("entries") or []:
        key = _match_key(language, e["form"])
        if key not in wanted or key in seen:
            # Accent oublié par Clikoda : rattrapé seulement s'il ne reste qu'UN
            # mot demandé qui puisse correspondre.
            candidates = [k for k in loose.get(_loose_key(language, e["form"]), []) if k not in seen]
            key = candidates[0] if len(candidates) == 1 else None
        if key is not None:
            seen.add(key)
            kept.append({**e, "form": wanted[key]})
    if language == "allemand":
        genderless = [e["form"] for e in kept if _is_common_noun(e) and not e.get("gender")]
        if genderless:
            errors.append(_tr(lang, f"genre manquant pour les noms : {', '.join(genderless[:6])}",
                              f"gender missing for the nouns: {', '.join(genderless[:6])}"))
        conflicts: list[tuple[str, str, str]] = []
        for ln in lines:
            conflicts += de_gender_conflict_pairs([t["text"] for t in ln["tokens"] if t.get("w")], kept)
        if conflicts:
            shown = ", ".join(f"{a} {w} ({g})" for a, w, g in conflicts[:4])
            errors.append(_tr(lang, f"genre contredit par l'article du texte : {shown}",
                              f"gender contradicted by the article in the text: {shown}"))
        refused = set(genderless) | {w for _a, w, _g in conflicts}
        if refused:
            kept = [e for e in kept if e["form"] not in refused]
            seen -= {_match_key(language, w) for w in refused}
    if needs_pron:
        unpronounced = [e["form"] for e in kept if not e.get("pron")]
        if unpronounced:
            errors.append(_tr(lang, f"prononciation manquante pour : {', '.join(unpronounced[:6])}",
                              f"pronunciation missing for: {', '.join(unpronounced[:6])}"))
            kept = [e for e in kept if e.get("pron")]
            seen -= {_match_key(language, w) for w in unpronounced}
    missing = [w for k, w in wanted.items() if k not in seen]
    missing_error = None
    if missing and len(missing) > max(1, len(wanted) // 10):
        missing_error = _tr(lang, f"il manque une entrée pour : {', '.join(missing[:10])} (une entrée par mot, dans l'ordre)",
                            f"an entry is missing for: {', '.join(missing[:10])} (one entry per word, in order)")
        errors.insert(0, missing_error)
    for e in result.get("expressions") or []:
        if needs_pron and not e.get("pron"):
            continue
        key = _match_key(language, e["form"])
        if " " in key and key not in seen and any(f" {key} " in f" {j} " for j in joined):
            seen.add(key)
            kept.append(e)
    return {"kept": kept, "missing": missing, "errors": errors, "missing_error": missing_error}


def validate_glossary(language: str, result: dict, lines: list[dict], ctx: dict,
                      requested: list[str]) -> tuple[list[dict], list[str]]:
    """G7 : une entrée par mot demandé, formes présentes dans le texte (jeton
    exact pour le mandarin), pas de doublon, genre des noms allemands."""
    check = check_glossary(language, result, lines, ctx, requested)
    return check["kept"], check["errors"]


def _in_line(language: str, needle: str, text: str) -> bool:
    if needle in text:
        return True
    if progress.family(language) == "arabe":
        return arabic.strip_harakat(needle) in arabic.strip_harakat(text)
    return False


def validate_notes_point(language: str, result: dict, lines: list[dict], explain_lang: str = "fr") -> tuple[dict, list[str]]:
    """G8 : ancres et exemples = sous-chaînes littérales du texte, distracteurs
    différents de la bonne réponse, longueurs bornées, notes et explication dans
    la langue d'explication."""
    lang = explain_lang
    errors: list[str] = []
    notes = []
    for n in result.get("notes") or []:
        li = n["line"] - 1
        if 0 <= li < len(lines) and _in_line(language, n["anchor"], lines[li]["text"]):
            if len(n["text"]) > LANG_NOTE_MAX_CHARS:
                errors.append(_tr(lang, f"note trop longue ({len(n['text'])} caractères, {LANG_NOTE_MAX_CHARS} au plus)",
                                  f"note too long ({len(n['text'])} characters, {LANG_NOTE_MAX_CHARS} at most)"))
                continue
            if _written_in_other_language(lang, n["text"], language):
                continue
            notes.append({**n, "line": li})
    if len(notes) < LANG_NOTES_PER_EPISODE[0]:
        errors.append(_tr(
            lang,
            f"{len(notes)} note(s) valide(s) sur {LANG_NOTES_PER_EPISODE[0]} au moins : chaque ancre doit être "
            "recopiée exactement de la réplique indiquée, chaque note écrite en français",
            f"{len(notes)} valid note(s) out of {LANG_NOTES_PER_EPISODE[0]} at least: each anchor must be "
            "copied exactly from the given line, each note written in English",
        ))
    point = dict(result.get("point") or {})
    if not point.get("observation"):
        errors.append(_tr(lang, "question d'observation manquante", "observation question missing"))
    if len(point.get("explanation") or "") > LANG_EXPLANATION_MAX_CHARS:
        errors.append(_tr(lang, f"explication trop longue ({len(point['explanation'])} caractères)",
                          f"explanation too long ({len(point['explanation'])} characters)"))
    if _written_in_other_language(lang, f"{point.get('observation') or ''} {point.get('explanation') or ''}", language):
        errors.append(_tr(lang, "la question et l'explication doivent être écrites en français",
                          "the question and the explanation must be written in English"))
    full = [ln["text"] for ln in lines]
    examples = [e for e in point.get("examples") or [] if any(_in_line(language, e, t) for t in full)]
    bad = [e for e in point.get("examples") or [] if e not in examples]
    if len(examples) < LANG_POINT_EXAMPLES[0]:
        errors.append(_tr(lang, f"exemples absents du texte, recopie-les exactement : {', '.join(bad[:3]) or '(aucun)'}",
                          f"examples not found in the text, copy them exactly: {', '.join(bad[:3]) or '(none)'}"))
    variants = []
    for v in point.get("variants") or []:
        if v["example"] not in examples:
            continue
        # Accents compris : « esta » est une forme fausse plausible de « está »
        # (le jeu « bonne forme » les distingue, § 7.7), pas un doublon.
        distractors = [d for d in v["distractors"] if normalize_for_compare(d) != normalize_for_compare(v["example"])]
        if distractors:
            variants.append({"example": v["example"], "distractors": list(dict.fromkeys(distractors))[:3]})
    point.update({"examples": examples[: LANG_POINT_EXAMPLES[1]], "variants": variants})
    return {"notes": notes[: LANG_NOTES_PER_EPISODE[1]], "point": point}, errors


# ── Calculs déterministes après validation (G11-G13) ──────────────────────────

def build_tokens(language: str, lines: list[dict]) -> list[dict]:
    out = []
    for ln in lines:
        if progress.family(language) == "hanzi":
            tokens = [{"text": t, "w": any(mandarin.is_han(c) or c.isalnum() for c in t)} for t in ln["tokens"]]
        else:
            tokens = segment(ln["text"])
        out.append({"speaker": ln["speaker"], "text": ln["text"], "translation": ln["translation"], "tokens": tokens})
    return out


def link_glossary(language: str, lines: list[dict], glossary: list[dict]) -> None:
    """Relie chaque jeton à son entrée de glossaire (`g`), expressions de
    plusieurs mots d'abord."""
    by_key: dict[str, int] = {}
    for gi, e in enumerate(glossary):
        for field in ("form", "lemma"):
            key = _match_key(language, e.get(field) or "")
            if key and key not in by_key:
                by_key[key] = gi
    multi = {k for k in by_key if " " in k}
    longest = max((len(k.split(" ")) for k in multi), default=1)
    for ln in lines:
        idx = [i for i, t in enumerate(ln["tokens"]) if t.get("w")]
        keys = [_match_key(language, ln["tokens"][i]["text"]) for i in idx]
        k = 0
        while k < len(idx):
            matched = False
            for size in range(min(longest, len(idx) - k), 1, -1):
                key = " ".join(keys[k:k + size])
                if key in multi:
                    for j in range(k, k + size):
                        ln["tokens"][idx[j]]["g"] = by_key[key]
                    k += size
                    matched = True
                    break
            if not matched:
                gi = by_key.get(keys[k])
                if gi is not None:
                    ln["tokens"][idx[k]]["g"] = gi
                k += 1


def compute_aids(language: str, lines: list[dict], episode_id: int | None) -> dict:
    """G11 (pinyin par jeton) et G12 (translittération, radical vocalisé comparé
    aux formes validées), parallèle à `lines`."""
    fam = progress.family(language)
    out_lines: list[list[dict]] = []
    sandhi: list[list[dict]] = []
    suspects = 0
    for ln in lines:
        row: list[dict] = []
        if fam == "hanzi":
            pys = [mandarin.token_pinyin(t["text"]) if t.get("w") else None for t in ln["tokens"]]
            for py in pys:
                row.append({"py": py["syllables"], "suspect": py["suspect"]} if py else {})
                suspects += int(bool(py and py["suspect"]))
            sandhi.append(mandarin.sandhi_notes([t["text"] for t in ln["tokens"]], pys))
        elif fam == "arabe":
            for t in ln["tokens"]:
                if not t.get("w"):
                    row.append({})
                    continue
                bare = arabic.strip_harakat(t["text"])
                stem = arabic.stem_vocalized(t["text"])
                forms = store.get_vocalized_forms(language, bare)
                valid = [f["stem_vocalized"] for f in forms if f["status"] == "valide"]
                reported = any(f["status"] == "signale" and f["stem_vocalized"] == stem for f in forms)
                suspect = bool(valid) and stem not in valid
                if not valid:
                    store.record_vocalized_candidate(language, bare, stem, episode_id)
                suspects += int(suspect)
                row.append({
                    "tr": arabic.transliterate_word(t["text"]), "bare": bare, "stem": stem,
                    "suspect": suspect or reported, "validated": valid[0] if suspect else None,
                })
            sandhi.append([])
        else:
            row = [{} for _ in ln["tokens"]]
            sandhi.append([])
        out_lines.append(row)
    return {
        "lines": out_lines, "sandhi": sandhi, "suspects": suspects,
        "pinyin_available": mandarin.PINYIN_AVAILABLE if fam == "hanzi" else None,
    }


def enrich_glossary(language: str, glossary: list[dict], lexicon: dict[str, dict],
                    explain_lang: str = "fr") -> list[dict]:
    """G13 et aides des entrées : prononciation calculée, mot transparent (par
    rapport à la traduction, dans la langue d'explication), faux-ami (pour un
    francophone), article allemand, clés du mandarin, mot nouveau ou non."""
    fam = progress.family(language)
    out = []
    for e in glossary:
        lemma = e.get("lemma") or e["form"]
        entry = {**e, "lemma": lemma, "new": lemma not in lexicon}
        if fam == "hanzi":
            py = mandarin.token_pinyin(e["form"])
            entry["pron"] = " ".join(s["mark"] for s in py["syllables"]) if py else None
            entry["components"] = [c["id"] for c in mandarin.components_in(e["form"])]
        elif fam == "arabe":
            entry["vocalized"] = e["form"]
            entry["pron"] = arabic.transliterate_word(e["form"])
        else:
            entry["transparent"] = is_transparent(lemma, e["translation"], explain_lang)
            fa = faux_ami(language, lemma, explain_lang)
            entry["faux_ami"] = fa.get("note") if fa else None
            if language == "allemand" and _is_common_noun(e):
                entry["article"] = de_article(e.get("gender"))
        out.append(entry)
    return out


# ── Pipeline ──────────────────────────────────────────────────────────────────

def _context(profile: dict, language: str, episode: dict, bible: dict) -> dict:
    lexicon = store.get_lexicon(profile["id"])
    lexicon_forms = {_match_key(language, r["form"]) for r in lexicon.values()} | {
        _match_key(language, r["lemma"]) for r in lexicon.values()
    }
    recent = [(e["title"], e["summary"]) for e in store.list_episodes(profile["id"], statuses=("ready", "played"),
                                                                       limit=LANG_REPEAT_WINDOW)
              if e["episode_n"] != episode["episode_n"]]
    from services.lang_scripts import HANZI_SCRIPT, seen_units

    iraab = _iraab_introduced(profile, language)
    return {
        "params": episode["params"], "kind": episode["kind"], "format": episode["format"],
        "speakers": _speaker_names(bible), "speaker_names": {c["name"] for c in bible.get("characters") or []},
        "lexicon": lexicon, "lexicon_forms": lexicon_forms, "lexicon_size": len(lexicon),
        "recent": recent, "pausal": not iraab, "explain_lang": explain_lang_of(profile),
        "seen_chars": seen_units(profile["id"], HANZI_SCRIPT) if progress.family(language) == "hanzi" else set(),
    }


def _iraab_introduced(profile: dict, language: str) -> bool:
    """A3 : forme pausale imposée jusqu'à l'introduction de l'iʿrāb au programme."""
    if language != "arabe":
        return False
    done = store.get_program_progress(profile["id"])
    return any("i3rab" in pid or "irab" in pid for pid in done)


def generate_episode(profile_id: int, episode_n: int) -> bool:
    """Écrit l'épisode `episode_n` (réservé au préalable, statut `queued`).
    Bloquant : appelé depuis un thread de fond, ou inline dans les tests."""
    profile = get_lang_profile_by_id(profile_id)
    episode = store.get_episode_by_n(profile_id, episode_n)
    if not profile or not episode or episode["status"] in ("ready", "played"):
        return bool(episode and episode["status"] in ("ready", "played"))
    profile = store.decode_profile(profile)
    language = profile["language"]
    started = time.monotonic()
    log: list[dict] = []
    metrics: list[dict] = []
    store.update_episode(episode["id"], status="generating")
    try:
        bible = ensure_bible(profile, language, log, metrics)
        arc = ensure_arc(profile, language, arc_number(episode_n), bible, log, metrics)
        ctx = _context(profile, language, episode, bible)
        point = store.get_point(language, episode["program_point_id"]) if episode["program_point_id"] else None
        lang = ctx["explain_lang"]
        pp = prompt_params(language, lang)
        point_title = localized(point, "title", lang) if point else ""
        recent_summaries = [e["summary"] for e in store.played_episodes(profile_id, limit=3, before_n=episode_n)]
        beat = beat_for(arc, episode_n)
        family = progress.family(language)

        def text_params(rejected: str) -> dict:
            return {
                "task": "lang_episode_text_hanzi" if family == "hanzi" else "lang_episode_text",
                "language_label": pp["language_label"], "episode_n": episode_n,
                "characters": bible.get("characters") or [], "setting": bible.get("setting", ""),
                "recent": list(reversed(recent_summaries)), "beat": beat.get("beat", ""),
                "format_rule": _format_rule(episode["format"], lang),
                "point_title": point_title,
                "point_constraint": point["dialogue_constraint"] if point else "",
                "constraints": progress.prompt_constraints(language, episode["params"], episode["kind"], lang),
                "lines_target": round(sum(episode["params"]["lines"]) / 2),
                "recycle": episode["params"].get("recycle") or [],
                "script_rules": pp.get("script_rules", ""), "line_schema": pp["line_schema"],
                "rejected": rejected, "explain_lang": lang,
            }

        text = _attempts("text", llm.generate_lang_episode_text_async, text_params,
                         lambda r: validate_text(language, r, ctx), log, metrics)
        lines = build_tokens(language, text["lines"])
        asked, known_entries = glossary_request(language, lines, ctx)

        asked_entries = _glossary_in_chunks(language, lines, ctx, asked, pp, log, metrics)
        glossary = _order_glossary(language, lines, asked_entries + known_entries)

        def notes_params(rejected: str) -> dict:
            return {
                "language_label": pp["language_label"],
                "lines": [(ln["text"], ln["translation"]) for ln in lines],
                "point_title": point_title, "point_notice": point["notice"] if point else "",
                "point_seed": point["explanation_seed"] if point else "",
                "notes_min": LANG_NOTES_PER_EPISODE[0], "notes_max": LANG_NOTES_PER_EPISODE[1],
                "examples_min": LANG_POINT_EXAMPLES[0], "examples_max": LANG_POINT_EXAMPLES[1],
                "note_max": LANG_NOTE_MAX_CHARS, "explanation_max": LANG_EXPLANATION_MAX_CHARS,
                "rejected": rejected, "explain_lang": lang,
            }

        notes_point = _attempts(
            "notes_point", llm.generate_lang_episode_notes_point_async, notes_params,
            lambda r: validate_notes_point(language, r, lines, lang), log, metrics,
        )
        glossary = enrich_glossary(language, glossary, ctx["lexicon"], lang)
        link_glossary(language, lines, glossary)
        aids = compute_aids(language, lines, episode["id"])
        new_count = sum(1 for g in glossary if g["new"] and not g.get("transparent"))
        store.update_episode(
            episode["id"], title=text["title"], summary=text["summary"], teaser=text["teaser"],
            lines=lines, glossary=glossary, notes=notes_point["notes"], point=notes_point["point"], aids=aids,
            status="ready", ready_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            generation={"calls": log, "metrics": metrics, "duration_s": round(time.monotonic() - started, 1),
                        "new_words": new_count, "beat": beat, "model": llm.OLLAMA_MODEL, "explain_lang": lang},
        )
        logger.info("Épisode %s prêt (profil %s, %.0f s)", episode_n, profile_id, time.monotonic() - started)
        return True
    except Exception as exc:
        logger.warning("Épisode %s non généré (profil %s) : %s", episode_n, profile_id, exc)
        store.update_episode(
            episode["id"], status="failed",
            generation={"calls": log, "metrics": metrics, "error": str(exc)[:300],
                        "duration_s": round(time.monotonic() - started, 1)},
        )
        return False


def _glossary_in_chunks(language: str, lines: list[dict], ctx: dict, asked: list[str], pp: dict,
                        log: list[dict], metrics: list[dict]) -> list[dict]:
    """Glossaire cumulatif : par lots de LANG_GLOSSARY_CHUNK mots ; chaque
    tentative ne redemande que les mots du lot encore sans entrée VALIDE. Une
    entrée refusée (nom allemand sans genre, ou au genre contredit par le
    texte) est redemandée avec sa raison, comme un mot manquant : elle ne fait
    plus échouer l'épisode au premier essai (§ 14, n° 5). Échec si plus de
    LANG_GLOSSARY_MAX_MISSING des mots demandés restent sans entrée."""
    lang = ctx.get("explain_lang") or "fr"
    collected: list[dict] = []
    missing_total: list[str] = []
    text_lines = [(ln["text"], ln["translation"]) for ln in lines]
    for start in range(0, len(asked), LANG_GLOSSARY_CHUNK):
        remaining = asked[start:start + LANG_GLOSSARY_CHUNK]
        rejected = ""
        for attempt in range(1, LANG_GEN_MAX_ATTEMPTS_PER_CALL + 1):
            result = _llm(llm.generate_lang_episode_glossary_async, {
                "language_label": pp["language_label"], "words": remaining, "lines": text_lines,
                "form_rule": pp.get("form_rule", ""), "rejected": rejected, "explain_lang": lang,
                "pron": pron_from_clikoda(language), "register": pp.get("register", ""),
            }, log, metrics, "glossary")
            if result is None:
                continue
            check = check_glossary(language, result, lines, ctx, remaining)
            have = {_match_key(language, c["form"]) for c in collected}
            collected += [e for e in check["kept"] if _match_key(language, e["form"]) not in have]
            remaining = check["missing"]
            refused = [e for e in check["errors"] if e != check["missing_error"]]
            entry = {"task": "glossary", "attempt": attempt, "ok": not remaining and not check["errors"],
                     "errors": check["errors"][:8], "excerpt": _excerpt(result)}
            if KEEP_RAW:
                entry["raw"] = result
            log.append(entry)
            if not remaining:
                break
            rejected = " ; ".join(refused[:3] + [_tr(lang, f"il manque encore : {', '.join(remaining[:12])}",
                                                     f"still missing: {', '.join(remaining[:12])}")])
        missing_total += remaining
    if asked and len(missing_total) > LANG_GLOSSARY_MAX_MISSING * len(asked):
        raise GenerationFailed(f"glossaire incomplet : {len(missing_total)} mots sur {len(asked)} sans entrée")
    return collected


def _order_glossary(language: str, lines: list[dict], entries: list[dict]) -> list[dict]:
    """Entrées dans l'ordre d'apparition du texte (expressions en fin)."""
    position: dict[str, int] = {}
    for ln in lines:
        for tok in ln["tokens"]:
            if tok.get("w"):
                position.setdefault(_match_key(language, tok["text"]), len(position))
    return sorted(entries, key=lambda e: position.get(_match_key(language, e["form"]), 10**6))


def _format_rule(fmt: str, explain_lang: str = "fr") -> str:
    from llm.prompts import LANG_FORMAT_RULES, LANG_FORMAT_RULES_EN

    rules = LANG_FORMAT_RULES_EN if explain_lang == "en" else LANG_FORMAT_RULES
    return rules.get(fmt, rules["dialogue"])


# ── Planification (G15-G16, G20) ──────────────────────────────────────────────

def trigger_generation(profile_id: int, episode_n: int) -> bool:
    """Lance la génération d'un épisode réservé ; une seule à la fois par
    (profil, épisode) (G15). Renvoie False si elle tournait déjà."""
    key = (profile_id, int(episode_n))
    if _GENERATIONS.is_running(key):
        return False

    def _job() -> None:
        if _GENERATIONS.claim(key) is not None:
            return
        try:
            generate_episode(profile_id, int(episode_n))
        except Exception:  # pragma: no cover - un thread de fond ne remonte rien
            logger.exception("Génération d'épisode interrompue")
        finally:
            _GENERATIONS.release(key)

    if RUN_IN_BACKGROUND:
        threading.Thread(target=_job, daemon=True, name=f"lang-episode-{profile_id}-{episode_n}").start()
    else:
        _job()
    return True


def is_generating(profile_id: int, episode_n: int | None = None) -> bool:
    if episode_n is not None:
        return _GENERATIONS.is_running((profile_id, int(episode_n)))
    return any(k[0] == profile_id for k in _GENERATIONS.running_keys())


def schedule_episode(profile: dict, language: str, episode_n: int, *, current: dict | None,
                     signals: dict | None) -> int:
    """Décide (P4) puis réserve et lance l'épisode `episode_n`. Idempotent : un
    épisode déjà réservé n'est pas redécidé ; un épisode `failed` est retenté."""
    existing = store.get_episode_by_n(profile["id"], episode_n)
    if existing:
        if existing["status"] in ("queued", "failed"):
            store.update_episode(existing["id"], status="queued")
            trigger_generation(profile["id"], episode_n)
        return existing["id"]
    decision = progress.next_episode_decision(profile, language, current=current, signals=signals,
                                              episode_n=episode_n)
    episode_id = store.create_episode(
        profile["id"], episode_n, kind=decision["kind"], program_point_id=decision["program_point_id"],
        format=decision["format"], ladder_step=decision["ladder_step"], params=decision["params"],
    )
    if decision["params"].get("forced"):
        store.update_profile_fields(profile["id"], force_respiration=0)
    store.update_profile_fields(profile["id"], ladder_step=decision["ladder_step"])
    trigger_generation(profile["id"], episode_n)
    return episode_id


def pregenerate_after(profile: dict, language: str, played: dict, signals: dict | None) -> list[int]:
    """Réserve les LANG_PREGEN_BUFFER épisodes suivant `played` (C9), avec les
    signaux du jour. Le premier épisode d'un nouvel arc attend le bilan, qui
    écrit l'arc d'abord (G16)."""
    from config.settings import LANG_BILAN_EVERY

    scheduled = []
    for k in range(1, LANG_PREGEN_BUFFER + 1):
        n = int(played["episode_n"]) + k
        if (n - 1) % (LANG_BILAN_EVERY - 1) == 0 and not store.get_arc(profile["id"], arc_number(n)):
            break
        scheduled.append(schedule_episode(profile, language, n, current=played, signals=signals))
        profile = store.decode_profile(get_lang_profile_by_id(profile["id"]))
    return scheduled


def requeue_stuck() -> int:
    """G20 : au démarrage, un épisode resté `generating` repart en file ; il
    sera relancé par la prochaine séance de sa langue."""
    count = store.requeue_stuck_generations()
    if count:
        logger.info("%d épisode(s) interrompu(s) remis en file", count)
    return count


def wait_idle(timeout: float = 10.0) -> None:
    """Tests : attend la fin des générations en cours."""
    deadline = time.monotonic() + timeout
    while _GENERATIONS.running_keys() and time.monotonic() < deadline:
        time.sleep(0.02)
