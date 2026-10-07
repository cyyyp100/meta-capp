# services/lang_writing.py — L'expression écrite d'une séance (étape « expression »).
#
# Juste après la leçon, l'apprenant écrit quelques phrases : une consigne
# DÉTERMINISTE (tirée de la forme du texte et du palier, rendue dans sa langue
# d'explication), les mots du jour et les formes du point à employer. Il envoie
# et continue : Clikoda corrige EN ARRIÈRE-PLAN (priorité au-dessus des
# épisodes en file), la séance n'attend jamais. Si la correction arrive avant
# la clôture, son verdict devient une mesure de la séance ; sinon l'écran de
# fin, puis l'accueil, la montrent quand elle est là.
#
# Les contrôles calculés (longueur, écriture, mots employés) guident
# l'apprenant ; ils ne sont ni une mesure ni un score.
from __future__ import annotations

import logging
import threading
import time
import unicodedata
from datetime import datetime

from config.settings import (
    LANG_WRITING_BANK_WORDS,
    LANG_WRITING_ERROR_TYPES,
    LANG_WRITING_LENGTH,
    LANG_WRITING_MAX_CHARS,
    LANG_WRITING_MAX_ERRORS,
    LANG_WRITING_TARGET_WORDS,
)
from db import lang_episode_db as store
from db.lang_db import get_lang_profile_by_id
from i18n import t_in
from llm import ollama_client as llm
from services import lang_arabic as arabic
from services import lang_episodes as episodes
from services import lang_mandarin as mandarin
from services import lang_progress as progress
from services.lang_inflight import InflightRegistry
from services.lang_text import fold, words

logger = logging.getLogger("services.lang_writing")

# Correction en thread démon ; les tests la passent à False pour la jouer inline.
RUN_IN_BACKGROUND = True
_CORRECTIONS = InflightRegistry()
_CONTENT_POS = ("nom", "verbe", "adjectif", "adverbe")
STATUSES = ("pending", "correcting", "ready", "failed", "skipped")


class WritingError(ValueError):
    """Requête impossible (séance inconnue, close, sans expression écrite)."""


# ── La consigne (assemblage de séance, aucun appel) ───────────────────────────

def _tier(episode: dict) -> int:
    return int((episode.get("params") or {}).get("tier_index") or 0)


def _task_kind(episode: dict, speaker: str | None) -> str:
    """Le modèle de consigne, d'après la forme du texte et le palier :
    répondre, écrire un message, tenir le journal, décrire, imaginer la suite."""
    fmt = episode.get("format") or "dialogue"
    tier = _tier(episode)
    if fmt in ("dialogue", "sms"):
        if not speaker:
            return "decrire"
        return "repondre" if tier < 2 or int(episode.get("episode_n") or 0) % 2 else "suite"
    if fmt == "lettre":
        return "message" if speaker else "decrire"
    if fmt == "journal":
        return "journal"
    if fmt == "recette":
        return "decrire"
    return "decrire" if tier < 2 else "suite"


def _last_speaker(episode: dict) -> str | None:
    narrators = {fold(episodes.NARRATOR), fold(episodes.NARRATOR_EN)}
    for ln in reversed(episode.get("lines") or []):
        if ln.get("speaker") and fold(ln["speaker"]) not in narrators:
            return ln["speaker"]
    return None


def _word_entry(entry: dict) -> dict:
    lemma = entry.get("lemma") or entry.get("form")
    shown = f"{entry['article']} {lemma}" if entry.get("article") else (entry.get("vocalized") or lemma)
    return {"form": shown, "match": [lemma, entry.get("form") or lemma], "translation": entry.get("translation", "")}


