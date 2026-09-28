# services/lang_runs.py — Assembleur de séance, méthode « feuilleton » (plan § 10).
#
# Décide du mode d'une séance, assemble le contenu de chaque étape depuis la
# base et ne fait AUCUN appel LLM (principe 1) : tout ce qu'une séance montre
# existe déjà. Si l'épisode du jour n'est pas prêt, la séance bascule sur un
# mode qui n'en a pas besoin (relecture) et la génération part aussitôt.
#
# Une séance (`lang_runs`) porte son plan complet : les étapes, les épisodes à
# afficher (aides déjà décidées selon l'acquis de l'apprenant), les items des
# jeux avec leurs clés. Le front reçoit ce plan, renvoie des lots d'événements
# à chaque changement d'étape, et c'est ici que les réponses sont recorrigées
# (R23), que la pré-génération de l'épisode suivant part (G16) et que le
# plafond de durée est appliqué (R24).
from __future__ import annotations

import logging
import random
from datetime import datetime

from config.settings import (
    LANG_BILAN_EVERY,
    LANG_DE_GENDER_COLORS,
    LANG_ESSENTIAL_STEPS,
    LANG_IDLE_CUTOFF_S,
    LANG_MILESTONES_EPISODE_1,
    LANG_PILOT_LANGUAGES,
    LANG_PREGEN_TRIGGER_STEP,
    LANG_RECAP_LONG_EPISODES,
    LANG_RELECTURE_EPISODES,
    LANG_REPRISE_CONTROLE_EPISODES,
    LANG_REPRISE_CONTROLE_OK,
    LANG_REWIND_EPISODES,
    LANG_RUN_MAX_S,
    LANG_RUN_SHORT_TARGET_S,
    LANG_RUN_TARGET_S,
    LANG_SCRIPT_FAMILY,
    LANG_SECOND_WAVE_LINES,
    LANG_SECOND_WAVE_OFFSET,
    LANG_SECOND_WAVE_START,
    LANG_STEP_BUDGET_S,
    LANG_TRANSPARENT_FLAG_UNTIL_EPISODE,
    LANG_ZH_TONE_COLORS,
)
from db import lang_episode_db as store
from db.lang_db import get_lang_profile_by_id, get_or_create_lang_profile, update_lang_profile
from db.user import DEFAULT_USER_ID
from i18n import t
from services import lang_activity as activity
from services import lang_episodes as episodes
from services import lang_games as games
from services import lang_progress as progress
from services.lang_scripts import (
    ARABIC_SCRIPT,
    COMPONENTS_SCRIPT,
    HANZI_SCRIPT,
    acquired_units,
    arabic_aid_level,
    arabic_word_display,
    seen_units,
)
from services.lang_static import explain_languages, localized
from services.lang_static import onboarding as onboarding_data
from services.lang_text import find_token_span, word_diff, words

logger = logging.getLogger("services.lang_runs")

FEELING_QUESTIONS = ("q1", "q2", "q3", "q4", "q5", "q6")
FEELING_OPTIONS = ("a", "b", "c")
EPISODE_MODES = ("episode", "court")
MODES = ("zero", "episode", "bilan", "reprise", "relecture", "court", "jalon")


class RunError(ValueError):
    """Requête impossible (séance inconnue, langue hors pilote…)."""


# ── Profil et cohabitation des flux (K8-K9) ───────────────────────────────────

def is_pilot(language: str) -> bool:
    return language in LANG_PILOT_LANGUAGES


def unavailable_reason(language: str) -> str | None:
    """Porte V17 : une langue du pilote qui ne peut pas s'ouvrir sur cette
    installation. Le mandarin sans pypinyin s'afficherait sans pinyin, sans
    prononciation sur les cartes et sans les jeux de lecture : il est refusé
    avec une raison que l'accueil affiche, plutôt qu'ouvert à moitié."""
    if _family(language) == "hanzi":
        from services.lang_mandarin import PINYIN_AVAILABLE

        if not PINYIN_AVAILABLE:
            return "pinyin"
    return None


def ensure_feuilleton(language: str, user_id: int = DEFAULT_USER_ID) -> dict:
    """Profil d'une langue du pilote, passé au flux feuilleton au premier accès.

    Un profil hérité (test de niveau passé, séances jouées) garde ses
    flashcards : elles sont importées dans le lexique (K9) et l'onboarding
    proposera le test de niveau statique."""
    if not is_pilot(language):
        raise RunError(f"langue hors pilote : {language}")
    reason = unavailable_reason(language)
    if reason:
        raise RunError(f"langue indisponible sur cette installation ({reason}) : {language}")
    profile = get_or_create_lang_profile(user_id, language)
    if profile.get("flow") != "feuilleton":
        _import_legacy_flashcards(profile, language)
        store.update_profile_fields(profile["id"], flow="feuilleton")
        profile = get_or_create_lang_profile(user_id, language)
    return {**store.decode_profile(profile), "user_id": user_id}


def _import_legacy_flashcards(profile: dict, language: str) -> int:
    """Cartes de vocabulaire du flux hérité -> lexique (recto « X en langue »,
    verso = mot cible). Les mots importés restent non acquis."""
    from db import get_connection

    rows = get_connection().execute(
        "SELECT id, front, back, pronunciation FROM flashcards WHERE language=? AND user_id=?",
        (language, profile["user_id"]),
    ).fetchall()
    suffix = f" en {language}"
    count = 0
    for r in rows:
        front, back = (r["front"] or "").strip(), (r["back"] or "").strip()
        if not back:
            continue
        translation = front[: -len(suffix)] if front.endswith(suffix) else front
        lex_id = store.insert_lexeme(profile["id"], {
            "form": back, "lemma": back, "translation": translation, "pron": r["pronunciation"],
        }, None)
        store.update_lexeme(lex_id, card_id=int(r["id"]))
        count += 1
    return count


def _profile(profile_id: int) -> dict:
    row = get_lang_profile_by_id(profile_id)
    if not row:
        raise RunError("profil introuvable")
    return {**store.decode_profile(row), "user_id": row.get("user_id") or DEFAULT_USER_ID}


def _family(language: str) -> str:
    return LANG_SCRIPT_FAMILY.get(language, "latin")


def _explain(profile: dict) -> str:
    return episodes.explain_lang_of(profile)


def choose_explain_lang(language: str, ui_lang: str | None = None) -> str:
    """§ 14, n° 14 : Gemma écrit dans la langue de l'interface quand la langue
    cible le permet (données anglaises présentes, et on n'explique pas
    l'anglais en anglais) ; en français sinon."""
    from i18n import current_lang

    wanted = ui_lang or current_lang()
    allowed = explain_languages(language)
    return wanted if wanted in allowed else allowed[0]


# ── Onboarding et test de niveau (E1-E2, R25-R26) ─────────────────────────────

