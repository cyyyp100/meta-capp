# services/lang_point_lesson.py — La leçon d'un point du programme (étape « leçon »).
#
# L'étape « leçon » part du texte (observer le point dans l'épisode), l'explique
# en entier (la leçon), puis fait s'entraîner. La leçon s'écrit UNE fois par
# point et par langue d'explication, partagée entre profils :
#
#   1. nwol/data/lang/lessons/<langue>.json, quand une leçon y est écrite à la
#      main pour ce point (relue ; validée par lang_static.validate_lessons_file) ;
#   2. sinon la base (`lang_point_lessons`), écrite par Clikoda dans le thread de
#      génération, APRÈS que l'épisode qui porte le point est prêt — son échec ne
#      touche jamais l'épisode (`ensure_point_lesson` ne lève jamais) ;
#   3. sinon un repli : titre et but du point, localisés, et l'explication écrite
#      avec l'épisode — jamais la matière française d'un point pour un profil
#      qui apprend en anglais.
#
# Ce qui se calcule ne se demande pas : pinyin et translittération des
# exemples, forme pausale de l'arabe, micro-items d'entraînement.
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
import unicodedata

from config.settings import (
    LANG_GEN_MAX_ATTEMPTS_PER_CALL,
    LANG_LESSON_CELL_MAX_CHARS,
    LANG_LESSON_EXAMPLES,
    LANG_LESSON_FORMS_MAX,
    LANG_LESSON_ITEMS,
    LANG_LESSON_MAX_ATTEMPTS,
    LANG_LESSON_NOTE_MAX_CHARS,
    LANG_LESSON_PITFALLS,
    LANG_LESSON_REMEMBER_MAX_CHARS,
    LANG_LESSON_RULE_MAX_CHARS,
    LANG_LESSON_TEXT_MAX_CHARS,
    LANG_LESSON_USES,
)
from db import lang_episode_db as store
from llm import ollama_client as llm
from services import lang_arabic as arabic
from services import lang_episodes as episodes
from services import lang_mandarin as mandarin
from services import lang_progress as progress
from services.lang_inflight import InflightRegistry
from services.lang_static import lessons_file, localized
from services.lang_text import segment

logger = logging.getLogger("services.lang_point_lesson")

_LESSONS = InflightRegistry()
_MARKDOWN = ("*", "`", "#", "_")
_FIELDS_HASHED = ("title", "title_en", "learner_goal", "learner_goal_en", "notice", "explanation_seed", "cefr")


def point_hash(point: dict) -> str:
    """Empreinte de ce qu'une leçon explique : un point réécrit dans
    nwol/data/lang/program/ fait réécrire sa leçon."""
    fields = {k: point.get(k) for k in _FIELDS_HASHED}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def lesson_pausal(language: str, point_id: str | None) -> bool:
    """Arabe : forme pausale (calculée) tant que le programme n'a pas introduit
    l'iʿrāb à ce point — la même règle que pour les épisodes, au point près,
    puisqu'une leçon est partagée par tous les profils."""
    if progress.family(language) != "arabe":
        return False
    points = progress.program(language)
    order = next((p["order"] for p in points if p["id"] == point_id), None)
    if order is None:
        return True
    return not any(("i3rab" in p["id"] or "irab" in p["id"]) and p["order"] <= order for p in points)


def lesson_for(language: str, point_id: str | None, explain_lang: str) -> dict | None:
    """{"lesson", "source"} : la leçon écrite à la main d'abord, puis celle de
    la base si elle est prête et explique le point tel qu'il est écrit."""
    if not point_id:
        return None
    entry = (lessons_file(language).get("lessons") or {}).get(point_id)
    if isinstance(entry, dict):
        # Pas de repli d'une langue sur l'autre : sans `lesson_en`, un profil qui
        # apprend en anglais reçoit la leçon de la base, jamais le texte français.
        lesson = entry.get("lesson_en" if explain_lang == "en" else "lesson")
        if isinstance(lesson, dict):
            return {"lesson": lesson, "source": "file"}
    row = store.get_point_lesson(language, point_id, explain_lang)
    if not row or row["status"] != "ready" or not row.get("lesson"):
        return None
    point = store.get_point(language, point_id)
    if not point or row["point_hash"] != point_hash(point):
        return None
    return {"lesson": row["lesson"], "source": "db"}