def writing_task(language: str, episode: dict, explain_lang: str) -> dict:
    """La consigne de l'expression écrite, déterministe : son modèle, son texte
    dans la langue d'explication, les mots du jour et les formes du point à
    employer, la longueur demandée et une banque de mots."""
    fam = progress.family(language)
    tier = min(_tier(episode), len(LANG_WRITING_LENGTH[fam]) - 1)
    lo, hi = LANG_WRITING_LENGTH[fam][tier]
    unit = "chars" if fam == "hanzi" else "words"
    speaker = _last_speaker(episode)
    kind = _task_kind(episode, speaker)
    length = t_in(explain_lang, f"lang.writing.length.{unit}", min=lo, max=hi)
    gloss = [g for g in episode.get("glossary") or [] if (g.get("pos") or "") != "nom propre"]
    content = [g for g in gloss if (g.get("pos") or "") in _CONTENT_POS]
    fresh = [g for g in content if g.get("new") and not g.get("transparent")]
    chosen: list[dict] = []
    for g in fresh + content:
        if len(chosen) >= LANG_WRITING_TARGET_WORDS:
            break
        if all((g.get("lemma") or g["form"]) != (c.get("lemma") or c["form"]) for c in chosen):
            chosen.append(g)
    taken = {c.get("lemma") or c["form"] for c in chosen}
    bank = []
    for g in content + gloss:
        lemma = g.get("lemma") or g["form"]
        if lemma not in taken and len(bank) < LANG_WRITING_BANK_WORDS:
            taken.add(lemma)
            bank.append(_word_entry(g))
    use_words = [_word_entry(g) for g in chosen]
    forms = list(dict.fromkeys((episode.get("point") or {}).get("examples") or []))[:2]
    prompt = t_in(explain_lang, f"lang.writing.task.{kind}", speaker=speaker or "", length=length)
    return {
        "kind": kind, "prompt": prompt, "speaker": speaker, "use_words": use_words, "use_forms": forms,
        "length": {"min": lo, "max": hi, "unit": unit}, "bank": bank, "tier_index": tier,
        "explain_lang": explain_lang, "max_chars": LANG_WRITING_MAX_CHARS,
    }


# ── Contrôles calculés ────────────────────────────────────────────────────────

def text_length(language: str, text: str) -> int:
    """Mots, ou caractères chinois pour le mandarin."""
    if progress.family(language) == "hanzi":
        return len(mandarin.han_chars(text))
    return len(words(text))


def _keys(language: str, text: str) -> list[str]:
    return [episodes._match_key(language, w) for w in words(text)]


def _uses_word(language: str, text: str, entry: dict) -> bool:
    """Le mot du jour est employé : tel quel ou fléchi (même début), sans ses
    voyelles brèves en arabe, comme sous-chaîne en mandarin."""
    fam = progress.family(language)
    candidates = [m for m in entry.get("match") or [] if m]
    if fam == "hanzi":
        return any(m in text for m in candidates)
    if fam == "arabe":
        bare = [arabic.strip_harakat(w) for w in words(text)]
        return any(arabic.strip_harakat(m) in w for m in candidates for w in bare)
    known = {episodes._match_key(language, m) for m in candidates}
    index = episodes._prefix_index(known)
    return any(episodes._known(k, known, index) for k in _keys(language, text))


def _uses_form(language: str, text: str, form: str) -> bool:
    def norm(x: str) -> str:
        x = unicodedata.normalize("NFC", x).casefold()
        x = arabic.strip_harakat(x) if progress.family(language) == "arabe" else x
        return " ".join(x.split())
    return norm(form) in norm(text)


def _script_check(language: str, text: str, explain_lang: str) -> dict:
    """L'écriture de la langue : du pinyin à la place des caractères, des lettres
    latines dans un texte arabe… Signalé, jamais refusé."""
    if not text:
        return {"ok": True, "problem": None}
    problems = episodes._script_problems(language, text, explain_lang)
    return {"ok": not problems, "problem": problems[0] if problems else None}


