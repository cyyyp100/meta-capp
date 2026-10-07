"""Banc d'évaluation hors séance du feuilleton (plan V14-V18).

Génère des épisodes sur des points variés du programme d'une langue, avec le
VRAI modèle (Ollama local), sur une base jetable, et mesure :
  * le taux de réussite des validateurs et le nombre de tentatives par appel ;
  * la durée réelle de chaque appel et de chaque épisode (G19), les tokens ;
  * les raisons de refus les plus fréquentes (pour ajuster les prompts) ;
  * pour le mandarin, la part de jetons « suspects » ; pour l'arabe, la part de
    mots dont le radical diffère d'une forme validée.

Écrit deux fichiers dans --out : `bench_<langue>.json` (mesures) et
`bench_<langue>.md` (épisodes lisibles, matière de la relecture humaine V15-V17).
`--explain en` banc la langue d'explication anglaise (prompts, traductions et
notes en anglais) ; les fichiers prennent alors le suffixe `_en`.

    python tools/lang_bench.py --language espagnol --episodes 20 --out bench/

`--sequential` banc au contraire des points CONSÉCUTIFS, comme un vrai
apprenant : chaque épisode est décidé depuis le précédent puis joué, si bien
que le lexique grandit et que le contrôle des mots nouveaux finit par jouer (un
banc dispersé part toujours d'un lexique vide). `--start-order N` commence au
point N ; `--placed` y fait arriver l'apprenant par le test de niveau (le
contrôle ne s'applique alors plus à lui). Un épisode refusé est retenté une
fois, comme à la séance suivante ; s'il échoue encore, le banc s'arrête là.

    python tools/lang_bench.py --language espagnol --sequential --episodes 12
    python tools/lang_bench.py --language espagnol --sequential --start-order 23 --placed

La porte V18 (épisode complet plus court qu'une séance) est calculée sur la
durée médiane d'un épisode prêt, comparée à LANG_RUN_TARGET_S.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nwol"))


def _setup_db(path: Path) -> None:
    import db

    db.close_connection()
    db.DB_PATH = str(path)
    from db.schema import initialize_schema
    from services.lang_runs import on_startup

    initialize_schema()
    on_startup()


def _points(language: str, count: int) -> list[dict]:
    from services import lang_progress as progress

    program = progress.program(language)
    if not program:
        raise SystemExit(f"aucun programme pour {language}")
    step = max(1, len(program) // count)
    return [program[min(len(program) - 1, i * step)] for i in range(count)]


def run(language: str, count: int, out: Path, interests: list[str], explain: str = "fr") -> dict:
    from db import lang_episode_db as store
    from services import lang_episodes as episodes
    from services import lang_progress as progress
    from services import lang_runs

    episodes.RUN_IN_BACKGROUND = False
    episodes.KEEP_RAW = True
    profile = lang_runs.ensure_feuilleton(language)
    store.update_profile_fields(profile["id"], interests=interests, onboarding_done=1, explain_lang=explain)
    stem = f"bench_{language}" + ("_en" if explain == "en" else "")
    results = []
    for n, point in enumerate(_points(language, count), start=1):
        store.update_profile_fields(
            profile["id"], program_order=point["order"] - 1,
            ladder_step=progress.target_step(language, point["order"]),
        )
        # Les points du banc sont dispersés dans le programme : l'arc est réécrit
        # pour chacun, sinon l'épisode C1 hériterait d'un arc écrit pour l'A1.
        from db import get_connection

        with get_connection() as conn:
            conn.execute("DELETE FROM lang_story_arcs WHERE profile_id=?", (profile["id"],))
        profile = lang_runs._profile(profile["id"])
        started = time.monotonic()
        decision = progress.next_episode_decision(profile, language, current=None, signals=None, episode_n=n)
        store.create_episode(profile["id"], n, kind="normal", program_point_id=point["id"],
                             format=decision["format"], ladder_step=decision["ladder_step"],
                             params=decision["params"])
        ok = episodes.generate_episode(profile["id"], n)
        episode = store.get_episode_by_n(profile["id"], n)
        if ok:
            store.update_episode(episode["id"], status="played")
        elapsed = time.monotonic() - started
        results.append({"n": n, "point": point["id"], "cefr": point["cefr"], "ok": ok,
                        "seconds": round(elapsed, 1), "episode": episode})
        print(f"[{n}/{count}] {point['id']:<40} {'OK ' if ok else 'ÉCHEC'} {elapsed:6.1f} s", flush=True)
    return _report(language, results, out, stem)


def run_sequential(language: str, count: int, out: Path, interests: list[str], explain: str = "fr",
                   start_order: int = 1, placed: bool = False, retries: int = 1) -> dict:
    """Points consécutifs à partir de `start_order`, chaque épisode joué
    (`lang_runs._mark_played`) : le lexique grandit comme chez un apprenant."""
    from db import lang_episode_db as store
    from services import lang_episodes as episodes
    from services import lang_progress as progress
    from services import lang_runs

    episodes.RUN_IN_BACKGROUND = False
    episodes.KEEP_RAW = True
    profile = lang_runs.ensure_feuilleton(language)
    start = max(1, int(start_order))
    store.update_profile_fields(profile["id"], interests=interests, onboarding_done=1, explain_lang=explain,
                                program_order=start - 1, ladder_step=progress.target_step(language, start),
                                placement_done=int(placed))
    # Le point de départ du parcours, tel que l'écrit l'onboarding (1) ou le
    # test de niveau (`--placed`) : c'est lui qui décide du contrôle des mots nouveaux.
    progress.record_level({**profile, "program_order": start}, language, start if placed else 1, "placement")
    stem = f"bench_{language}_seq{start}" + ("_placed" if placed else "") + ("_en" if explain == "en" else "")
    results = []
    for n in range(1, count + 1):
        profile = lang_runs._profile(profile["id"])
        current = store.get_episode_by_n(profile["id"], n - 1) if n > 1 else None
        started = time.monotonic()
        for _attempt in range(1 + max(0, retries)):
            episodes.schedule_episode(profile, language, n, current=current, signals=None)
            episode = store.get_episode_by_n(profile["id"], n)
            if episode["status"] == "ready":
                break
        ok = episode["status"] == "ready"
        if ok:
            lang_runs._mark_played(profile, language, episode)
            episode = store.get_episode_by_n(profile["id"], n)
        elapsed = time.monotonic() - started
        point = store.get_point(language, episode["program_point_id"] or "") or {}
        results.append({"n": n, "point": episode["program_point_id"], "cefr": point.get("cefr"), "ok": ok,
                        "seconds": round(elapsed, 1), "episode": episode,
                        "lexicon": len(store.get_lexicon(profile["id"]))})
        print(f"[{n}/{count}] {episode['program_point_id'] or '-':<40} {'OK ' if ok else 'ÉCHEC'} {elapsed:6.1f} s"
              f"  lexique {results[-1]['lexicon']}", flush=True)
        if not ok:
            break  # l'apprenant resterait sur cet épisode : la suite n'a pas de sens
    return _report(language, results, out, stem)


def _lesson_stats(language: str, results: list[dict]) -> dict:
    from db import lang_episode_db as store

    rows = []
    for r in results:
        if not r["ok"] or not r["episode"].get("program_point_id"):
            continue
        explain = (r["episode"].get("generation") or {}).get("explain_lang") or "fr"
        row = store.get_point_lesson(language, r["episode"]["program_point_id"], explain)
        if row:
            rows.append({"point": row["point_id"], "status": row["status"], "attempts": row["attempts"],
                         "seconds": (row.get("generation") or {}).get("duration_s"),
                         "errors": [e for c in (row.get("generation") or {}).get("calls") or []
                                    for e in c.get("errors") or []][:6]})
    seconds = [x["seconds"] for x in rows if x["seconds"] is not None]
    return {"written": len(rows), "ready": sum(x["status"] == "ready" for x in rows),
            "median_s": statistics.median(seconds) if seconds else None, "max_s": max(seconds) if seconds else None,
            "rows": rows}


def _reliability_line(gen: dict) -> str:
    """Mots nouveaux estimés contre le plafond, acceptation douce, lemmes
    réparés, échecs subis : une ligne par épisode du rapport lisible."""
    estimate = gen.get("new_words_estimate") or {}
    if not estimate:
        return ""
    parts = [f"Mots nouveaux estimés : {estimate.get('estimate')} (plafond {estimate.get('cap')}, "
             f"contrôlé : {'oui' if estimate.get('checked') else 'non'})"]
    if gen.get("soft_accepted"):
        parts.append("accepté malgré un problème doux : " + ", ".join(gen["soft_accepted"]))
    if gen.get("lemma_repairs"):
        parts.append("lemmes réparés : " + ", ".join(f"{r['form']} ({r['was']})" for r in gen["lemma_repairs"]))
    if gen.get("failures"):
        parts.append(f"échecs avant : {gen['failures']}")
    return " ; ".join(parts)


def _report(language: str, results: list[dict], out: Path, stem: str) -> dict:
    from config.settings import LANG_RUN_TARGET_S

    calls = [c for r in results for c in (r["episode"].get("generation") or {}).get("calls") or []]
    metrics = [m for r in results for m in (r["episode"].get("generation") or {}).get("metrics") or []]
    by_task: dict[str, dict] = {}
    for task in ("text", "glossary", "notes_point", "bible", "arc"):
        tc = [c for c in calls if c["task"] == task]
        if not tc:
            continue
        by_task[task] = {
            "attempts": len(tc), "accepted": sum(1 for c in tc if c.get("ok") or c.get("soft_accepted")),
            "soft_accepted": sum(1 for c in tc if c.get("soft_accepted")),
        }
    reasons = Counter(e.split(" : ")[0][:70] for c in calls for e in c.get("errors") or [])
    durations = [r["seconds"] for r in results if r["ok"]]
    per_call: dict[str, list[float]] = {}
    for m in metrics:
        per_call.setdefault(m["task"], []).append(m["wall_s"])
    suspects = sum((r["episode"].get("aids") or {}).get("suspects") or 0 for r in results)
    tokens = sum(len([t for ln in r["episode"].get("lines") or [] for t in ln.get("tokens") or [] if t.get("w")])
                 for r in results)
    report = {
        "language": language, "episodes": len(results), "ready": sum(r["ok"] for r in results),
        "validator_calls": by_task, "top_rejections": reasons.most_common(12),
        "episode_seconds": {"median": statistics.median(durations) if durations else None,
                            "max": max(durations) if durations else None},
        "call_seconds": {k: {"median": round(statistics.median(v), 1), "max": round(max(v), 1), "n": len(v)}
                         for k, v in per_call.items()},
        "prompt_tokens_max": {k: max((m.get("prompt_tokens") or 0) for m in metrics if m["task"] == k)
                              for k in per_call},
        "suspect_rate": round(suspects / tokens, 4) if tokens else None,
        "gate_v18_under_run_target": bool(durations) and statistics.median(durations) < LANG_RUN_TARGET_S,
        # Génération fiable : ce qui a été accepté malgré un problème doux, les mots
        # nouveaux estimés contre leur plafond, les lemmes réparés, les échecs.
        "new_words": [{"n": r["n"], **((r["episode"].get("generation") or {}).get("new_words_estimate") or {}),
                       "soft_accepted": (r["episode"].get("generation") or {}).get("soft_accepted") or [],
                       "lexicon": r.get("lexicon")} for r in results],
        "lemma_repairs": [rep for r in results for rep in (r["episode"].get("generation") or {}).get("lemma_repairs") or []],
        "failures": sum(int((r["episode"].get("generation") or {}).get("failures") or 0) for r in results),
        # Leçon du point, écrite après chaque épisode prêt : acceptée ou non, et
        # le temps qu'elle ajoute au thread de génération.
        "lessons": _lesson_stats(language, results),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Banc {language} — {report['ready']}/{report['episodes']} épisodes prêts\n"]
    for r in results:
        ep = r["episode"]
        lines.append(f"## {r['n']}. {ep.get('title') or '(échec)'} — {r['point']} ({r['cefr']}, {ep.get('format')})\n")
        if not r["ok"]:
            gen = ep.get("generation") or {}
            lines.append(f"Échec : {gen.get('error')}\n")
            for c in gen.get("calls") or []:
                if c.get("errors"):
                    lines.append(f"- {c['task']} : {'; '.join(c['errors'])}")
            lines.append("")
            continue
        reliability = _reliability_line(ep.get("generation") or {})
        if reliability:
            lines.append(reliability + "\n")
        for ln in ep.get("lines") or []:
            lines.append(f"- **{ln['speaker']}** : {ln['text']}  \n  _{ln['translation']}_")
        lines.append("\n**Glossaire** : " + ", ".join(f"{g['form']} = {g['translation']}" for g in ep.get("glossary") or []))
        lines.append("\n**Notes** :")
        for note in ep.get("notes") or []:
            lines.append(f"- (réplique {note['line'] + 1}, « {note['anchor']} ») {note['text']}")
        point = ep.get("point") or {}
        lines.append(f"\n**Point du jour** : {point.get('observation')} — {point.get('explanation')}")
        lines.append(f"Exemples : {', '.join(point.get('examples') or [])}\n")
    (out / f"{stem}.md").write_text("\n".join(lines), encoding="utf-8")
    # Sorties brutes (acceptées ET refusées), avec leur contexte : matière des
    # fixtures de tests/fixtures/lang/ (V2).
    raw = [{"n": r["n"], "point": r["point"], "params": r["episode"].get("params"), "format": r["episode"].get("format"),
            "calls": [c for c in (r["episode"].get("generation") or {}).get("calls") or [] if "raw" in c]}
           for r in results]
    (out / f"{stem}_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--language", required=True)
    parser.add_argument("--episodes", type=int, default=20)
    parser.add_argument("--out", type=Path, default=ROOT / "bench")
    parser.add_argument("--interests", default="cuisine,voyages,cinéma")
    parser.add_argument("--db", type=Path, default=None, help="base jetable (défaut : fichier temporaire)")
    parser.add_argument("--explain", choices=("fr", "en"), default="fr",
                        help="langue d'explication du profil (ce qu'écrit Clikoda pour l'apprenant)")
    parser.add_argument("--sequential", action="store_true",
                        help="points consécutifs, chaque épisode joué (le lexique grandit)")
    parser.add_argument("--start-order", type=int, default=1, help="--sequential : premier point du programme")
    parser.add_argument("--placed", action="store_true",
                        help="--sequential : l'apprenant arrive au point de départ par le test de niveau")
    args = parser.parse_args()
    db_path = args.db or Path(tempfile.mkdtemp(prefix="lang-bench-")) / "bench.db"
    _setup_db(db_path)
    interests = [s.strip() for s in args.interests.split(",") if s.strip()]
    if args.sequential:
        report = run_sequential(args.language, args.episodes, args.out, interests, args.explain,
                                args.start_order, args.placed)
    else:
        report = run(args.language, args.episodes, args.out, interests, args.explain)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