def onboarding(language: str, interests: list[str], has_studied: bool) -> dict:
    """E1 : centres d'intérêt et choix « séance zéro » ou test de niveau. Un
    débutant voit son épisode 1 s'écrire (bible, arc, texte) pendant la séance
    zéro ; un apprenant qui passe le test le verra partir au rendu du test.

    C'est aussi là que la langue d'explication est choisie, d'après celle de
    l'interface, avant tout contenu : elle reste ensuite celle du feuilleton."""
    profile = ensure_feuilleton(language)
    cleaned = [s.strip()[:40] for s in interests or [] if isinstance(s, str) and s.strip()][:8]
    store.update_profile_fields(profile["id"], interests=cleaned)
    profile["interests"] = cleaned
    if profile.get("onboarding_done") or store.list_episodes(profile["id"], limit=1):
        # Déjà engagé dans le feuilleton : seuls les centres d'intérêt changent.
        return {"ok": True, "next": "home"}
    if not store.get_latest_bible(profile["id"]):
        store.update_profile_fields(profile["id"], explain_lang=choose_explain_lang(language))
        profile = _profile(profile["id"])
    if has_studied:
        return {"ok": True, "next": "placement"}
    store.update_profile_fields(profile["id"], program_order=0, ladder_step=progress.target_step(language, 1))
    progress.record_level({**profile, "program_order": 1}, language, 1, "placement")
    profile = _profile(profile["id"])
    episodes.schedule_episode(profile, language, 1, current=None, signals=None)
    return {"ok": True, "next": "zero"}


def placement_items(language: str) -> dict:
    """E2 : items du test SANS leurs clés ; la bible part pendant le test (R26)."""
    profile = ensure_feuilleton(language)
    items = store.get_placement_items(language)
    if not items:
        raise RunError("test de niveau absent pour cette langue")
    _start_bible_in_background(profile, language)
    lang = _explain(profile)
    # Les choix traduits gardent l'ordre des originaux : la clé reste l'index.
    return {"items": [
        {"id": it["id"], "kind": it["kind"], "prompt": localized(it, "prompt", lang),
         "choices": localized(it, "choices", lang), "cefr": it["cefr"]}
        for it in items
    ]}


def _start_bible_in_background(profile: dict, language: str) -> None:
    import threading

    if store.get_latest_bible(profile["id"]):
        return

    def _job() -> None:
        try:
            episodes.ensure_bible(profile, language)
        except Exception:  # pragma: no cover - la bible se refera à la génération de l'épisode
            logger.debug("Bible en tâche de fond ignorée", exc_info=True)

    if episodes.RUN_IN_BACKGROUND:
        threading.Thread(target=_job, daemon=True, name=f"lang-bible-{profile['id']}").start()
    else:
        _job()


def placement_submit(language: str, answers: dict) -> dict:
    """E2 : correction déterministe contre les clés écrites à la main ; point de
    départ = dernier point réussi de façon consécutive, moins une marge (R25)."""
    profile = ensure_feuilleton(language)
    items = store.get_placement_items(language)
    if not items:
        raise RunError("test de niveau absent pour cette langue")
    answers = answers or {}
    results = []
    passed: list[str] = []
    streak_open = True
    for it in items:
        given = answers.get(it["id"])
        ok = given is not None and str(given) == str(it["answer"])
        results.append({"id": it["id"], "correct": ok})
        if ok and streak_open:
            passed.append(it["program_point"])
        elif not ok:
            streak_open = False
    start = progress.placement_start_order(language, passed)
    store.update_profile_fields(
        profile["id"], program_order=start - 1, ladder_step=progress.target_step(language, start),
        onboarding_done=1, placement_done=1,
    )
    cefr = progress.record_level({**profile, "program_order": start}, language, start, "placement")
    profile = _profile(profile["id"])
    episodes.schedule_episode(profile, language, 1, current=None, signals=None)
    point = store.get_point_by_order(language, start)
    return {
        "ok": True, "level": cefr, "start_order": start,
        "start_point": localized(point, "title", _explain(profile)) if point else "",
        "correct": sum(1 for r in results if r["correct"]), "total": len(results),
    }


# ── Affichage d'un épisode (aides décidées ici) ───────────────────────────────

def display_episode(profile: dict, language: str, episode: dict) -> dict:
    """Épisode prêt à rendre : chaque jeton porte ce que l'apprenant voit
    encore (pinyin des caractères non acquis, niveau de vocalisation arabe,
    translittération sous les lettres non acquises), le glossaire ce que la
    bulle du tap affiche."""
    fam = _family(language)
    lexicon = store.get_lexicon(profile["id"])
    acquired = {lemma for lemma, row in lexicon.items() if row.get("acquired_at")}
    gloss = episode.get("glossary") or []
    aids = (episode.get("aids") or {}).get("lines") or []
    reported = store.reported_tokens(episode["id"])
    level = 0
    letters_acq: set[str] = set()
    chars_acq: set[str] = set()
    if fam == "arabe":
        level = arabic_aid_level(*progress.program_position(language, profile.get("program_order") or 1))
        letters_acq = acquired_units(profile["id"], ARABIC_SCRIPT)
    elif fam == "hanzi":
        chars_acq = acquired_units(profile["id"], HANZI_SCRIPT)
    lines = []
    for li, ln in enumerate(episode.get("lines") or []):
        row = aids[li] if li < len(aids) else []
        tokens = []
        for ti, tok in enumerate(ln.get("tokens") or []):
            out = {"text": tok["text"], "w": bool(tok.get("w"))}
            if tok.get("w"):
                aid = row[ti] if ti < len(row) else {}
                gi = tok.get("g")
                out["g"] = gi
                if fam == "hanzi" and aid.get("py"):
                    out["ruby"] = [{**s, "show": s["hanzi"] not in chars_acq} for s in aid["py"]]
                    out["suspect"] = bool(aid.get("suspect"))
                elif fam == "arabe":
                    lemma = gloss[gi].get("lemma") if gi is not None and gi < len(gloss) else None
                    out.update(arabic_word_display(
                        tok["text"], level=level, word_acquired=lemma in acquired, letters_acquired=letters_acq,
                    ))
                    out["suspect"] = bool(aid.get("suspect"))
                    out["validated"] = aid.get("validated")
                if (li, ti) in reported:
                    out["reported"] = True
            tokens.append(out)
        lines.append({"speaker": ln.get("speaker", ""), "translation": ln.get("translation", ""), "tokens": tokens})
    glossary = []
    for entry in gloss:
        lemma = entry.get("lemma") or entry.get("form")
        glossary.append({
            "form": entry.get("form"), "lemma": lemma, "translation": entry.get("translation"),
            "pos": entry.get("pos"), "gender": entry.get("gender"), "article": entry.get("article"),
            "pron": entry.get("pron"), "vocalized": entry.get("vocalized"),
            "faux_ami": entry.get("faux_ami"), "acquired": lemma in acquired,
            "transparent": bool(entry.get("transparent"))
            and int(episode.get("episode_n") or 0) <= LANG_TRANSPARENT_FLAG_UNTIL_EPISODE,
        })
    return {
        "id": episode["id"], "n": episode["episode_n"], "title": episode.get("title", ""),
        "summary": episode.get("summary", ""), "teaser": episode.get("teaser", ""),
        "format": episode.get("format"), "kind": episode.get("kind"), "family": fam,
        "dir": "rtl" if fam == "arabe" else "ltr", "aid_level": level or None,
        "tone_colors": LANG_ZH_TONE_COLORS if fam == "hanzi" else False,
        "gender_colors": LANG_DE_GENDER_COLORS and language == "allemand",
        "explain_lang": _explain(profile), "lines": lines, "glossary": glossary,
    }