def checks(language: str, text: str, task: dict, explain_lang: str = "fr") -> dict:
    """Longueur, écriture, mots et formes employés. Une liste de contrôle pour
    l'apprenant, jamais une note."""
    length = task.get("length") or {}
    n = text_length(language, text)
    return {
        "length": {"value": n, "min": length.get("min"), "max": length.get("max"),
                   "unit": length.get("unit"), "ok": n >= int(length.get("min") or 0)},
        "script": _script_check(language, text, explain_lang),
        "words_used": [{"form": w["form"], "used": _uses_word(language, text, w)} for w in task.get("use_words") or []],
        "forms_used": [{"form": f, "used": _uses_form(language, text, f)} for f in task.get("use_forms") or []],
    }


def _in_explanation_language(language: str, text: str, explain_lang: str) -> bool:
    """L'apprenant a écrit dans SA langue (français, anglais) et non dans celle
    qu'il apprend : une correction n'aurait rien à corriger. Un texte qui a des
    caractères chinois ou des lettres arabes n'en est pas ; du pinyin non plus
    (il sera corrigé). Jugé sur les mots-outils de la langue d'explication, à
    partir d'un quart des mots : un mot isolé peut être une citation."""
    if any(mandarin.is_han(c) or arabic.is_arabic_letter(c) for c in text):
        return False
    if explain_lang == "en":
        marks = [w for w in (x.lower() for x in words(text)) if w in episodes._EN_FUNCTION_WORDS]
    else:
        excluded = episodes._FR_MARKERS_EXCLUDED.get(language, set())
        marks = [w for w in (fold(x) for x in words(text)) if w in episodes._FR_MARKERS - excluded]
    return len(marks) >= max(2, round(0.25 * len(words(text))))


# ── Envoi (la séance continue aussitôt) ───────────────────────────────────────

def _run_and_task(run_id: int) -> tuple[dict, dict, dict]:
    run = store.get_run(run_id)
    if not run:
        raise WritingError("séance introuvable")
    step = next((s for s in (run.get("plan") or {}).get("steps") or [] if s.get("kind") == "expression"), None)
    if not step:
        raise WritingError("pas d'expression écrite dans cette séance")
    return run, step, step.get("task") or {}


def submit(run_id: int, text: str) -> dict:
    """Enregistre l'expression écrite de la séance (une seule : un second envoi
    rend la première) et lance sa correction en arrière-plan. Normalisée en NFC,
    coupée à LANG_WRITING_MAX_CHARS. Sautée seulement si elle est vide ou écrite
    dans la langue d'explication."""
    run, step, task = _run_and_task(run_id)
    existing = store.get_writing_for_run(run_id)
    if existing:
        return writing_view(existing)
    if run["status"] != "in_progress":
        raise WritingError("séance close")
    language = (run.get("plan") or {}).get("language")
    explain_lang = task.get("explain_lang") or "fr"
    text = unicodedata.normalize("NFC", text or "").strip()[:LANG_WRITING_MAX_CHARS]
    skipped = not text or _in_explanation_language(language, text, explain_lang)
    writing_id = store.create_writing(
        run["profile_id"], run_id, step.get("episode_ref"), task=task, text=text,
        checks=checks(language, text, task, explain_lang) if text else None,
        status="skipped" if skipped else "pending",
    )
    if not skipped:
        schedule_correction(writing_id)
    return writing_view(store.get_writing(writing_id))


def writing_view(writing: dict | None) -> dict:
    if not writing:
        raise WritingError("expression écrite introuvable")
    return {
        "id": writing["id"], "run_id": writing.get("run_id"), "status": writing["status"],
        "text": writing.get("text") or "", "task": writing.get("task") or {}, "checks": writing.get("checks"),
        "feedback": writing.get("feedback") if writing["status"] == "ready" else None,
        "corrected_at": writing.get("corrected_at"), "seen": bool(writing.get("seen_at")),
    }


def get(writing_id: int) -> dict:
    return writing_view(store.get_writing(writing_id))


