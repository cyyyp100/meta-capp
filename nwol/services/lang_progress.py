# services/lang_progress.py — Difficulté, progression et acquis (plan § 9).
#
# ENTIÈREMENT déterministe : aucun appel LLM (principe 6 du plan — les signaux
# décident, Clikoda ne fait que formuler). Quatre responsabilités :
#
#   1. l'échelle de difficulté (P1-P2) : un cran -> des paramètres concrets
#      (répliques, mots par réplique, mots nouveaux, traduction, formes de texte),
#      interpolés entre les paliers d'ancrage de config/settings.py ;
#   2. la décision du prochain épisode (P3-P6) : normal ou respiration, cran ±1,
#      point du programme, forme du texte, mots à recycler ;
#   3. le programme et le niveau (P7-P9) : le niveau CECR est la position dans le
#      programme, historisée à chaque changement ;
#   4. les acquis (P10-P13) : lexique, signes d'écriture, flashcards.
#
# Le cran de difficulté et la position dans le programme sont couplés : le cran
# réel ne s'écarte jamais de plus de LANG_LADDER_BAND crans de celui qu'impose le
# point courant — un texte de niveau A1 ne porte pas un point de niveau B1.
from __future__ import annotations

import logging
import random
from datetime import datetime

from config.settings import (
    LANG_ACQUIRED_MIN_EPISODES,
    LANG_ACQUIRED_RECOGNITIONS,
    LANG_CARDS_PER_EPISODE,
    LANG_CEFR_ORDER,
    LANG_CEFR_TIER_INDEX,
    LANG_DIFFICULTY_LADDER,
    LANG_DUE_CARDS_CAP,
    LANG_EASY_STREAK_TO_STEP_UP,
    LANG_FORMAT_AVOID_LAST,
    LANG_GAMES_SUCCESS_EASY,
    LANG_GAMES_SUCCESS_HARD,
    LANG_KNOWN_WORDS_PROMPT_TOKENS,
    LANG_LADDER_BAND,
    LANG_LADDER_MAX_STEP_PER_EPISODE,
    LANG_LADDER_STEPS_PER_TIER,
    LANG_MAX_CONSECUTIVE_RESPIRATION,
    LANG_NEW_WORDS_CHECK_MAX_START_ORDER,
    LANG_NEW_WORDS_CHECK_MAX_TIER,
    LANG_NEW_WORDS_CHECK_MIN_LEXICON,
    LANG_RECYCLE_WORDS,
    LANG_RECYCLE_WORDS_RESPIRATION,
    LANG_RESPIRATION_NEW_WORDS_FACTOR,
    LANG_REVEAL_MIN_TOKENS,
    LANG_REVEAL_RATE_HIGH,
    LANG_REVEAL_RATE_LOW,
    LANG_SCRIPT_ACQUIRED_MIN_EPISODES,
    LANG_SCRIPT_ACQUIRED_RECOGNITIONS,
    LANG_SCRIPT_FAMILY,
    LANG_SECOND_WAVE_WEIGHT,
    LANG_TEXT_FORMATS,
    LANG_TRANSLATED_SHARE_EASY,
    LANG_TRANSLATED_SHARE_HARD,
)
from db import get_connection
from db import lang_episode_db as store
from services.lang_latin import de_article_pron

logger = logging.getLogger("services.lang_progress")

SECOND_WAVE_SCORES = {"su": 1.0, "a_peu_pres": 0.5, "pas_su": 0.0}
# Passes de lecture SANS traduction affichée d'office : un mot lu sans être
# touché y est une reconnaissance (C6), sauf dans une réplique dont l'apprenant
# a demandé la traduction (lang_line_reveals). L'ancien passage 1 montrait la
# traduction, il ne compte pas ; `p2` reste pour les séances d'avant la lecture unique.
RECOGNITION_PASSES = ("lecture", "p2", "relecture", "rappel", "jalon", "recap")
# LA lecture de l'épisode du jour : l'étape « lecture », ou le passage 2 des
# séances d'avant (données anciennes comprises).
FIRST_READING_PASSES = ("lecture", "p2")


def family(language: str) -> str:
    return LANG_SCRIPT_FAMILY.get(language, "latin")


# ── 1. Échelle de difficulté (P1-P2) ──────────────────────────────────────────

def ladder_max_step(language: str) -> int:
    return (len(LANG_DIFFICULTY_LADDER[family(language)]) - 1) * LANG_LADDER_STEPS_PER_TIER


def _lerp_range(low, high, t: float):
    """Interpolation d'une borne (min, max). `None` = libre : on garde la borne
    du palier inférieur tant qu'on n'a pas atteint le palier « libre »."""
    if low is None:
        return None
    if high is None:
        return tuple(low)
    return (round(low[0] + (high[0] - low[0]) * t), round(low[1] + (high[1] - low[1]) * t))