# ── Validation (bornes, écriture cible, langue d'explication) ─────────────────

def _clean(value) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip()


def validate_lesson(language: str, lesson, explain_lang: str = "fr", *, pausal: bool = True) -> tuple[dict, list[str]]:
    """Une leçon utilisable : règle et « à retenir » bornés et écrits dans la
    langue d'explication ; emplois, pièges et exemples en langue cible (écriture
    de la langue, vocalisation complète en arabe, forme pausale calculée) avec
    leur traduction ; un tableau de formes facultatif, borné ; aucune mise en
    forme. Les raisons de refus sont écrites dans la langue du prompt."""
    lang = explain_lang
    tr = episodes._tr
    if not isinstance(lesson, dict):
        return {}, [tr(lang, "leçon illisible", "unreadable lesson")]
    fam = progress.family(language)
    errors: list[str] = []

    def target(text) -> str:
        text = _clean(text)
        return arabic.to_pausal(text) if fam == "arabe" and pausal and text else text

    def check_target(label: str, text: str, *, vocalized: bool = True) -> None:
        problems = episodes._script_problems(language, text, lang)
        if fam == "arabe" and vocalized and not problems:
            problems = episodes._arabic_problems(text, pausal, lang)
        if problems:
            errors.append(f"{label} : {problems[0]}")

    def check_explained(label: str, text: str) -> None:
        if text and episodes._written_in_other_language(lang, text, language):
            errors.append(tr(lang, f"{label} : écris-le en français", f"{label}: write it in English"))

    def check_length(label: str, text: str, limit: int) -> None:
        if len(text) > limit:
            errors.append(tr(lang, f"{label} trop long ({len(text)} caractères, {limit} au plus)",
                             f"{label} too long ({len(text)} characters, {limit} at most)"))

    rule, remember = _clean(lesson.get("rule")), _clean(lesson.get("remember"))
    for field, value, limit in (("rule", rule, LANG_LESSON_RULE_MAX_CHARS),
                                ("remember", remember, LANG_LESSON_REMEMBER_MAX_CHARS)):
        if not value:
            errors.append(tr(lang, f"\"{field}\" manquant", f"\"{field}\" missing"))
        check_length(f"\"{field}\"", value, limit)
        check_explained(f"\"{field}\"", value)

    uses = []
    for u in lesson.get("uses") or []:
        if not isinstance(u, dict) or len(uses) >= LANG_LESSON_USES[1]:
            continue
        use, example, translation = _clean(u.get("use")), target(u.get("example")), _clean(u.get("translation"))
        if not use or not example:
            continue
        check_length(tr(lang, "un emploi", "a use"), use, LANG_LESSON_NOTE_MAX_CHARS)
        check_length(tr(lang, "un exemple d'emploi", "a use example"), example, LANG_LESSON_TEXT_MAX_CHARS)
        check_target(tr(lang, f"exemple d'emploi « {example[:40]} »", f"use example \"{example[:40]}\""), example)
        check_explained(tr(lang, "un emploi", "a use"), f"{use} {translation}")
        uses.append({"use": use, "example": example, "translation": translation})
    if len(uses) < LANG_LESSON_USES[0]:
        errors.append(tr(lang, f"{len(uses)} emploi(s) au lieu de {LANG_LESSON_USES[0]} à {LANG_LESSON_USES[1]}",
                         f"{len(uses)} use(s) instead of {LANG_LESSON_USES[0]} to {LANG_LESSON_USES[1]}"))

    pitfalls = []
    for pf in lesson.get("pitfalls") or []:
        if not isinstance(pf, dict) or len(pitfalls) >= LANG_LESSON_PITFALLS[1]:
            continue
        wrong, right, why = _clean(pf.get("wrong")), target(pf.get("right")), _clean(pf.get("why"))
        if not wrong or not right or wrong == right:
            continue
        for label, text in ((tr(lang, "un piège", "a pitfall"), wrong), (tr(lang, "un piège", "a pitfall"), right)):
            check_length(label, text, LANG_LESSON_TEXT_MAX_CHARS)
        check_length(tr(lang, "une explication de piège", "a pitfall explanation"), why, LANG_LESSON_NOTE_MAX_CHARS)
        # La forme fautive l'est exprès : son écriture seule est vérifiée.
        check_target(tr(lang, f"forme fautive « {wrong[:40]} »", f"wrong form \"{wrong[:40]}\""), wrong, vocalized=False)
        check_target(tr(lang, f"forme juste « {right[:40]} »", f"right form \"{right[:40]}\""), right)
        check_explained(tr(lang, "une explication de piège", "a pitfall explanation"), why)
        pitfalls.append({"wrong": wrong, "right": right, "why": why})

    examples = []
    for e in lesson.get("examples") or []:
        if not isinstance(e, dict) or len(examples) >= LANG_LESSON_EXAMPLES[1]:
            continue
        text, translation = target(e.get("text")), _clean(e.get("translation"))
        if not text:
            continue
        if not translation or translation == text:
            errors.append(tr(lang, f"traduction manquante pour l'exemple « {text[:40]} »",
                             f"translation missing for the example \"{text[:40]}\""))
        check_length(tr(lang, "un exemple", "an example"), text, LANG_LESSON_TEXT_MAX_CHARS)
        check_target(tr(lang, f"exemple « {text[:40]} »", f"example \"{text[:40]}\""), text)
        check_explained(tr(lang, "une traduction d'exemple", "an example translation"), translation)
        examples.append({"text": text, "translation": translation})
    if len(examples) < LANG_LESSON_EXAMPLES[0]:
        errors.append(tr(lang, f"{len(examples)} exemple(s) au lieu de {LANG_LESSON_EXAMPLES[0]} à {LANG_LESSON_EXAMPLES[1]}",
                         f"{len(examples)} example(s) instead of {LANG_LESSON_EXAMPLES[0]} to {LANG_LESSON_EXAMPLES[1]}"))

    forms = _clean_forms(lesson.get("forms"))
    if forms:
        long_cells = [c for c in forms["columns"] + [c for r in forms["rows"] for c in r] if len(c) > LANG_LESSON_CELL_MAX_CHARS]
        if long_cells:
            errors.append(tr(lang, f"tableau : une case = une forme, pas une phrase (« {long_cells[0][:30]}… »)",
                             f"table: one cell = one form, not a sentence (\"{long_cells[0][:30]}…\")"))
    texts = [rule, remember] + [v for u in uses for v in u.values()] + [v for p in pitfalls for v in p.values()] \
        + [v for e in examples for v in e.values()] + ((forms or {}).get("columns") or []) \
        + [c for r in (forms or {}).get("rows") or [] for c in r]
    if any(mark in text for text in texts for mark in _MARKDOWN):
        errors.append(tr(lang, "mise en forme interdite : ni astérisque, ni dièse, ni tiret bas",
                         "formatting is not allowed: no asterisk, no hash, no underscore"))
    cleaned = {"rule": rule, "forms": forms, "uses": uses, "pitfalls": pitfalls, "examples": examples,
               "remember": remember}
    return cleaned, errors