def _anchor_span(language: str, tokens: list[dict], needle: str) -> list[int]:
    span = find_token_span(tokens, needle)
    if span or _family(language) != "arabe":
        return span
    from services.lang_arabic import strip_harakat

    wanted = strip_harakat(needle).split()
    return [i for i, tok in enumerate(tokens) if tok.get("w") and strip_harakat(tok["text"]) in wanted]


def episode_notes(profile: dict, language: str, episode: dict) -> tuple[list[dict], list[str]]:
    """Notes numérotées : celles de Gemma, plus les notes automatiques
    (faux-amis N2, sandhi M6 une fois le point enseigné, clés M8 pas encore
    vues). Renvoie aussi les clés à marquer comme vues."""
    notes = []
    for n in episode.get("notes") or []:
        ln = (episode.get("lines") or [])[n["line"]] if n["line"] < len(episode.get("lines") or []) else None
        if ln:
            notes.append({"line": n["line"], "tokens": _anchor_span(language, ln["tokens"], n["anchor"]),
                          "kind": n["kind"], "text": n["text"], "auto": False})
    gloss = episode.get("glossary") or []

    def first_token(gi: int) -> tuple[int, int] | None:
        for li, ln in enumerate(episode.get("lines") or []):
            for ti, tok in enumerate(ln.get("tokens") or []):
                if tok.get("g") == gi:
                    return li, ti
        return None

    for gi, entry in enumerate(gloss):
        if entry.get("faux_ami"):
            pos = first_token(gi)
            if pos:
                notes.append({"line": pos[0], "tokens": [pos[1]], "kind": "usage", "auto": True,
                              "text": t("lang.feuilleton.note.faux_ami", form=entry["form"], note=entry["faux_ami"])})
    fam = _family(language)
    new_components: list[str] = []
    if fam == "hanzi":
        introduced = store.get_program_progress(profile["id"])
        sandhi_taught = any("sandhi" in pid or "yi_bu" in pid for pid in introduced)
        if sandhi_taught:
            for li, rules in enumerate((episode.get("aids") or {}).get("sandhi") or []):
                for rule in rules:
                    key = f"lang.feuilleton.note.sandhi.{rule['rule']}"
                    notes.append({"line": li, "tokens": [rule["token_idx"]], "kind": "prononciation", "auto": True,
                                  "text": t(key, hanzi=rule["hanzi"], src=rule["from"], dst=rule["to"])})
        from services.lang_mandarin import components_in

        seen = seen_units(profile["id"], COMPONENTS_SCRIPT)
        for gi, entry in enumerate(gloss):
            for comp in components_in(entry.get("form") or ""):
                if comp["id"] in seen or comp["id"] in new_components:
                    continue
                pos = first_token(gi)
                if not pos:
                    continue
                new_components.append(comp["id"])
                examples = "、".join(e["hanzi"] for e in comp.get("examples") or [])
                notes.append({"line": pos[0], "tokens": [pos[1]], "kind": "grammaire", "auto": True,
                              "text": t("lang.feuilleton.note.component", char=comp["char"],
                                        meaning=localized(comp, "meaning", _explain(profile)),
                                        word=entry["form"], examples=examples)})
    notes.sort(key=lambda n: (n["line"], n["tokens"][0] if n["tokens"] else 0))
    for i, n in enumerate(notes, start=1):
        n["n"] = i
    return notes, new_components


def _point_view(language: str, episode: dict, explain_lang: str = "fr") -> dict:
    point = dict(episode.get("point") or {})
    point_meta = store.get_point(language, episode.get("program_point_id") or "") or {}
    highlights = []
    for example in point.get("examples") or []:
        for li, ln in enumerate(episode.get("lines") or []):
            span = _anchor_span(language, ln["tokens"], example)
            if span:
                highlights.append({"line": li, "tokens": span, "example": example})
                break
    return {
        "title": localized(point_meta, "title", explain_lang) or "",
        "learner_goal": localized(point_meta, "learner_goal", explain_lang) or "",
        "kind": point_meta.get("kind"), "observation": point.get("observation", ""),
        "explanation": point.get("explanation", ""), "highlights": highlights,
    }


# ── Choix du mode (R1-R2) ─────────────────────────────────────────────────────

def _bilan_due(profile: dict) -> bool:
    n = int(profile.get("episode_n") or 0)
    return n > 0 and n % (LANG_BILAN_EVERY - 1) == 0 and int(profile.get("last_bilan_episode_n") or 0) < n


def choose_mode(profile: dict, language: str, *, requested: str | None, absence_days: int | None) -> tuple[str, dict]:
    """R1, par ordre de priorité : onboarding -> reprise (absence) -> bilan ->
    épisode prêt -> relecture (et la génération part). L'apprenant peut
    toujours demander une séance courte ou « juste relire »."""
    if not profile.get("onboarding_done"):
        return "zero", {}
    tier = activity.absence_tier(absence_days)
    next_n = int(profile.get("episode_n") or 0) + 1
    ready = store.get_episode_by_n(profile["id"], next_n)
    ready = ready if ready and ready["status"] == "ready" else None
    if requested == "relecture":
        return "relecture", {"requested": True}
    if requested == "court":
        return ("court", {"episode": ready, "requested": True}) if ready else ("relecture", {"fallback": "court"})
    if profile.get("replay_queue"):
        return "relecture", {"queued": True}
    if tier in ("reprise", "reprise_controle"):
        return "reprise", {"tier": tier}
    if _bilan_due(profile):
        return "bilan", {}
    if ready:
        return "episode", {"episode": ready, "long_recall": tier == "rappel_long"}
    return "relecture", {"fallback": "episode_not_ready"}


def _ensure_next_generation(profile: dict, language: str) -> None:
    """R1.6 : l'épisode à jouer manque ou a échoué -> il part tout de suite."""
    next_n = int(profile.get("episode_n") or 0) + 1
    if _bilan_due(profile):
        return
    current = store.get_episode_by_n(profile["id"], next_n - 1) if next_n > 1 else None
    episodes.schedule_episode(profile, language, next_n, current=current, signals=None)


# ── Construction des étapes (R3-R13) ──────────────────────────────────────────

def _step(key: str, kind: str | None = None, **content) -> dict:
    kind = kind or key
    base = kind.split("_")[0] if kind.startswith("relecture") else kind
    return {"key": key, "kind": kind, "budget_s": LANG_STEP_BUDGET_S.get(base, 120),
            "essential": key in LANG_ESSENTIAL_STEPS or kind == "au_revoir", **content}


