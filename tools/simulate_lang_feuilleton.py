"""Simulation longue du feuilleton (plan V13), sans Clikoda.

Rejoue N jours d'apprentissage sur une base jetable avec deux profils
d'apprenant — « aise » (peu de taps, bonnes réponses, assidu) et « difficulte »
(beaucoup de taps, réponses à moitié justes, absences fréquentes) — et des
épisodes synthétiques écrits directement en base à la place de Clikoda. Ce qui
est vérifié, c'est l'assembleur et la progression, pas la langue :

  * couverture du programme et respect des bornes de difficulté (±1 cran,
    bande autour du point courant, respirations bornées) ;
  * variété des jeux et des formes de texte ;
  * déclenchement des bilans, de la deuxième vague, des jalons, des reprises ;
  * plafond des cartes dues servies par séance.

    python tools/simulate_lang_feuilleton.py --language espagnol --days 120

La suite de tests en rejoue une version courte (tests/services/test_lang_simulation.py).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "nwol") not in sys.path:
    sys.path.insert(0, str(ROOT / "nwol"))

LEARNERS = {
    "aise": {"absent": 0.08, "long_gap": 0.01, "tap_rate": 0.02, "right": 0.92, "signal": "compris"},
    "difficulte": {"absent": 0.3, "long_gap": 0.04, "tap_rate": 0.18, "right": 0.5, "signal": "a_peu_pres"},
}
# Pseudo-mots : l'acquisition a besoin de mots qui reviennent d'un épisode à l'autre.
POOL = [f"{a}{b}{c}" for a in "bdklmnprst" for b in "aeiou" for c in ("la", "ro", "ne", "ti", "so", "mu")]


def _synthetic_episode(profile_id: int, episode_n: int) -> bool:
    """Remplace services.lang_episodes.generate_episode : un épisode valide,
    aux bornes de son palier, qui recycle les mots demandés."""
    from db import lang_episode_db as store
    from services.lang_text import segment

    episode = store.get_episode_by_n(profile_id, episode_n)
    params = episode["params"]
    rng = random.Random(profile_id * 7919 + episode_n)
    n_lines = round(sum(params["lines"]) / 2)
    wpl = params.get("words_per_line") or (8, 14)
    known = list(params.get("recycle") or [])
    fresh = [w for w in POOL[(episode_n * 5) % len(POOL):] + POOL][: params["new_words"][1]]
    vocabulary = (known + fresh + rng.sample(POOL, 20))[:60]
    speakers = ["Ana", "Luis", "Marta"]
    lines = []
    for i in range(n_lines):
        words = [rng.choice(vocabulary) for _ in range(rng.randint(*wpl))]
        text = " ".join(words).capitalize() + "."
        lines.append({"speaker": speakers[i % 3], "text": text, "translation": f"Traduction {i}.",
                      "tokens": segment(text)})
    forms = {}
    for ln in lines:
        for tok in ln["tokens"]:
            if tok["w"]:
                forms.setdefault(tok["text"].lower(), tok["text"])
    glossary = [{"form": f, "lemma": lemma, "translation": f"sens de {lemma}", "pos": "nom", "gender": "m",
                 "new": True} for lemma, f in forms.items()]
    index = {g["lemma"]: i for i, g in enumerate(glossary)}
    for ln in lines:
        for tok in ln["tokens"]:
            if tok["w"]:
                tok["g"] = index[tok["text"].lower()]
    ex1 = " ".join(lines[0]["text"].rstrip(".").split()[:2])
    ex2 = " ".join(lines[1]["text"].rstrip(".").split()[:2])
    store.update_episode(
        episode["id"], title=f"Épisode {episode_n}", summary=f"Résumé {episode_n}", teaser="La suite.",
        lines=lines, glossary=glossary, aids={"lines": [[{} for _ in ln["tokens"]] for ln in lines]},
        notes=[{"line": 0, "anchor": ex1, "kind": "usage", "text": "Une note."}] * 3,
        point={"observation": "Observe.", "explanation": "Explication.", "examples": [ex1, ex2],
               "variants": [{"example": ex1, "distractors": ["forme fausse"]}]},
        status="ready", generation={"synthetic": True},
    )
    return True


def _play(client_run, run: dict, learner: dict, rng: random.Random) -> dict:
    from services import lang_runs

    stats = {"cards": 0}
    for step in run["steps"]:
        events = [{"type": "step", "step": step["key"], "started": True}]
        if step["kind"] in ("episode_p2", "relecture", "rappel", "jalon") and step.get("episode_ref"):
            shown = run["episodes"][str(step["episode_ref"])]
            for li, ln in enumerate(shown["lines"]):
                for ti, tok in enumerate(ln["tokens"]):
                    if tok["w"] and rng.random() < learner["tap_rate"]:
                        events.append({"type": "reveal", "episode_id": shown["id"], "line": li, "token": ti,
                                       "pass": {"episode_p2": "p2"}.get(step["kind"], step["kind"])})
        for item in [it for g in step.get("games", []) for it in g["items"]] + step.get("items", []):
            given = item.get("expected") if rng.random() < learner["right"] else "__faux__"
            events.append({"type": "answer", "item": item["ref"], "given": given})
        if step["kind"] == "deuxieme_vague":
            for line in step["lines"]:
                events.append({"type": "rating", "episode_id": step["episode_ref"], "line": line["line"],
                               "rating": "su" if rng.random() < learner["right"] else "pas_su"})
        for card in step.get("cards", []):
            stats["cards"] += 1
            events.append({"type": "card", "card_id": card["id"],
                           "verdict": "correct" if rng.random() < learner["right"] else "incorrect"})
        events.append({"type": "step", "step": step["key"], "ended": True, "active_s": step["budget_s"],
                       "signal": learner["signal"] if step["kind"].startswith("episode") else None})
        res = lang_runs.record_events(run["run_id"], events, step["key"])
        if res.get("cap_reached"):
            break
    feeling = next((s["feeling"]["options"][0] for s in run["steps"] if s["kind"] == "au_revoir"), None)
    lang_runs.complete_run(run["run_id"], "fini", feeling)
    return stats


def simulate(language: str, days: int, learner_kind: str, seed: int = 0, db_path: Path | None = None) -> dict:
    import db
    from config.settings import LANG_DUE_CARDS_CAP, LANG_LADDER_MAX_STEP_PER_EPISODE
    from db import lang_episode_db as store
    from db.schema import initialize_schema
    from services import lang_activity, lang_episodes, lang_progress, lang_runs
    from services import session as metacog

    db.close_connection()
    previous_db = db.DB_PATH
    db.DB_PATH = str(db_path or Path(tempfile.mkdtemp(prefix="lang-sim-")) / "sim.db")
    initialize_schema()
    lang_runs.on_startup()
    learner = LEARNERS[learner_kind]
    rng = random.Random(seed)
    today = {"d": date(2026, 1, 5)}
    from llm import ollama_client

    saved = (lang_episodes.generate_episode, lang_episodes.RUN_IN_BACKGROUND, lang_activity.study_date,
             lang_activity.RUN_IN_BACKGROUND, metacog.nudge_metacog_profile,
             ollama_client.generate_lang_weekly_analysis_async)
    lang_episodes.generate_episode = _synthetic_episode
    # Aucun appel au vrai Clikoda : l'analyse hebdomadaire répond un ton fixe.
    ollama_client.generate_lang_weekly_analysis_async = lambda params, ok, err, on_metrics=None, model=None: ok(
        {"observations": ["Simulation."], "tone": "encourager", "suggestion": ""})
    lang_episodes.RUN_IN_BACKGROUND = False
    lang_activity.RUN_IN_BACKGROUND = False
    lang_activity.study_date = lambda dt=None: today["d"].isoformat()
    metacog.nudge_metacog_profile = lambda *a, **k: {}
    modes: Counter = Counter()
    step_kinds: Counter = Counter()
    games: Counter = Counter()
    formats: Counter = Counter()
    max_cards = 0
    runs = 0
    def age_cards(days_passed: int) -> None:
        # La répétition espacée lit datetime('now') : on vieillit les cartes à
        # la place de l'horloge, pour que des cartes deviennent dues.
        conn = db.get_connection()
        with conn:
            conn.execute("UPDATE flashcards SET due_at = datetime(due_at, ?) WHERE due_at IS NOT NULL",
                         (f"-{int(days_passed)} day",))

    try:
        lang_runs.onboarding(language, ["cuisine"], False)
        day = 0
        while day < days:
            if rng.random() < learner["long_gap"]:
                gap = rng.randint(8, 25)
                today["d"] += timedelta(days=gap)
                age_cards(gap)
                day += gap
                continue
            if rng.random() < learner["absent"]:
                today["d"] += timedelta(days=1)
                age_cards(1)
                day += 1
                continue
            run = lang_runs.start_run(language)
            modes[run["mode"]] += 1
            for step in run["steps"]:
                step_kinds[step["kind"]] += 1
                for g in step.get("games", []):
                    games[g["kind"]] += 1
                if step.get("cards") is not None:
                    max_cards = max(max_cards, len(step["cards"]))
            stats = _play(None, run, learner, rng)
            runs += 1
            max_cards = max(max_cards, stats["cards"])
            today["d"] += timedelta(days=1)
            age_cards(1)
            day += 1
        profile = lang_runs._profile(lang_runs.ensure_feuilleton(language)["id"])
        episodes = sorted(store.list_episodes(profile["id"], limit=10000), key=lambda e: e["episode_n"])
        for e in episodes:
            formats[e["format"]] += 1
        steps = [e["ladder_step"] for e in episodes]
        jumps = max((abs(b - a) for a, b in zip(steps, steps[1:])), default=0)
        streak = worst = 0
        for e in episodes:
            streak = streak + 1 if e["kind"] == "respiration" else 0
            worst = max(worst, streak)
        out_of_band = [e["episode_n"] for e in episodes if e["program_point_id"] and abs(
            e["ladder_step"] - lang_progress.target_step(language, store.get_point(
                language, e["program_point_id"])["order"])) > lang_progress.LANG_LADDER_BAND + 1]
        counts = store.lexicon_counts(profile["id"])
        return {
            "language": language, "learner": learner_kind, "days": days, "runs": runs,
            "modes": dict(modes), "steps": dict(step_kinds), "episodes_played": profile["episode_n"],
            "program_order": profile["program_order"], "program_size": store.program_size(language),
            "respirations": sum(1 for e in episodes if e["kind"] == "respiration"),
            "max_consecutive_respirations": worst, "max_ladder_jump": jumps,
            "ladder_jump_ok": jumps <= LANG_LADDER_MAX_STEP_PER_EPISODE,
            "out_of_band_episodes": out_of_band, "games": dict(games), "formats": dict(formats),
            "max_cards_per_run": max_cards, "cards_cap_ok": max_cards <= LANG_DUE_CARDS_CAP,
            "words_seen": counts["seen"], "words_acquired": counts["acquired"],
            "level": lang_progress.current_cefr(language, profile["program_order"]),
        }
    finally:
        (lang_episodes.generate_episode, lang_episodes.RUN_IN_BACKGROUND, lang_activity.study_date,
         lang_activity.RUN_IN_BACKGROUND, metacog.nudge_metacog_profile,
         ollama_client.generate_lang_weekly_analysis_async) = saved
        db.close_connection()
        db.DB_PATH = previous_db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--language", default="espagnol")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    for kind in LEARNERS:
        print(json.dumps(simulate(args.language, args.days, kind, args.seed), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