def _clean_forms(forms) -> dict | None:
    """Tableau borné à LANG_LESSON_FORMS_MAX (lignes en-tête compris, colonnes) :
    le surplus est coupé, une case trop longue est refusée par l'appelant."""
    if not isinstance(forms, dict):
        return None
    rows_max, cols_max = LANG_LESSON_FORMS_MAX
    columns = [_clean(c) for c in forms.get("columns") or []][:cols_max]
    rows = [[_clean(c) for c in r][:cols_max] for r in forms.get("rows") or [] if isinstance(r, list)][: rows_max - 1]
    rows = [r for r in rows if any(r)]
    if not rows or max(len(columns), *(len(r) for r in rows)) < 2:
        return None
    width = max(len(columns), *(len(r) for r in rows))
    return {"columns": (columns + [""] * width)[:width], "rows": [(r + [""] * width)[:width] for r in rows]}


# ── Écriture (thread de génération) ───────────────────────────────────────────

def ensure_point_lesson(language: str, point_id: str | None, explain_lang: str) -> str:
    """Écrit la leçon du point si elle manque, ou si le point a changé depuis.
    Ne lève JAMAIS : appelée après qu'un épisode est prêt, son échec ne doit
    pas le toucher. Renvoie ce qui s'est passé : « file » ou « db » (déjà là),
    « ready », « failed », « gave_up » (trop d'échecs pour ce point),
    « running » (déjà en cours ailleurs) ou « none » (pas de point)."""
    key = (language, point_id, explain_lang)
    try:
        if not point_id:
            return "none"
        found = lesson_for(language, point_id, explain_lang)
        if found:
            return found["source"]
        point = store.get_point(language, point_id)
        if not point:
            return "none"
        digest = point_hash(point)
        row = store.get_point_lesson(language, point_id, explain_lang)
        previous = int(row["attempts"] or 0) if row and row["point_hash"] == digest else 0
        if previous >= LANG_LESSON_MAX_ATTEMPTS:
            return "gave_up"
        if _LESSONS.claim(key) is not None:
            return "running"
        try:
            return _write_lesson(language, point, explain_lang, digest, previous)
        finally:
            _LESSONS.release(key)
    except Exception:
        logger.warning("Leçon du point %s non écrite", point_id, exc_info=True)
        return "failed"