def _feeling(run_count: int) -> dict:
    q = FEELING_QUESTIONS[run_count % len(FEELING_QUESTIONS)]
    return {"question": f"lang.feuilleton.feel.{q}",
            "options": [f"lang.feuilleton.feel.{q}.{o}" for o in FEELING_OPTIONS]}


def _take_away(language: str, episode: dict) -> dict | None:
    """R8 : la phrase à emporter — la plus courte réplique qui contient un
    exemple du point du jour."""
    examples = (episode.get("point") or {}).get("examples") or []
    best = None
    for li, ln in enumerate(episode.get("lines") or []):
        text = "".join(tok["text"] for tok in ln["tokens"])
        if any(ex in text for ex in examples):
            size = len(words(text))
            if best is None or size < best[0]:
                best = (size, li, ln)
    if best is None:
        return None
    _size, li, ln = best
    return {"episode_ref": episode["id"], "line": li, "translation": ln.get("translation", "")}


def _relecture_choice(profile: dict, exclude: set[int]) -> list[tuple[dict, str]]:
    """R10 : le dernier épisode joué et un plus ancien qui avait suscité le plus de taps."""
    played = store.played_episodes(profile["id"], limit=60)
    out: list[tuple[dict, str]] = []
    if played and played[0]["id"] not in exclude:
        out.append((played[0], "last"))
    older = [e for e in played[1:] if e["id"] not in exclude]
    if older and len(out) < LANG_RELECTURE_EPISODES:
        taps = store.p2_reveal_counts(profile["id"])
        out.append((max(older, key=lambda e: (taps.get(e["id"], 0), -e["episode_n"])), "hard"))
    return out[:LANG_RELECTURE_EPISODES]


def _second_wave(profile: dict, episode_n: int, family: str, seed: int) -> tuple[dict | None, list[dict]]:
    """R7 : 3 à 6 répliques de l'épisode N − 49, en français."""
    if episode_n < LANG_SECOND_WAVE_START:
        return None, []
    old = store.get_episode_by_n(profile["id"], episode_n - LANG_SECOND_WAVE_OFFSET)
    if not old or old["status"] != "played":
        return None, []
    rng = random.Random(seed)
    candidates = [li for li, ln in enumerate(old["lines"]) if 3 <= len([x for x in ln["tokens"] if x.get("w")]) <= 14]
    rng.shuffle(candidates)
    n = min(len(candidates), rng.randint(*LANG_SECOND_WAVE_LINES))
    chosen = sorted(candidates[:n])
    return old, [{"line": li, "translation": old["lines"][li]["translation"], "typing": family == "latin"}
                 for li in chosen]


def _phrases_view(language: str, explain_lang: str = "fr") -> list[dict]:
    """Phrases de survie (séance zéro) avec leurs aides écrites à la main,
    traduites dans la langue d'explication."""
    from services import lang_arabic as arabic

    out = []
    for ph in (onboarding_data(language) or {}).get("phrases") or []:
        # Une phrase peut changer avec la langue de l'apprenant (« Parlez-vous
        # français ? » -> « … anglais ? ») : `target_en` et ses aides écrites.
        item = {"target": localized(ph, "target", explain_lang), "translation": localized(ph, "translation", explain_lang),
                "note": localized(ph, "note", explain_lang)}
        if language == "arabe":
            vocalized = localized(ph, "vocalized", explain_lang)
            item.update(target=vocalized, pron=arabic.transliterate(vocalized))
        elif language == "mandarin":
            item["pron"] = localized(ph, "pinyin", explain_lang)
        out.append(item)
    return out


def _cards_view(profile: dict, language: str) -> list[dict]:
    return [{"id": c["id"], "front": c["front"], "back": c["back"], "pronunciation": c.get("pronunciation")}
            for c in progress.due_cards(profile, language)]