def text_formats(language: str, tier_index: int) -> tuple[str, ...]:
    table = LANG_TEXT_FORMATS.get(language) or LANG_TEXT_FORMATS["_default"]
    return table[max(0, min(tier_index, len(table) - 1))]


def ladder_params(language: str, step: int) -> dict:
    """Paramètres concrets d'un cran de l'échelle (P1)."""
    anchors = LANG_DIFFICULTY_LADDER[family(language)]
    step = max(0, min(int(step), ladder_max_step(language)))
    tier = min(step // LANG_LADDER_STEPS_PER_TIER, len(anchors) - 1)
    frac = (step - tier * LANG_LADDER_STEPS_PER_TIER) / LANG_LADDER_STEPS_PER_TIER
    low = anchors[tier]
    high = anchors[min(tier + 1, len(anchors) - 1)]
    return {
        "step": step,
        "tier_index": tier,
        "tier": low["tier"],
        "lines": _lerp_range(low["lines"], high["lines"], frac),
        "words_per_line": _lerp_range(low["words_per_line"], high["words_per_line"], frac),
        "new_words": _lerp_range(low["new_words"], high["new_words"], frac),
        "translation": low["translation"],
        "formats": list(text_formats(language, tier)),
    }


def new_words_cap(params: dict, kind: str | None) -> int:
    """Mots nouveaux (caractères en mandarin) permis par un épisode : la borne
    haute du cran, réduite pour une respiration. Le prompt l'annonce et le
    validateur la contrôle — un seul calcul pour les deux."""
    cap = int(params["new_words"][1])
    if kind == "respiration":
        cap = max(1, round(cap * LANG_RESPIRATION_NEW_WORDS_FACTOR))
    return cap


def prompt_constraints(language: str, params: dict, kind: str, explain_lang: str = "fr") -> str:
    """P2 : les paramètres du cran traduits en consignes pour le prompt du texte,
    dans la langue du prompt (langue d'explication du profil)."""
    hanzi = family(language) == "hanzi"
    new_max = new_words_cap(params, kind)
    wpl = params.get("words_per_line")
    lo, hi = params["lines"]
    if explain_lang == "en":
        unit = "characters" if hanzi else "words"
        parts = [f"between {lo} and {hi} lines",
                 f"{wpl[0]} to {wpl[1]} {unit} per line" if wpl else "free line length, natural sentences"]
        if kind == "respiration":
            parts.append(f"BREATHER episode: same point as the previous episode, at most {new_max} new {unit}, "
                         "and as many already-seen words as possible")
        else:
            parts.append(f"at most {new_max} new {unit} for the learner; the rest must be very common")
        return "; ".join(parts) + "."
    unit = "caractères" if hanzi else "mots"
    parts = [f"entre {lo} et {hi} répliques"]
    parts.append(
        f"de {wpl[0]} à {wpl[1]} {unit} par réplique" if wpl else "longueur des répliques libre, phrases naturelles"
    )
    if kind == "respiration":
        parts.append(
            f"épisode de RESPIRATION : même point que l'épisode précédent, au plus {new_max} {unit} nouveaux, "
            "et le plus possible de mots déjà vus"
        )
    else:
        parts.append(f"au plus {new_max} {unit} nouveaux pour l'apprenant ; le reste doit être très courant")
    return " ; ".join(parts) + "."


# ── 2. Programme et niveau (P7-P9) ────────────────────────────────────────────

_PROGRAM_CACHE: dict[tuple[str, str], list[dict]] = {}


def program(language: str) -> list[dict]:
    """Programme d'une langue, gardé en mémoire tant que sa version en base
    (empreinte du fichier, D23) ne change pas : une décision le relit souvent."""
    version = store.reference_version("lang_program_points", "language", language) or ""
    key = (language, version)
    cached = _PROGRAM_CACHE.get(key)
    if cached is None:
        cached = store.get_program(language)
        if version:
            _PROGRAM_CACHE.clear() if len(_PROGRAM_CACHE) > 16 else None
            _PROGRAM_CACHE[key] = cached
    return cached


def program_position(language: str, order: int) -> tuple[str, float]:
    """(niveau CECR du point `order`, part du niveau déjà parcourue 0-1)."""
    points = program(language)
    if not points:
        return "A1", 0.0
    order = max(1, min(int(order or 1), len(points)))
    cefr = points[order - 1]["cefr"]
    same = [p for p in points if p["cefr"] == cefr]
    idx = next((i for i, p in enumerate(same) if p["order"] == order), 0)
    return cefr, idx / max(1, len(same))


def current_cefr(language: str, program_order: int) -> str:
    """Niveau CECR = palier du point courant (P8) ; A1 avant le premier point."""
    if not program_order:
        return "A1"
    return program_position(language, program_order)[0]


def target_step(language: str, order: int) -> int:
    cefr, frac = program_position(language, order)
    step = LANG_CEFR_TIER_INDEX.get(cefr, 0) * LANG_LADDER_STEPS_PER_TIER + round(frac * LANG_LADDER_STEPS_PER_TIER)
    return max(0, min(step, ladder_max_step(language)))


def clamp_step(language: str, step: int, order: int) -> int:
    target = target_step(language, order)
    low = max(0, target - LANG_LADDER_BAND)
    high = min(ladder_max_step(language), target + LANG_LADDER_BAND)
    return max(low, min(high, int(step)))


def record_level(profile: dict, language: str, program_order: int, source: str) -> str:
    """Écrit une ligne d'historique si le niveau change (P8) ; renvoie le niveau."""
    from db.lang_db import update_lang_profile

    cefr = current_cefr(language, program_order)
    history = store.get_level_history(profile["id"])
    if not history or history[-1]["cefr"] != cefr or source == "placement":
        store.add_level_history(profile["id"], cefr, program_order, source)
    if profile.get("level") != cefr:
        update_lang_profile(profile["id"], level=cefr, touch_last_session=False)
    return cefr


def placement_start_order(language: str, passed_points: list[str]) -> int:
    """P9 / R25 : point de départ = dernier point réussi de façon consécutive
    (items dans l'ordre du test), moins une marge de sécurité ; 1 au minimum."""
    from config.settings import LANG_PLACEMENT_SAFETY_MARGIN

    orders = {p["id"]: p["order"] for p in program(language)}
    last = 0
    for pid in passed_points:
        if pid not in orders:
            break
        last = max(last, orders[pid])
    return max(1, last - LANG_PLACEMENT_SAFETY_MARGIN + 1) if last else 1


def start_order_of(profile_id: int) -> int:
    """Point de départ du parcours : la dernière ligne `placement` de
    l'historique de niveau (test de niveau, ou 1 pour un débutant). Sans elle,
    le parcours est parti du début."""
    placements = [h for h in store.get_level_history(profile_id) if h["source"] == "placement"]
    return int(placements[-1]["program_order"] or 1) if placements else 1


def program_ended(language: str, order: int) -> bool:
    """Tout le programme est introduit : il n'y a plus de point après `order`."""
    points = program(language)
    return bool(points) and int(order or 0) >= points[-1]["order"]


def new_words_check_applies(params: dict, lexicon_size: int, start_order: int) -> bool:
    """Le contrôle des mots nouveaux n'a de sens que là où le lexique dit ce que
    l'apprenant sait : paliers A1 et A1-A2, lexique amorcé, parcours commencé au
    début du programme. Un apprenant placé (A1 au point 23, C1 au point 262)
    sait bien plus que les quelques dizaines de mots de son lexique."""
    return (int(params.get("tier_index") or 0) <= LANG_NEW_WORDS_CHECK_MAX_TIER
            and int(lexicon_size) >= LANG_NEW_WORDS_CHECK_MIN_LEXICON
            and int(start_order) <= LANG_NEW_WORDS_CHECK_MAX_START_ORDER)


def mark_point_introduced(profile: dict, language: str, point_id: str | None, episode_n: int) -> int:
    """P7 : un épisode normal joué introduit son point ; la position courante
    avance (jamais de recul). Renvoie la nouvelle position."""
    order = int(profile.get("program_order") or 0)
    if point_id:
        point = store.get_point(language, point_id)
        store.set_point_status(profile["id"], point_id, "introduit", introduced_episode_n=episode_n)
        if point and point["order"] > order:
            order = point["order"]
            store.update_profile_fields(profile["id"], program_order=order)
            record_level({**profile, "program_order": order}, language, order, "progression")
    return order


def consolidate_points(profile: dict, point_ids: list[str]) -> None:
    """P7 : la séance bilan consolide les points de son groupe."""
    for pid in point_ids:
        store.set_point_status(profile["id"], pid, "consolide")


# ── 3. Signaux et décision (P3-P6) ────────────────────────────────────────────

def word_token_count(lines: list[dict]) -> int:
    return sum(1 for line in lines or [] for tok in line.get("tokens") or [] if tok.get("w"))


def episode_signals(run_id: int) -> dict:
    """P3 : signaux d'une séance. `None` quand rien n'a été mesuré — un signal
    absent n'est jamais un succès (principe 5).

    La lecture du jour est l'étape « lecture » (le passage 2 d'une séance
    d'avant). Une réplique dont l'apprenant a demandé la traduction ne dit rien
    de ce qu'il lit seul : le taux de taps se calcule sur les AUTRES, et vaut
    None sous LANG_REVEAL_MIN_TOKENS mots ; la part de répliques traduites
    (`translated_share`) est un signal à part, jugé selon le palier."""
    run = store.get_run(run_id) or {}
    episode = store.get_episode(run["episode_id"]) if run.get("episode_id") else None
    steps = {s["step"]: s for s in store.get_steps(run_id)}
    key, pass_ = ("episode_p2", "p2") if "episode_p2" in steps and "lecture" not in steps else ("lecture", "lecture")
    reading = steps.get(key)
    done = bool(reading and not reading["skipped"])
    lines = (episode or {}).get("lines") or []
    tokens = word_token_count(lines)
    translated = {r["line_idx"] for r in store.get_line_reveals(run_id)
                  if episode and r["episode_id"] == episode["id"] and r["pass"] == pass_}
    open_tokens = word_token_count([ln for li, ln in enumerate(lines) if li not in translated])
    reveals = [r for r in store.get_reveals(run_id) if r["pass"] == pass_ and episode
               and r["episode_id"] == episode["id"] and r["line_idx"] not in translated]
    reveal_rate = (len(reveals) * 100.0 / open_tokens) if done and open_tokens >= LANG_REVEAL_MIN_TOKENS else None
    translated_share = (len(translated) / len(lines)) if done and lines else None
    understood = None
    for step_key in ("lecture", "episode_p2", "episode_p1"):
        if steps.get(step_key) and steps[step_key].get("signal"):
            understood = steps[step_key]["signal"]
            break
    answered = [a for a in store.get_attempts(run_id) if a["correct"] is not None]
    games_rate = (sum(a["correct"] for a in answered) / len(answered)) if answered else None
    ratings = [SECOND_WAVE_SCORES[r["rating"]] for r in store.get_second_wave_ratings(run_id)
               if r["rating"] in SECOND_WAVE_SCORES]
    sw_rate = (sum(ratings) / len(ratings)) if ratings else None
    tier = ((episode or {}).get("params") or {}).get("tier_index")
    return {
        "reveal_rate": round(reveal_rate, 2) if reveal_rate is not None else None,
        "reveals": len(reveals),
        "tokens": tokens,
        "read_tokens": open_tokens,
        "translated_lines": len(translated),
        "translated_share": round(translated_share, 3) if translated_share is not None else None,
        "tier_index": int(tier) if tier is not None else None,
        "understood": understood,
        "games_rate": round(games_rate, 3) if games_rate is not None else None,
        "answered": len(answered),
        "second_wave_rate": round(sw_rate, 3) if sw_rate is not None else None,
        "reading_done": done,
    }


def success_rate(signals: dict) -> float | None:
    """Réussite du jour : jeux (items répondus) et auto-évaluation de 2e vague,
    celle-ci pondérée par LANG_SECOND_WAVE_WEIGHT."""
    games, sw = signals.get("games_rate"), signals.get("second_wave_rate")
    if games is None and sw is None:
        return None
    if sw is None:
        return games
    if games is None:
        return sw
    return games * (1 - LANG_SECOND_WAVE_WEIGHT) + sw * LANG_SECOND_WAVE_WEIGHT


def _share_thresholds(signals: dict) -> tuple[float | None, float | None]:
    """(seuil « dur », seuil « facile ») de la part traduite, pour le palier du
    texte lu ; (None, None) sans part mesurée — d'anciens signaux se classent
    comme avant."""
    share, tier = signals.get("translated_share"), signals.get("tier_index")
    if share is None or tier is None:
        return None, None
    i = max(0, min(int(tier), len(LANG_TRANSLATED_SHARE_HARD) - 1))
    return LANG_TRANSLATED_SHARE_HARD[i], LANG_TRANSLATED_SHARE_EASY[min(i, len(LANG_TRANSLATED_SHARE_EASY) - 1)]


def classify(signals: dict) -> str:
    """hard | easy | ok. Il faut un signal POSITIF pour dire « facile ».

    La part de répliques traduites compte selon le palier : en A1, « Tout
    traduire » est une aide prévue et ne rend jamais « dur » ; en B1, traduire
    presque tout l'est. « Facile » demande d'être resté sous le seuil du palier."""
    rate = signals.get("reveal_rate")
    understood = signals.get("understood")
    success = success_rate(signals)
    share = signals.get("translated_share")
    hard_share, easy_share = _share_thresholds(signals)
    if (rate is not None and rate > LANG_REVEAL_RATE_HIGH) or understood == "pas_compris" or (
        success is not None and success < LANG_GAMES_SUCCESS_HARD
    ) or (hard_share is not None and share >= hard_share):
        return "hard"
    if rate is not None and rate < LANG_REVEAL_RATE_LOW and understood in (None, "compris") and (
        success is None or success >= LANG_GAMES_SUCCESS_EASY
    ) and (easy_share is None or share <= easy_share):
        return "easy"
    return "ok"


def choose_format(language: str, params: dict, point: dict | None, recent_formats: list[str], seed: int) -> str:
    """P5 : rotation dans les formes autorisées par le palier ET par le point,
    en évitant celles des derniers épisodes."""
    tier_formats = params.get("formats") or ["dialogue"]
    point_formats = list((point or {}).get("formats_allowed") or [])
    if point_formats and point_formats[0] != "dialogue":
        # Un point qui porte sur une forme écrite (« écrire à un ami », « une
        # recette ») la reçoit, même si le palier n'autorise encore que le dialogue.
        return point_formats[0]
    allowed = [f for f in tier_formats if not point or f in (point_formats or tier_formats)]
    if not allowed:
        allowed = list((point or {}).get("formats_allowed") or tier_formats)[:1] or ["dialogue"]
    avoid = set(recent_formats[:LANG_FORMAT_AVOID_LAST])
    fresh = [f for f in allowed if f not in avoid]
    pool = fresh or allowed
    return pool[seed % len(pool)]


def lemma_polluted(language: str, form: str | None, lemma: str | None, translation: str | None) -> bool:
    """Lemme « pollué » : Clikoda y a mis la traduction (« demographic » →
    lemme « démographie »). Il est égal à sa traduction, différent de sa forme,
    et la forme ne commence pas par lui (« restaurants » → « restaurant » est un
    vrai lemme). En mandarin et en arabe, un lemme hors de l'écriture cible."""
    from services.lang_text import fold

    lemma = (lemma or "").strip()
    if not lemma:
        return False
    fam = family(language)
    if fam == "hanzi":
        from services.lang_mandarin import is_han

        return not any(is_han(c) for c in lemma)
    if fam == "arabe":
        from services.lang_arabic import is_arabic_letter

        return not any(is_arabic_letter(c) for c in lemma)
    f_form, f_lemma = fold(form or ""), fold(lemma)
    return f_lemma == fold(translation or "") and f_lemma != f_form and not f_form.startswith(f_lemma)


def lexeme_polluted(language: str, row: dict) -> bool:
    """Une ligne du lexique inscrite avec un lemme pollué (avant la réparation) :
    elle n'est plus proposée au réemploi, ni comme mot connu."""
    return lemma_polluted(language, row.get("form"), row.get("lemma"), row.get("translation"))


def recycle_words(profile_id: int, language: str, count: int) -> list[str]:
    """P6 : mots vus mais non acquis ; ceux dont la carte est due d'abord, puis
    ceux qui ont suscité le plus de taps. Un lemme pollué (une traduction prise
    pour un lemme) n'est pas un mot à réemployer."""
    rows = get_connection().execute(
        """SELECT l.form, l.lemma, l.translation, l.reveals,
                  CASE WHEN f.due_at IS NOT NULL AND f.due_at <= datetime('now', 'localtime') THEN 1 ELSE 0 END AS due
           FROM lang_lexicon l LEFT JOIN flashcards f ON f.id = l.card_id
           WHERE l.profile_id=? AND l.acquired_at IS NULL
           ORDER BY due DESC, l.reveals DESC, l.last_episode_n DESC, l.id DESC""",
        (profile_id,),
    ).fetchall()
    kept = [r["lemma"] or r["form"] for r in rows if not lexeme_polluted(language, dict(r))]
    return kept[: max(0, int(count))]


def known_words_for_prompt(profile_id: int, language: str, *, read_chars=(), exclude=()) -> list[str]:
    """Ce que l'apprenant connaît déjà, pour le prompt du texte : ses lemmes,
    acquis d'abord puis les plus reconnus ; en mandarin, ses caractères (acquis,
    vus, puis lus dans un épisode joué). Bornés à LANG_KNOWN_WORDS_PROMPT_TOKENS."""
    from llm.prompts import fit_word_list

    skip = set(exclude)
    if family(language) == "hanzi":
        from services.lang_scripts import HANZI_SCRIPT

        rows = store.get_script_progress(profile_id, HANZI_SCRIPT)
        ranked = sorted(rows.items(), key=lambda kv: (kv[1].get("acquired_at") is None,
                                                      -int(kv[1].get("recognitions_ok") or 0)))
        chars = list(dict.fromkeys([unit for unit, _row in ranked] + list(read_chars)))
        return fit_word_list([c for c in chars if c not in skip], LANG_KNOWN_WORDS_PROMPT_TOKENS)
    rows = get_connection().execute(
        """SELECT form, lemma, translation, pos FROM lang_lexicon WHERE profile_id=?
           ORDER BY (acquired_at IS NULL), recognitions_ok DESC, exposures DESC, id""",
        (profile_id,),
    ).fetchall()
    lemmas = [r["lemma"] for r in rows if r["lemma"] and r["lemma"] not in skip
              and (r["pos"] or "") != "nom propre" and not lexeme_polluted(language, dict(r))]
    return fit_word_list(list(dict.fromkeys(lemmas)), LANG_KNOWN_WORDS_PROMPT_TOKENS)


def next_episode_decision(profile: dict, language: str, *, current: dict | None, signals: dict | None,
                          episode_n: int) -> dict:
    """P4 : type, cran, point et forme de l'épisode `episode_n`.

    - trop de taps, « pas compris » ou jeux ratés -> respiration (même point,
      moins de mots nouveaux, plus de recyclage), au plus
      LANG_MAX_CONSECUTIVE_RESPIRATION d'affilée ;
    - « facile » LANG_EASY_STREAK_TO_STEP_UP fois de suite -> un cran de plus ;
    - une reprise après absence impose une respiration (force_respiration) ;
    - jamais de recul dans le programme ; le cran bouge d'au plus un cran, à
      partir de celui de l'épisode joué (`current`) quand il est connu : le cran
      du profil a pu avancer déjà, avec un épisode décidé d'avance que l'on
      redécide (une respiration imposée par une reprise montait d'un cran)."""
    signals = signals or {}
    verdict = classify(signals) if signals else "ok"
    step = int(profile.get("ladder_step") or 0)
    if current is not None and current.get("ladder_step") is not None:
        step = int(current["ladder_step"])
    order = int(profile.get("program_order") or 0)
    points = program(language)
    recent = store.list_episodes(profile["id"], limit=LANG_MAX_CONSECUTIVE_RESPIRATION + 3)
    recent = [e for e in recent if e["episode_n"] < episode_n]
    consecutive_resp = 0
    for e in recent:
        if e["kind"] != "respiration":
            break
        consecutive_resp += 1
    forced = bool(profile.get("force_respiration"))
    can_breathe = current is not None and current.get("program_point_id") and consecutive_resp < LANG_MAX_CONSECUTIVE_RESPIRATION
    kind = "respiration" if can_breathe and (forced or verdict == "hard") else "normal"
    previous_streak = int(((current or {}).get("params") or {}).get("easy_streak", 0))
    streak = 0
    if kind == "respiration":
        point_id = current["program_point_id"]
        delta = -1 if verdict == "hard" else 0
    else:
        nxt = next((p for p in points if p["order"] > order), None)
        if nxt is None and points:
            nxt = points[-1]  # fin du programme : on reste sur le dernier point
        point_id = nxt["id"] if nxt else None
        streak = previous_streak + 1 if verdict == "easy" else 0
        delta = 1 if streak >= LANG_EASY_STREAK_TO_STEP_UP else 0
        if delta:
            streak = 0  # la série repart de zéro au cran suivant
    point = store.get_point(language, point_id) if point_id else None
    point_order = point["order"] if point else max(order, 1)
    delta = max(-LANG_LADDER_MAX_STEP_PER_EPISODE, min(LANG_LADDER_MAX_STEP_PER_EPISODE, delta))
    new_step = clamp_step(language, step + delta, point_order)
    # La bande peut imposer plus d'un cran quand le programme a sauté (test de
    # niveau) : on n'y va qu'un cran à la fois.
    new_step = max(step - LANG_LADDER_MAX_STEP_PER_EPISODE, min(step + LANG_LADDER_MAX_STEP_PER_EPISODE, new_step)) \
        if recent else new_step
    params = ladder_params(language, new_step)
    fmt = choose_format(language, params, point, [e["format"] for e in recent], seed=episode_n)
    recycle_range = LANG_RECYCLE_WORDS_RESPIRATION if kind == "respiration" else LANG_RECYCLE_WORDS
    rng = random.Random(profile["id"] * 1000 + episode_n)
    recycle = recycle_words(profile["id"], language, rng.randint(*recycle_range))
    return {
        "kind": kind,
        "program_point_id": point_id,
        "ladder_step": new_step,
        "format": fmt,
        "params": {**params, "recycle": recycle, "verdict": verdict, "signals": signals,
                   "easy_streak": streak, "forced": forced and kind == "respiration",
                   "program_end": program_ended(language, order)},
    }


# ── 4. Acquis (P10-P13) ───────────────────────────────────────────────────────

def _is_acquired(row: dict, recognitions: int, min_episodes: int) -> bool:
    return (
        int(row.get("recognitions_ok") or 0) >= recognitions
        and int(row.get("episodes_seen") or 0) >= min_episodes
        and int(row.get("recognitions_ok") or 0) > int(row.get("recognitions_ko") or 0)
    )


def ensure_lexemes(profile_id: int, episode: dict) -> dict[int, int]:
    """Inscrit au lexique les mots du glossaire d'un épisode ; renvoie
    {index glossaire: id lexique}."""
    ids: dict[int, int] = {}
    for gi, entry in enumerate(episode.get("glossary") or []):
        if (entry.get("pos") or "") == "nom propre":
            continue
        ids[gi] = store.insert_lexeme(profile_id, {
            "form": entry.get("form"), "lemma": entry.get("lemma") or entry.get("form"),
            "translation": entry.get("translation"), "pos": entry.get("pos"), "gender": entry.get("gender"),
            "pron": entry.get("pron"), "vocalized": entry.get("vocalized"),
            "transparent": entry.get("transparent"),
        }, episode.get("episode_n"))
    return ids


def apply_run_acquisition(run_id: int) -> dict:
    """P10-P11 : met à jour lexique et signes après une séance.

    Pour chaque épisode lu SANS traduction pendant la séance (lecture,
    relecture, rappel, jalon ; passage 2 des séances d'avant) : un mot touché
    compte un tap et un échec, un mot lu sans être touché une reconnaissance —
    sauf dans une réplique dont la traduction a été montrée, qui ne donne
    qu'une exposition. Les réponses aux jeux qui portent un mot (`lexeme`) ou un
    signe (`unit`) comptent aussi. Chaque épisode ne compte qu'une fois par séance."""
    from services.lang_scripts import script_units_of_token

    run = store.get_run(run_id) or {}
    plan = run.get("plan") or {}
    profile_id = run["profile_id"]
    language = plan.get("language")
    reveals = store.get_reveals(run_id)
    tapped: dict[tuple[int, str], set[tuple[int, int]]] = {}
    for r in reveals:
        tapped.setdefault((int(r["episode_id"] or 0), r["pass"]), set()).add((r["line_idx"], r["token_idx"]))
    translated: dict[tuple[int, str], set[int]] = {}
    for r in store.get_line_reveals(run_id):
        translated.setdefault((int(r["episode_id"]), r["pass"]), set()).add(int(r["line_idx"]))
    steps = {s["step"]: s for s in store.get_steps(run_id)}
    stats = {"lexemes": 0, "acquired": 0, "units": 0}
    seen_units: set[tuple[str, str]] = set()
    for reading in plan.get("readings") or []:
        step = steps.get(reading["step"])
        if not step or step["skipped"]:
            continue
        episode = store.get_episode(reading["episode_id"])
        if not episode:
            continue
        lex_ids = ensure_lexemes(profile_id, episode)
        taps = tapped.get((episode["id"], reading["pass"]), set())
        shown = translated.get((episode["id"], reading["pass"]), set())
        counted_ok: dict[int, int] = {}
        counted_ko: dict[int, int] = {}
        for li, line in enumerate(episode["lines"]):
            exposure_only = li in shown  # traduction montrée : ni reconnaissance ni échec
            for ti, tok in enumerate(line.get("tokens") or []):
                if not tok.get("w"):
                    continue
                touched = (li, ti) in taps
                gi = tok.get("g")
                if gi is not None and gi in lex_ids and reading["pass"] in RECOGNITION_PASSES and not exposure_only:
                    target = counted_ko if touched else counted_ok
                    target[lex_ids[gi]] = 1
                for script, unit in script_units_of_token(language, tok.get("text", "")):
                    key = (script, unit)
                    store.bump_script_unit(
                        profile_id, script, unit, episode_n=episode["episode_n"], exposures=1,
                        ok=0 if touched or exposure_only else int(key not in seen_units),
                        ko=1 if touched and not exposure_only else 0,
                    )
                    seen_units.add(key)
        reveals_per_lexeme: dict[int, int] = {}
        for li, ti in taps:
            try:
                gi = episode["lines"][li]["tokens"][ti].get("g")
            except (IndexError, KeyError, TypeError):
                continue
            if gi in lex_ids:
                reveals_per_lexeme[lex_ids[gi]] = reveals_per_lexeme.get(lex_ids[gi], 0) + 1
        for lex_id in set(lex_ids.values()):
            ko = counted_ko.get(lex_id, 0)
            ok = 0 if ko else counted_ok.get(lex_id, 0)
            store.bump_lexeme(
                lex_id, episode_n=episode["episode_n"], exposures=1,
                reveals=reveals_per_lexeme.get(lex_id, 0), ok=ok, ko=ko,
            )
            stats["lexemes"] += 1
    for attempt in store.get_attempts(run_id):
        if attempt["correct"] is None:
            continue
        expected = attempt.get("expected") or {}
        ok = int(bool(attempt["correct"]))
        for lemma in expected.get("lexemes") or []:
            row = store.get_lexeme(profile_id, lemma)
            if row:
                store.bump_lexeme(row["id"], ok=ok, ko=1 - ok)
        for script, unit in expected.get("units") or []:
            store.bump_script_unit(profile_id, script, unit, ok=ok, ko=1 - ok)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for row in store.get_lexicon(profile_id).values():
        if row["acquired_at"] is None and _is_acquired(row, LANG_ACQUIRED_RECOGNITIONS, LANG_ACQUIRED_MIN_EPISODES):
            store.update_lexeme(row["id"], acquired_at=now)
            stats["acquired"] += 1
    for script, _unit in seen_units | {tuple(u) for a in store.get_attempts(run_id)
                                       for u in ((a.get("expected") or {}).get("units") or [])}:
        for unit_key, row in store.get_script_progress(profile_id, script).items():
            if row["acquired_at"] is None and _is_acquired(
                row, LANG_SCRIPT_ACQUIRED_RECOGNITIONS, LANG_SCRIPT_ACQUIRED_MIN_EPISODES
            ):
                store.set_script_unit_acquired(profile_id, script, unit_key)
                stats["units"] += 1
    return stats


def _card_pronunciation(entry: dict) -> str | None:
    """Prononciation du RECTO d'une carte du feuilleton : celle du lemme, précédée
    de celle de l'article quand le recto l'écrit (allemand)."""
    pron = (entry.get("pron") or "").strip()
    if not pron:
        return None
    article = de_article_pron(entry.get("article"))
    return f"{article} {pron}" if article else pron


def create_episode_flashcards(profile: dict, language: str, episode: dict, tapped_lemmas: set[str]) -> int:
    """P12 : cartes du feuilleton — recto en langue cible, verso traduction,
    prononciation du recto, dédoublonnées par lemme. Les mots touchés au passage 2
    d'abord, puis les mots nouveaux non transparents.

    Pas de carte de langue sans prononciation : calculée (pinyin, translittération
    arabe) ou écrite par Clikoda (langues latines). Un mot qui n'en a pas laisse
    sa place au suivant ; il aura sa carte quand un épisode la lui donnera."""
    from services.flashcards import create_flashcard

    user_id = int(profile.get("user_id") or 1)
    lexicon = store.get_lexicon(profile["id"])
    candidates: list[dict] = []
    for entry in episode.get("glossary") or []:
        lemma = entry.get("lemma") or entry.get("form")
        row = lexicon.get(lemma)
        if not row or row.get("card_id") or (entry.get("pos") or "") == "nom propre":
            continue
        if not _card_pronunciation(entry):
            continue
        priority = 0 if lemma in tapped_lemmas else (1 if entry.get("new") and not entry.get("transparent") else 9)
        if priority < 9:
            candidates.append({**entry, "_priority": priority, "_lexeme_id": row["id"]})
    candidates.sort(key=lambda e: e["_priority"])
    created = 0
    for entry in candidates[:LANG_CARDS_PER_EPISODE]:
        lemma = entry.get("lemma") or entry["form"]
        front = entry.get("vocalized") or lemma
        if entry.get("article"):
            front = f"{entry['article']} {front}"
        try:
            card_id = create_flashcard(
                user_id, front=front, back=entry["translation"], tags=[language],
                source="lang_feuilleton", language=language,
                origin=("lang_lemma", f"{language}\x1f{lemma}"),
                pronunciation=_card_pronunciation(entry),
            )
        except Exception:  # une carte ratée ne casse pas la clôture
            logger.warning("Carte du feuilleton non créée (%s)", lemma, exc_info=True)
            continue
        store.update_lexeme(entry["_lexeme_id"], card_id=card_id)
        created += 1
    return created


def due_cards(profile: dict, language: str, cap: int = LANG_DUE_CARDS_CAP) -> list[dict]:
    """P13 : cartes dues de la langue, les plus anciennes d'abord, plafonnées ;
    le reste attend naturellement les séances suivantes."""
    rows = get_connection().execute(
        """SELECT id, front, back, pronunciation, source, due_at FROM flashcards
           WHERE language=? AND user_id=? AND due_at IS NOT NULL
             AND due_at <= datetime('now', 'localtime')
           ORDER BY due_at ASC, id ASC LIMIT ?""",
        (language, int(profile.get("user_id") or 1), int(cap)),
    ).fetchall()
    return [dict(r) for r in rows]


def cefr_rank(cefr: str) -> int:
    return LANG_CEFR_ORDER.index(cefr) if cefr in LANG_CEFR_ORDER else 0