def _write_lesson(language: str, point: dict, explain_lang: str, digest: str, previous: int) -> str:
    pp = episodes.prompt_params(language, explain_lang)
    pausal = lesson_pausal(language, point["id"])

    def params(rejected: str) -> dict:
        return {
            "language_label": pp["language_label"], "cefr": point["cefr"],
            "point_title": localized(point, "title", explain_lang),
            "learner_goal": localized(point, "learner_goal", explain_lang),
            "point_notice": point.get("notice", ""), "point_seed": point.get("explanation_seed", ""),
            "register": pp.get("register", ""), "writing_rules": pp.get("writing_rules", ""),
            "rule_max": LANG_LESSON_RULE_MAX_CHARS, "remember_max": LANG_LESSON_REMEMBER_MAX_CHARS,
            "forms_rows": LANG_LESSON_FORMS_MAX[0], "forms_cols": LANG_LESSON_FORMS_MAX[1],
            "uses_min": LANG_LESSON_USES[0], "uses_max": LANG_LESSON_USES[1],
            "pitfalls_max": LANG_LESSON_PITFALLS[1],
            "examples_min": LANG_LESSON_EXAMPLES[0], "examples_max": LANG_LESSON_EXAMPLES[1],
            "rejected": rejected, "explain_lang": explain_lang,
        }

    log: list[dict] = []
    metrics: list[dict] = []
    started = time.monotonic()
    try:
        lesson = episodes._attempts(
            "lesson", llm.generate_lang_point_lesson_async, params,
            lambda r: validate_lesson(language, r, explain_lang, pausal=pausal), log, metrics,
        )
        status = "ready"
    except episodes.GenerationFailed:
        lesson, status = None, "failed"
    calls = sum(1 for c in log if c.get("task") == "lesson") or LANG_GEN_MAX_ATTEMPTS_PER_CALL
    store.save_point_lesson(
        language, point["id"], explain_lang, status=status, lesson=lesson, point_hash=digest,
        model=llm.OLLAMA_MODEL, attempts=previous + calls,
        generation={"calls": log, "metrics": metrics, "duration_s": round(time.monotonic() - started, 1)},
    )
    logger.info("Leçon %s (%s) : %s en %.0f s", point["id"], explain_lang, status, time.monotonic() - started)
    return status


# ── Affichage et entraînement (assemblage de séance, aucun appel) ─────────────

def _pron(language: str, text: str) -> str | None:
    """Prononciation CALCULÉE d'une phrase en langue cible : pinyin, ou
    translittération de l'arabe vocalisé. Rien pour les langues latines."""
    fam = progress.family(language)
    if fam == "hanzi":
        py = mandarin.token_pinyin(text)
        return " ".join(s["mark"] for s in py["syllables"]) if py and py["syllables"] else None
    if fam == "arabe":
        return arabic.transliterate(text) or None
    return None