def mark_seen(writing_id: int) -> dict:
    writing = store.get_writing(writing_id)
    if not writing:
        raise WritingError("expression écrite introuvable")
    if not writing.get("seen_at") and writing["status"] == "ready":
        store.update_writing(writing_id, seen_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return {"ok": True}


def unseen_for(profile_id: int) -> dict | None:
    """La dernière correction arrivée après sa séance, pas encore vue (accueil)."""
    writing = store.latest_unseen_writing(profile_id)
    return {"id": writing["id"], "run_id": writing.get("run_id")} if writing else None


def run_measure(run_id: int) -> str | None:
    """Le verdict de la correction, si elle est prête : la seule mesure que
    l'expression écrite donne à la séance."""
    writing = store.get_writing_for_run(run_id)
    if not writing or writing["status"] != "ready":
        return None
    verdict = (writing.get("feedback") or {}).get("verdict")
    return verdict if verdict in ("correct", "partial", "incorrect") else None


# ── Correction (arrière-plan) ─────────────────────────────────────────────────

def schedule_correction(writing_id: int) -> bool:
    """Une correction à la fois par expression écrite ; jamais attendue."""
    if _CORRECTIONS.is_running(writing_id):
        return False

    def _job() -> None:
        if _CORRECTIONS.claim(writing_id) is not None:
            return
        try:
            correct(writing_id)
        except Exception:  # pragma: no cover - un thread de fond ne remonte rien
            logger.exception("Correction d'expression écrite interrompue")
        finally:
            _CORRECTIONS.release(writing_id)

    if RUN_IN_BACKGROUND:
        threading.Thread(target=_job, daemon=True, name=f"lang-writing-{writing_id}").start()
    else:
        _job()
    return True


def _flat(passage: str) -> str:
    """Un passage comparable : NFC, espaces réduits ; la casse compte (« elena »
    → « Elena » est une vraie correction)."""
    return " ".join(unicodedata.normalize("NFC", passage).split())


def _locate(text: str, needle: str) -> str | None:
    """Le passage tel qu'il est écrit dans le texte : exact, ou retrouvé à la
    casse et aux espaces près (un petit modèle les normalise souvent)."""
    if needle and needle in text:
        return needle
    folded = _flat(needle).casefold()
    if not folded:
        return None
    flat = unicodedata.normalize("NFC", text)
    lowered = flat.casefold()
    start = lowered.find(folded)
    if start < 0 or len(lowered) != len(flat):
        return None
    return flat[start:start + len(folded)]


def validate_feedback(language: str, result: dict, text: str, explain_lang: str = "fr") -> tuple[dict, list[str]]:
    """Une correction utilisable : chaque `original` est un passage EXACT du
    texte (retrouvé à la casse près, sinon refusé), son type d'erreur vient du
    vocabulaire hérité, le texte corrigé est écrit dans l'écriture de la langue,
    les explications dans la langue d'explication ; LANG_WRITING_MAX_ERRORS
    erreurs au plus (les premières, les plus importantes). Une « erreur » dont
    la correction recopie l'original est écartée sans relance."""
    lang = explain_lang
    tr = episodes._tr
    errors: list[str] = []
    kept = []
    for e in (result.get("errors") or [])[:LANG_WRITING_MAX_ERRORS]:
        if _flat(e.get("original") or "") == _flat(e.get("correction") or ""):
            continue  # « X → X » : rien n'est corrigé, l'erreur ne s'affiche pas
        original = _locate(text, e.get("original") or "")
        if original is None:
            errors.append(tr(lang, f"« {e.get('original', '')[:40]} » n'est pas dans le texte de l'apprenant : recopie le passage exactement",
                             f"\"{e.get('original', '')[:40]}\" is not in the learner's text: copy the passage exactly"))
            continue
        if e.get("error_type") not in LANG_WRITING_ERROR_TYPES:
            e = {**e, "error_type": "vocabulaire"}
        if episodes._written_in_other_language(lang, e.get("explanation") or "", language):
            errors.append(tr(lang, "les explications doivent être écrites en français",
                             "the explanations must be written in English"))
        kept.append({**e, "original": original})
    corrected = unicodedata.normalize("NFC", result.get("corrected") or "").strip()
    problems = episodes._script_problems(language, corrected, lang) if corrected else [
        tr(lang, "texte corrigé manquant", "corrected text missing")]
    if problems:
        errors.append(tr(lang, f"texte corrigé : {problems[0]}", f"corrected text: {problems[0]}"))
    if episodes._written_in_other_language(lang, result.get("praise") or "", language):
        errors.append(tr(lang, "\"praise\" doit être écrit en français", "\"praise\" must be written in English"))
    verdict = result.get("verdict")
    if verdict == "correct" and kept:
        verdict = "partial"  # des erreurs relevées : le texte n'était pas sans faute
    return {"verdict": verdict, "errors": kept, "corrected": corrected,
            "praise": (result.get("praise") or "").strip()}, errors


def correct(writing_id: int) -> str:
    """Corrige une expression écrite (thread de fond) : `pending` → `correcting`
    → `ready` | `failed`. Renvoie le statut final."""
    writing = store.get_writing(writing_id)
    if not writing or writing["status"] not in ("pending", "correcting"):
        return (writing or {}).get("status") or "missing"
    store.update_writing(writing_id, status="correcting")
    profile = store.decode_profile(get_lang_profile_by_id(writing["profile_id"]) or {})
    language = profile.get("language")
    task = writing.get("task") or {}
    explain_lang = task.get("explain_lang") or episodes.explain_lang_of(profile)
    pp = episodes.prompt_params(language, explain_lang)
    text = writing.get("text") or ""
    from llm.schema_json import WRITING_ERROR_TYPES_EN

    error_types = [WRITING_ERROR_TYPES_EN[t] for t in LANG_WRITING_ERROR_TYPES] if explain_lang == "en" \
        else list(LANG_WRITING_ERROR_TYPES)
    use = ", ".join(w["form"] for w in task.get("use_words") or [])
    instruction = task.get("prompt", "") + (" " + t_in(explain_lang, "lang.writing.task.use", words=use) if use else "")

    def params(rejected: str) -> dict:
        return {
            "language_label": pp["language_label"], "cefr": progress.current_cefr(language, profile.get("program_order") or 0),
            "task": instruction, "text": text, "writing_rules": pp.get("writing_rules", ""),
            "errors_max": LANG_WRITING_MAX_ERRORS, "error_types": error_types,
            "rejected": rejected, "explain_lang": explain_lang,
        }

    log: list[dict] = []
    metrics: list[dict] = []
    started = time.monotonic()
    try:
        feedback = episodes._attempts(
            "writing", llm.generate_lang_writing_feedback_async, params,
            lambda r: validate_feedback(language, r, text, explain_lang), log, metrics,
        )
    except episodes.GenerationFailed:
        store.update_writing(writing_id, status="failed", generation={
            "calls": log, "metrics": metrics, "duration_s": round(time.monotonic() - started, 1),
            "model": llm.OLLAMA_MODEL})
        logger.info("Expression écrite %s : correction impossible", writing_id)
        return "failed"
    store.update_writing(
        writing_id, status="ready", feedback=feedback, corrected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        generation={"calls": log, "metrics": metrics, "duration_s": round(time.monotonic() - started, 1),
                    "model": llm.OLLAMA_MODEL},
    )
    logger.info("Expression écrite %s corrigée en %.0f s", writing_id, time.monotonic() - started)
    return "ready"


def requeue_stuck() -> int:
    """Au démarrage : une correction interrompue (application fermée pendant
    l'appel) repasse en file, et toute correction en attente repart."""
    pending = store.requeue_stuck_writings()
    for writing_id in pending:
        schedule_correction(writing_id)
    if pending:
        logger.info("%d correction(s) d'expression écrite relancée(s)", len(pending))
    return len(pending)