def build_plan(profile: dict, language: str, mode: str, info: dict, *, run_seed: int,
               absence_days: int | None) -> dict:
    fam = _family(language)
    lang = _explain(profile)
    plan: dict = {
        "mode": mode, "language": language, "family": fam, "rtl": fam == "arabe", "explain_lang": lang,
        "target_s": LANG_RUN_SHORT_TARGET_S if mode == "court" else LANG_RUN_TARGET_S,
        "max_s": LANG_RUN_MAX_S, "idle_cutoff_s": LANG_IDLE_CUTOFF_S,
        "episodes": {}, "steps": [], "readings": [], "items": {},
        "absence": {"days": absence_days, "tier": activity.absence_tier(absence_days)},
        "tone": activity.message_tone(profile["id"]), "episode_id": None, "episode_n": None,
        "pregen_step": None, "component_units": [], "info": {k: v for k, v in info.items() if k != "episode"},
    }
    runs_done = store.count_runs(profile["id"])

    def add_episode(ep: dict) -> int:
        plan["episodes"][str(ep["id"])] = display_episode(profile, language, ep)
        return ep["id"]

    def add_reading(step_key: str, ep: dict, pass_: str) -> None:
        plan["readings"].append({"step": step_key, "episode_id": ep["id"], "pass": pass_})

    def register_items(step_key: str, items: list[dict]) -> None:
        for it in items:
            plan["items"][it["ref"]] = {
                "kind": it["kind"], "expected": it.get("expected"), "lexemes": it.get("lexemes") or [],
                "units": it.get("units") or [], "step": step_key, "episode_id": it.get("episode_id"),
            }

    steps = plan["steps"]
    if mode == "zero":
        # Les centres d'intérêt ont été demandés par l'écran d'onboarding (E1).
        steps.append(_step("accueil", variant="zero"))
        steps.append(_step("phrases", phrases=_phrases_view(language, lang)))
        preview = localized(onboarding_data(language), "script_preview", lang)
        if preview:
            steps.append(_step("ecriture", preview=preview))
        steps.append(_step("au_revoir", take_away=None, teaser="", feeling=_feeling(runs_done)))
        return plan

    if mode in EPISODE_MODES:
        ep = info["episode"]
        plan["episode_id"], plan["episode_n"] = ep["id"], ep["episode_n"]
        add_episode(ep)
        prev = store.get_episode_by_n(profile["id"], ep["episode_n"] - 1) if ep["episode_n"] > 1 else None
        if mode == "court":
            steps.append(_step("rappel", teaser_only=True, teaser=(prev or {}).get("teaser", ""), episode_ref=None))
        elif info.get("long_recall"):
            recent = store.played_episodes(profile["id"], limit=LANG_RECAP_LONG_EPISODES)
            steps.append(_step("rappel", long=True, summaries=[e["summary"] for e in reversed(recent)],
                               episode_ref=None))
            for i, (old, why) in enumerate(_relecture_choice(profile, set()), start=1):
                key = f"relecture_{i}"
                steps.append(_step(key, "relecture", episode_ref=add_episode(old), why=why))
                add_reading(key, old, "relecture")
        elif prev and prev["status"] == "played":
            steps.append(_step("rappel", episode_ref=add_episode(prev), summary=prev["summary"], long=False))
            add_reading("rappel", prev, "rappel")
        translation = (ep.get("params") or {}).get("translation", "toujours")
        steps.append(_step("episode_p1", episode_ref=ep["id"], translation=translation))
        steps.append(_step("episode_p2", episode_ref=ep["id"]))
        add_reading("episode_p2", ep, "p2")
        if mode == "episode":
            notes, components = episode_notes(profile, language, ep)
            plan["component_units"] = components
            steps.append(_step("notes", episode_ref=ep["id"], notes=notes))
        micro = games.point_micro_items(ep, fam, run_seed)
        register_items("point", micro)
        steps.append(_step("point", episode_ref=ep["id"], point=_point_view(language, ep, lang), items=micro))
        if mode == "episode":
            recent_kinds = [[g["kind"] for g in s.get("games", [])]
                            for r in store.recent_runs(profile["id"], limit=2)
                            for s in (r.get("plan") or {}).get("steps", []) if s.get("kind") == "jeux"]
            chosen = games.choose_games(ep, fam, run_seed, recent_kinds)
            for g in chosen:
                register_items("jeux", g["items"])
            if chosen:
                steps.append(_step("jeux", episode_ref=ep["id"], games=chosen))
            old, sw_lines = _second_wave(profile, ep["episode_n"], fam, run_seed)
            if old and sw_lines:
                plan["second_wave_episode_id"] = old["id"]
                steps.append(_step("deuxieme_vague", episode_ref=add_episode(old), lines=sw_lines))
            if ep["episode_n"] in LANG_MILESTONES_EPISODE_1:
                first = store.get_episode_by_n(profile["id"], 1)
                if first and first["status"] == "played":
                    first_taps = _first_reading_taps(profile["id"], first["id"])
                    steps.append(_step("jalon", episode_ref=add_episode(first), first_taps=first_taps,
                                       tokens=progress.word_token_count(first["lines"])))
                    add_reading("jalon", first, "jalon")
        plan["pregen_step"] = LANG_PREGEN_TRIGGER_STEP if mode == "episode" else "point"
        steps.append(_step("au_revoir", take_away=_take_away(language, ep), teaser=ep.get("teaser", ""),
                           feeling=_feeling(runs_done)))
        return plan

    if mode == "bilan":
        since = int(profile.get("last_bilan_episode_n") or 0)
        group = [e for e in store.played_episodes(profile["id"], limit=LANG_BILAN_EVERY * 2)
                 if e["episode_n"] > since and e.get("program_point_id")]
        group.sort(key=lambda e: e["episode_n"])
        points, seen_points, micro_all = [], set(), []
        for e in group:
            if e["program_point_id"] in seen_points:
                continue
            seen_points.add(e["program_point_id"])
            view = _point_view(language, e, lang)
            view["episode_ref"] = add_episode(e)
            points.append(view)
            micro_all += [it for it in games.point_micro_items(e, fam, run_seed + e["episode_n"])
                          if it["kind"] == "bonne_forme"][:1]
            add_reading("recap", e, "recap")
        plan["bilan_points"] = sorted(seen_points)
        steps.append(_step("recap", points=points))
        for i, it in enumerate(micro_all):
            it["ref"] = f"bilan.{i}.{it['ref']}"
        register_items("jeux", micro_all)
        if micro_all:
            steps.append(_step("jeux", games=[{"kind": "bonne_forme", "ease": 2, "items": micro_all}]))
        cards = _cards_view(profile, language)
        if cards:
            steps.append(_step("cartes", cards=cards))
        steps.append(_step("au_revoir", take_away=None, teaser="", feeling=_feeling(runs_done)))
        return plan

    if mode == "reprise":
        tier = info.get("tier")
        recent = store.played_episodes(profile["id"], limit=LANG_RECAP_LONG_EPISODES)
        steps.append(_step("accueil", variant="reprise", absence_days=absence_days))
        if recent:
            steps.append(_step("recap", summaries=[e["summary"] for e in reversed(recent)], points=[]))
            last = recent[0]
            steps.append(_step("relecture_1", "relecture", episode_ref=add_episode(last), why="last"))
            add_reading("relecture_1", last, "relecture")
        # Le plafond de cartes dues (P13) vaut pour la séance entière : un
        # contrôle sur cartes les prend sur la même pile.
        cards = _cards_view(profile, language)
        if tier == "reprise_controle":
            controle = _controle_step(profile, language, plan, add_episode, register_items, run_seed, cards)
            steps.append(controle)
            cards = cards[len(controle.get("cards") or []):]
        if cards:
            steps.append(_step("cartes", cards=cards))
        steps.append(_step("au_revoir", take_away=None, teaser="", feeling=_feeling(runs_done)))
        return plan

    # relecture
    queue = list(profile.get("replay_queue") or [])
    chosen: list[tuple[dict, str]] = []
    if queue:
        ep = store.get_episode(int(queue[0]))
        if ep:
            chosen.append((ep, "queued"))
        plan["replay_consumed"] = int(queue[0])
    else:
        chosen = _relecture_choice(profile, set())
    for i, (ep, why) in enumerate(chosen, start=1):
        key = f"relecture_{i}"
        steps.append(_step(key, "relecture", episode_ref=add_episode(ep), why=why))
        add_reading(key, ep, "relecture")
    if not chosen:
        steps.append(_step("phrases", phrases=_phrases_view(language, lang), waiting=True))
    cards = _cards_view(profile, language)
    if cards:
        steps.append(_step("cartes", cards=cards))
    steps.append(_step("au_revoir", take_away=None, teaser="", feeling=_feeling(runs_done)))
    return plan


def _first_reading_taps(profile_id: int, episode_id: int) -> int:
    reveals = store.reveals_for_episode(profile_id, episode_id, "p2")
    if not reveals:
        return 0
    first_run = reveals[0]["run_id"]
    return sum(1 for r in reveals if r["run_id"] == first_run)


def _controle_step(profile, language, plan, add_episode, register_items, seed, cards: list[dict]) -> dict:
    """§ 14.2, 21 jours et plus : mini-contrôle en deuxième vague sur trois
    anciens épisodes, ou sur des cartes avant l'épisode 50."""
    if int(profile.get("episode_n") or 0) >= LANG_SECOND_WAVE_START:
        rng = random.Random(seed)
        blocks = []
        for ep in store.played_episodes(profile["id"], limit=LANG_REPRISE_CONTROLE_EPISODES):
            lines = [li for li, ln in enumerate(ep["lines"]) if len([x for x in ln["tokens"] if x.get("w")]) >= 3]
            rng.shuffle(lines)
            blocks.append({"episode_ref": add_episode(ep),
                           "lines": [{"line": li, "translation": ep["lines"][li]["translation"],
                                      "typing": _family(language) == "latin"} for li in sorted(lines[:2])]})
        return _step("controle", "controle", mode="episodes", blocks=blocks)
    return _step("controle", "controle", mode="cartes", cards=cards[:6])