def _with_aids(language: str, lesson: dict) -> dict:
    out = json.loads(json.dumps(lesson))
    for u in out.get("uses") or []:
        u["pron"] = _pron(language, u.get("example") or "")
    for p in out.get("pitfalls") or []:
        p["pron"] = _pron(language, p.get("right") or "")
    for e in out.get("examples") or []:
        e["pron"] = _pron(language, e.get("text") or "")
    return out


def lesson_view(language: str, point_id: str | None, explain_lang: str, episode: dict | None = None) -> dict:
    """Ce que l'étape « leçon » affiche : le point (titre, but), l'explication
    écrite avec l'épisode, et la leçon avec ses prononciations calculées — ou,
    sans leçon, le repli : titre, but et explication de l'épisode, tous dans la
    langue d'explication du profil."""
    point = store.get_point(language, point_id or "") or {}
    found = lesson_for(language, point_id, explain_lang)
    return {
        "title": localized(point, "title", explain_lang) or "",
        "learner_goal": localized(point, "learner_goal", explain_lang) or "",
        "kind": point.get("kind"),
        "explanation": ((episode or {}).get("point") or {}).get("explanation", ""),
        "lesson": _with_aids(language, found["lesson"]) if found else None,
        "source": found["source"] if found else "fallback",
    }


def _order_tokens(language: str, text: str) -> list[str]:
    """Les morceaux à remettre en ordre : les mots (sans la ponctuation), ou les
    caractères d'une courte phrase chinoise."""
    if progress.family(language) == "hanzi":
        return mandarin.han_chars(text)
    return [t["text"] for t in segment(text) if t["w"]]


def lesson_items(language: str, lesson: dict | None, seed: int, prefix: str = "lecon.lesson") -> list[dict]:
    """LANG_LESSON_ITEMS micro-items DÉTERMINISTES tirés de la leçon : « la bonne
    forme » prise dans le tableau de formes ou dans un piège, « remets en ordre »
    un exemple. Corrigés par lang_games.grade comme les items du texte."""
    if not lesson:
        return []
    rng = random.Random(seed)
    table, traps, orders = [], [], []
    forms = lesson.get("forms") or {}
    rows = forms.get("rows") or []
    for c in range(1, len(forms.get("columns") or [])):
        column = [r[c] for r in rows if c < len(r) and r[c]]
        for r in rows:
            answer = r[c] if c < len(r) else ""
            others = list(dict.fromkeys(x for x in column if x != answer))
            if answer and len(others) >= 2:
                rng.shuffle(others)
                options = [answer, *others[:3]]
                rng.shuffle(options)
                table.append({"kind": "bonne_forme", "prompt": {"source": "forms", "cue": [r[0], forms["columns"][c]]},
                              "options": options, "expected": answer})
    for p in lesson.get("pitfalls") or []:
        options = [p["right"], p["wrong"]]
        rng.shuffle(options)
        traps.append({"kind": "bonne_forme", "prompt": {"source": "pitfall", "cue": []}, "options": options,
                      "expected": p["right"]})
    for e in lesson.get("examples") or []:
        order = _order_tokens(language, e["text"])
        if not 3 <= len(order) <= 8:
            continue
        shuffled = order[:]
        for _ in range(5):
            rng.shuffle(shuffled)
            if shuffled != order:
                break
        orders.append({"kind": "remettre_en_ordre", "prompt": {"translation": e.get("translation", "")},
                       "options": shuffled, "expected": order})
    for pool in (table, traps, orders):
        rng.shuffle(pool)
    items: list[dict] = []
    while len(items) < LANG_LESSON_ITEMS and (table or traps or orders):
        for pool in (table, traps, orders):
            if pool and len(items) < LANG_LESSON_ITEMS:
                items.append(pool.pop())
    for i, it in enumerate(items):
        it.update(ref=f"{prefix}.{it['kind']}.{i}", lexemes=[], units=[])
    return items