# ── Cycle de vie d'une séance (E3-E6) ─────────────────────────────────────────

def start_run(language: str, mode: str | None = None) -> dict:
    """E3 : plan complet de la séance, immédiatement (aucune attente de Gemma).
    Une séance du jour restée ouverte est reprise à l'étape atteinte (R2) ;
    celles des jours précédents passent `abandoned`."""
    profile = ensure_feuilleton(language)
    today = activity.study_date()
    for run in store.open_runs(profile["id"]):
        if run.get("study_date") != today:
            store.update_run(run["id"], status="abandoned", end_reason="quitte")
        elif mode in (None, run["mode"]):
            return run_view(run["id"], resumed=True)
        else:
            store.update_run(run["id"], status="abandoned", end_reason="quitte")
    days = activity.absence_days(profile["id"], today)
    chosen, info = choose_mode(profile, language, requested=mode, absence_days=days)
    if chosen == "relecture" and info.get("fallback") and profile.get("onboarding_done"):
        _ensure_next_generation(profile, language)
    if chosen == "bilan":
        _start_bilan_generation(profile, language)
    if chosen == "reprise":
        _prepare_respiration(profile, language)
    activity.maybe_trigger_weekly(profile, language, today)
    # R6 : la graine des jeux est l'id de la séance — variété d'une séance à
    # l'autre, mais reproductible.
    run_id = store.create_run(profile["id"], mode=chosen, plan={}, episode_id=None, second_wave_episode_id=None,
                              absence_days=days, study_date=today)
    plan = build_plan(profile, language, chosen, info, run_seed=run_id, absence_days=days)
    store.update_run(run_id, plan=plan, episode_id=plan.get("episode_id"),
                     second_wave_episode_id=plan.get("second_wave_episode_id"))
    activity.record(profile["id"], today, first_start_local=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return run_view(run_id)


def _start_bilan_generation(profile: dict, language: str) -> None:
    """R9 / G16 : pendant le bilan, l'arc suivant puis l'épisode suivant."""
    n = int(profile.get("episode_n") or 0) + 1
    current = store.get_episode_by_n(profile["id"], n - 1)
    episodes.schedule_episode(profile, language, n, current=current, signals=None)


def _prepare_respiration(profile: dict, language: str) -> None:
    """§ 14.2 : après une reprise, l'épisode suivant est une respiration. Un
    épisode normal déjà écrit d'avance est réécrit comme tel."""
    store.update_profile_fields(profile["id"], force_respiration=1)
    n = int(profile.get("episode_n") or 0) + 1
    upcoming = store.get_episode_by_n(profile["id"], n)
    if upcoming and upcoming["kind"] == "normal" and upcoming["status"] in ("ready", "failed", "queued"):
        current = store.get_episode_by_n(profile["id"], n - 1)
        refreshed = _profile(profile["id"])
        decision = progress.next_episode_decision(refreshed, language, current=current, signals=None, episode_n=n)
        store.update_episode(
            upcoming["id"], kind=decision["kind"], program_point_id=decision["program_point_id"],
            format=decision["format"], ladder_step=decision["ladder_step"], params=decision["params"],
            status="queued", lines=None, glossary=None, notes=None, point=None, aids=None,
        )
        if decision["params"].get("forced"):
            store.update_profile_fields(profile["id"], force_respiration=0)
        episodes.trigger_generation(profile["id"], n)


def run_view(run_id: int, *, resumed: bool = False) -> dict:
    """E4 : le plan d'une séance, l'étape atteinte et les étapes déjà faites."""
    run = store.get_run(run_id)
    if not run:
        raise RunError("séance introuvable")
    plan = dict(run["plan"])
    plan.pop("items", None)  # clés de correction : déjà dans chaque étape
    done = [s["step"] for s in store.get_steps(run_id) if s["ended_at"]]
    return {"run_id": run_id, "status": run["status"], "current_step": run.get("current_step"),
            "done_steps": done, "resumed": resumed, "effective_s": run.get("effective_seconds") or 0, **plan}


def record_events(run_id: int, events: list[dict], current_step: str | None = None) -> dict:
    """E5 : lot d'événements (étapes, taps, réponses, auto-évaluations, cartes).
    Les réponses sont recorrigées ici (R23) ; l'étape de déclenchement lance la
    pré-génération de l'épisode suivant (G16) ; le plafond est calculé (R24)."""
    from services.flashcards import review_flashcard

    run = store.get_run(run_id)
    if not run:
        raise RunError("séance introuvable")
    if run["status"] != "in_progress":
        return {"ok": False, "status": run["status"]}
    plan = run["plan"]
    profile_id = run["profile_id"]
    day = run.get("study_date") or activity.study_date()
    steps_before = {s["step"]: s for s in store.get_steps(run_id)}
    added_seconds = reveals = answered = cards = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for ev in events or []:
        kind = ev.get("type")
        if kind == "step":
            step = str(ev.get("step") or "")[:40]
            if not step:
                continue
            seconds = max(0, min(int(ev.get("active_s") or 0), LANG_RUN_MAX_S))
            previous = int((steps_before.get(step) or {}).get("seconds") or 0)
            added_seconds += max(0, seconds - previous)
            signal = ev.get("signal") if ev.get("signal") in ("compris", "a_peu_pres", "pas_compris") else None
            # started_at ne s'écrit qu'une fois (COALESCE) : un lot renvoyé ne
            # déplace pas le début d'une étape.
            store.upsert_step(run_id, step, started_at=now, ended_at=now if ev.get("ended") else None,
                              seconds=seconds, skipped=bool(ev.get("skipped")), signal=signal)
            steps_before[step] = {"seconds": max(seconds, previous)}
        elif kind == "reveal":
            try:
                reveals += store.add_reveals(run_id, run.get("episode_id"), [{
                    "episode_id": int(ev["episode_id"]), "line_idx": int(ev["line"]), "token_idx": int(ev["token"]),
                    "pass": str(ev.get("pass") or "p2")[:12],
                }])
            except (KeyError, TypeError, ValueError):
                continue
        elif kind == "answer":
            ref = str(ev.get("item") or "")
            item = (plan.get("items") or {}).get(ref)
            if not item:
                continue
            correct = games.grade(item, ev.get("given"))
            store.upsert_attempt(run_id, item["step"], item["kind"], ref, expected={
                "value": item.get("expected"), "lexemes": item.get("lexemes"), "units": item.get("units"),
            }, given=ev.get("given"), correct=correct, ms=ev.get("ms"))
            answered += int(correct is not None)
        elif kind == "rating":
            rating = ev.get("rating")
            if rating in progress.SECOND_WAVE_SCORES:
                store.upsert_second_wave_rating(run_id, ev.get("episode_id"), int(ev.get("line") or 0),
                                                typed=(ev.get("typed") or None), rating=rating)
        elif kind == "card":
            verdict = ev.get("verdict")
            if verdict in ("correct", "partial", "incorrect") and ev.get("card_id"):
                try:
                    review_flashcard(int(ev["card_id"]), verdict)
                    cards += 1
                except Exception:
                    logger.debug("Révision de carte ignorée", exc_info=True)
    effective = int(run.get("effective_seconds") or 0) + added_seconds
    fields = {"effective_seconds": effective}
    if current_step:
        fields["current_step"] = str(current_step)[:40]
    store.update_run(run_id, **fields)
    activity.record(profile_id, day, effective_seconds=added_seconds, reveals=reveals,
                    items_answered=answered, cards_reviewed=cards)
    trigger = plan.get("pregen_step")
    if trigger and (current_step == trigger or trigger in steps_before) and not plan.get("pregen_done"):
        _on_episode_read(run_id)
    cap = effective >= LANG_RUN_MAX_S
    return {"ok": True, "effective_s": effective, "cap_reached": cap,
            "skip_to": "au_revoir" if cap else None}


def _on_episode_read(run_id: int) -> None:
    """L'épisode est lu (étape de déclenchement atteinte) : il est joué, son
    point introduit, et l'épisode suivant part avec les signaux du jour."""
    run = store.get_run(run_id)
    plan = run["plan"]
    plan["pregen_done"] = True
    store.update_run(run_id, plan=plan)
    profile = _profile(run["profile_id"])
    episode = store.get_episode(run["episode_id"]) if run.get("episode_id") else None
    if not episode:
        return
    _mark_played(profile, plan["language"], episode)
    profile = _profile(run["profile_id"])
    signals = progress.episode_signals(run_id)
    previous_run = next((r for r in store.recent_runs(profile["id"], limit=1)), None)
    if previous_run:
        prev_signals = (previous_run.get("plan") or {}).get("signals") or {}
        for key in ("games_rate", "second_wave_rate"):
            if signals.get(key) is None:
                signals[key] = prev_signals.get(key)
    episodes.pregenerate_after(profile, plan["language"], episode, signals)


def _mark_played(profile: dict, language: str, episode: dict) -> None:
    # Les mots de l'épisode entrent au lexique AVANT que le suivant s'écrive :
    # sans ça, l'épisode N+1 comptait comme « nouveaux » les mots de N.
    progress.ensure_lexemes(profile["id"], episode)
    if episode["status"] != "played":
        store.update_episode(episode["id"], status="played",
                             first_played_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if int(profile.get("episode_n") or 0) < episode["episode_n"]:
        store.update_profile_fields(profile["id"], episode_n=episode["episode_n"])
        update_lang_profile(profile["id"], touch_last_session=True)
    if episode["kind"] == "normal":
        progress.mark_point_introduced(profile, language, episode.get("program_point_id"), episode["episode_n"])


def complete_run(run_id: int, end_reason: str = "fini", feeling: str | None = None) -> dict:
    """E6 : clôture — progression (programme, lexique, signes, cartes), activité
    du jour, ressenti relié au profil métacognitif. Renvoie ce qui a été gagné
    (écran de fin sans score, F11)."""
    run = store.get_run(run_id)
    if not run:
        raise RunError("séance introuvable")
    if run["status"] == "completed":
        return {"ok": True, "already": True}
    plan = run["plan"]
    language = plan["language"]
    profile = _profile(run["profile_id"])
    reason = end_reason if end_reason in ("fini", "plafond", "quitte") else "fini"
    lexicon_before = store.lexicon_counts(profile["id"])
    episode = store.get_episode(run["episode_id"]) if run.get("episode_id") else None
    read = any(s["step"] in ("episode_p1", "episode_p2") and s["ended_at"] and not s["skipped"]
               for s in store.get_steps(run_id))
    if episode and run["mode"] in EPISODE_MODES:
        if read and not plan.get("pregen_done"):
            _on_episode_read(run_id)
            plan = store.get_run(run_id)["plan"]
        episode = store.get_episode(episode["id"])
        if episode["status"] != "played":
            episode = None  # quitté avant d'avoir lu : l'épisode reste à jouer
    signals = progress.episode_signals(run_id)
    plan["signals"] = signals
    store.update_run(run_id, plan=plan, status="completed", end_reason=reason, feeling=(feeling or "")[:80] or None,
                     ended_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    acquisition = progress.apply_run_acquisition(run_id)
    for unit in plan.get("component_units") or []:
        store.bump_script_unit(profile["id"], COMPONENTS_SCRIPT, unit, exposures=1)
    cards_created = 0
    new_words: list[str] = []
    if episode and run["mode"] in EPISODE_MODES:
        tapped = set()
        for r in store.get_reveals(run_id):
            if r["episode_id"] == episode["id"] and r["pass"] == "p2":
                try:
                    gi = episode["lines"][r["line_idx"]]["tokens"][r["token_idx"]].get("g")
                    if gi is not None:
                        tapped.add(episode["glossary"][gi].get("lemma") or episode["glossary"][gi]["form"])
                except (IndexError, KeyError, TypeError):
                    continue
        cards_created = progress.create_episode_flashcards(profile, language, episode, tapped)
        new_words = [g["form"] for g in episode.get("glossary") or [] if g.get("new")][:12]
    if run["mode"] == "bilan":
        progress.consolidate_points(profile, plan.get("bilan_points") or [])
        store.update_profile_fields(profile["id"], last_bilan_episode_n=int(profile.get("episode_n") or 0))
    if plan.get("second_wave_episode_id"):
        store.update_profile_fields(profile["id"], second_wave_started=1)
    if plan.get("replay_consumed"):
        queue = [e for e in profile.get("replay_queue") or [] if int(e) != int(plan["replay_consumed"])]
        store.update_profile_fields(profile["id"], replay_queue=queue)
    if run["mode"] == "zero":
        store.update_profile_fields(profile["id"], onboarding_done=1)
    day = run.get("study_date") or activity.study_date()
    activity.record(profile["id"], day, runs_completed=1, rereads=int(run["mode"] == "relecture"))
    _nudge(profile, run, plan, feeling)
    rewind = _rewind_suggestion(run_id, plan)
    lexicon_after = store.lexicon_counts(profile["id"])
    return {
        "ok": True, "mode": run["mode"],
        "episode": {"n": episode["episode_n"], "title": episode["title"]} if episode else None,
        "point": _point_view(language, episode, _explain(profile))["title"] if episode else None,
        "new_words": new_words, "cards_created": cards_created,
        "words_seen": lexicon_after["seen"], "words_acquired": lexicon_after["acquired"],
        "acquired_today": max(0, lexicon_after["acquired"] - lexicon_before["acquired"]),
        "units_acquired_today": acquisition.get("units", 0),
        "suggest_rewind": rewind,
    }


def _nudge(profile: dict, run: dict, plan: dict, feeling: str | None) -> None:
    """R8 : la séance rejoint le profil métacognitif commun, AVEC ou SANS
    réponse de ressenti. Rien n'est noté (lecture jamais notée) : la séance
    compte — c'est ce passage qui enregistre le jour d'étude commun, la série
    affichée ailleurs dans l'application (§ 14, n° 11) — sans déplacer les
    jauges. La réponse, si elle correspond à la question posée, s'y ajoute.

    En tâche de fond : la finalisation commune réécrit l'analyse générale de
    l'apprenant avec Gemma, et une séance n'attend jamais Gemma (P-1)."""
    au_revoir = next((s for s in plan.get("steps") or [] if s.get("kind") == "au_revoir"), {})
    question_key = (au_revoir.get("feeling") or {}).get("question")
    answered = bool(feeling and question_key and str(feeling).startswith(question_key + "."))
    responses = [t(feeling)] if answered else []
    questions = [t(question_key)] if answered else []
    metrics = {"duration_s": int(run.get("effective_seconds") or 0), "language": plan.get("language"),
               "questions_answered": 0, "pages_read": 0, "correct": 0, "success_rate": 0}
    user_id = int(profile.get("user_id") or DEFAULT_USER_ID)

    def _job() -> None:
        try:
            from services.session import nudge_metacog_profile

            nudge_metacog_profile(user_id, 0.0, responses, metrics, session_id=None, questions=questions, measures=0)
        except Exception:  # pragma: no cover - la clôture ne casse jamais sur le profil
            logger.debug("Nudge métacognitif (feuilleton) ignoré", exc_info=True)

    if activity.RUN_IN_BACKGROUND:
        import threading

        threading.Thread(target=_job, daemon=True, name=f"lang-nudge-{profile['id']}").start()
    else:
        _job()


def _rewind_suggestion(run_id: int, plan: dict) -> int | None:
    """§ 14.2 : après un contrôle raté, PROPOSER de relire quelques épisodes."""
    if not any(s.get("kind") == "controle" for s in plan.get("steps") or []):
        return None
    ratings = store.get_second_wave_ratings(run_id)
    scores = [progress.SECOND_WAVE_SCORES[r["rating"]] for r in ratings if r["rating"] in progress.SECOND_WAVE_SCORES]
    if not scores:
        return None
    return LANG_REWIND_EPISODES if sum(scores) / len(scores) < LANG_REPRISE_CONTROLE_OK else None


def accept_rewind(language: str) -> dict:
    """L'apprenant accepte de reculer : les dernières séances relisent les
    derniers épisodes, du plus ancien au plus récent, avant de reprendre."""
    profile = ensure_feuilleton(language)
    recent = store.played_episodes(profile["id"], limit=LANG_REWIND_EPISODES)
    queue = [e["id"] for e in reversed(recent)]
    store.update_profile_fields(profile["id"], replay_queue=queue)
    return {"ok": True, "queued": len(queue)}


# ── Accueil, bibliothèque, signalements (E7-E10) ──────────────────────────────

def language_status(language: str) -> dict:
    """E9 : l'écran d'accueil d'une langue. Aucun compteur de jours (F1). Une
    langue fermée par la porte V17 répond sa raison, sans créer de profil."""
    if is_pilot(language) and unavailable_reason(language):
        return {"language": language, "flow": "feuilleton", "family": _family(language),
                "unavailable": unavailable_reason(language)}
    profile = ensure_feuilleton(language)
    next_n = int(profile.get("episode_n") or 0) + 1
    upcoming = store.get_episode_by_n(profile["id"], next_n)
    order = int(profile.get("program_order") or 0)
    point = store.get_point_by_order(language, max(order, 1))
    counts = store.lexicon_counts(profile["id"])
    open_run = next((r for r in store.open_runs(profile["id"]) if r.get("study_date") == activity.study_date()), None)
    return {
        "language": language, "flow": "feuilleton", "family": _family(language),
        "onboarding_done": bool(profile.get("onboarding_done")),
        "episode_n": int(profile.get("episode_n") or 0), "next_episode": next_n,
        "next_status": upcoming["status"] if upcoming else None,
        "generating": episodes.is_generating(profile["id"]),
        "bilan_due": _bilan_due(profile),
        "level": progress.current_cefr(language, order), "explain_lang": _explain(profile),
        "program": {"order": order, "size": store.program_size(language),
                    "point": localized(point, "title", _explain(profile)) if point else ""},
        "words_seen": counts["seen"], "words_acquired": counts["acquired"],
        "episodes_played": store.count_played(profile["id"]),
        "open_run": open_run["id"] if open_run else None,
        "has_placement": bool(store.get_placement_items(language)),
    }


def library(language: str) -> list[dict]:
    """E7 : les épisodes déjà joués, pour une lecture libre sans score."""
    profile = ensure_feuilleton(language)
    return [{"id": e["id"], "n": e["episode_n"], "title": e["title"], "summary": e["summary"],
             "kind": e["kind"], "format": e["format"]}
            for e in store.played_episodes(profile["id"], limit=1000)]


def episode_view(episode_id: int) -> dict:
    episode = store.get_episode(episode_id)
    if not episode or episode["status"] != "played":
        raise RunError("épisode introuvable")
    profile = _profile(episode["profile_id"])
    language = profile["language"]
    notes, _components = episode_notes(profile, language, episode)
    return {**display_episode(profile, language, episode), "notes": notes,
            "point": _point_view(language, episode, _explain(profile))}


def report(episode_id: int, line_idx: int | None, token_idx: int | None, kind: str, comment: str) -> dict:
    """E8 / A8 : un signalement. Sur une vocalisation arabe, la forme passe
    `signale` et sort des jeux."""
    episode = store.get_episode(episode_id)
    if not episode:
        raise RunError("épisode introuvable")
    kind = kind if kind in ("vocalisation", "pinyin", "traduction", "glossaire", "autre") else "autre"
    report_id = store.add_report(episode["profile_id"], episode_id=episode_id, line_idx=line_idx,
                                 token_idx=token_idx, kind=kind, comment=(comment or "")[:500])
    if kind == "vocalisation" and line_idx is not None and token_idx is not None:
        from services import lang_arabic as arabic

        try:
            word = episode["lines"][line_idx]["tokens"][token_idx]["text"]
            profile = _profile(episode["profile_id"])
            store.set_vocalized_status(profile["language"], arabic.strip_harakat(word),
                                       arabic.stem_vocalized(word), "signale")
        except (IndexError, KeyError, TypeError):
            pass
    return {"ok": True, "id": report_id}


def warmup_cards(language: str) -> list[dict]:
    """E10 : cartes dues de la langue, plafonnées (P13)."""
    profile = ensure_feuilleton(language)
    return _cards_view(profile, language)


def compare_retranslation(original: str, typed: str) -> dict:
    """N5 : différences surlignées entre l'original et la saisie ; aucun LLM,
    l'apprenant s'auto-évalue."""
    return {"ops": word_diff(original or "", typed or "")}


def on_startup() -> None:
    """Démarrage : données de référence (D23), générations interrompues (G20)."""
    from services.lang_static import seed_lang_reference

    try:
        seed_lang_reference()
    except Exception:  # pragma: no cover - jamais bloquant au démarrage
        logger.exception("Injection des données de langue échouée")
    episodes.requeue_stuck()
