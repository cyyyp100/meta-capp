# services/lang_activity.py — Activité quotidienne, absence, analyse hebdomadaire (§ 14).
#
# Décompte PAR LANGUE, backend uniquement, jamais affiché comme une série (T4) :
# il est indépendant du jour d'étude commun que `nudge_metacog_profile`
# enregistre, et sert à deux choses — choisir le mode de la séance après une
# absence (T5-T7) et nourrir l'analyse hebdomadaire (T8-T11), qui ne décide de
# rien : Clikoda y formule seulement des observations, dont le ton colore les
# messages de rappel et de reprise.
from __future__ import annotations

import logging
import statistics
import threading
from datetime import date, datetime, timedelta

from config.settings import (
    LANG_ABSENCE_TIERS,
    LANG_STUDY_DAY_CUTOFF_HOUR,
    LANG_STUDY_DAY_MIN_S,
    LANG_WEEKLY_WINDOWS_DAYS,
)
from db import lang_episode_db as store

logger = logging.getLogger("services.lang_activity")

RUN_IN_BACKGROUND = True


def study_date(dt: datetime | None = None) -> str:
    """T1 : date locale de la machine, décalée de LANG_STUDY_DAY_CUTOFF_HOUR —
    une séance à 1 h du matin compte pour la veille."""
    dt = dt or datetime.now()
    return (dt - timedelta(hours=LANG_STUDY_DAY_CUTOFF_HOUR)).date().isoformat()


def _as_date(value: str) -> date:
    return date.fromisoformat(value)


def is_counted(row: dict) -> bool:
    """T3 : séance terminée, relecture terminée, ou assez de temps effectif."""
    return bool(
        int(row.get("runs_completed") or 0) > 0
        or int(row.get("rereads") or 0) > 0
        or int(row.get("effective_seconds") or 0) >= LANG_STUDY_DAY_MIN_S
    )


def record(profile_id: int, day: str, *, first_start_local: str | None = None, **increments) -> dict:
    """T2 : mise à jour incrémentale de la journée, puis de `counted`."""
    row = store.bump_daily_activity(profile_id, day, first_start_local=first_start_local, **increments)
    counted = is_counted(row)
    if bool(row.get("counted")) != counted:
        store.set_daily_counted(profile_id, day, counted)
        row["counted"] = int(counted)
    return row


def absence_days(profile_id: int, today: str | None = None) -> int | None:
    """T5 : jours écoulés depuis le dernier jour d'étude de cette langue ; None
    si l'apprenant n'a jamais étudié. Aujourd'hui en fait partie dès qu'il
    compte (T3) : la relecture imposée par une absence faite, la séance
    suivante du même jour joue l'épisode gardé au lieu de la réimposer."""
    today = today or study_date()
    tomorrow = (_as_date(today) + timedelta(days=1)).isoformat()
    last = store.last_counted_study_date(profile_id, before=tomorrow)
    if not last:
        return None
    return (_as_date(today) - _as_date(last)).days


def absence_tier(days: int | None) -> str:
    """Palier d'absence (C7) : normal | rappel_long | reprise | reprise_controle."""
    if days is None:
        return "normal"
    for bound, tier in LANG_ABSENCE_TIERS:
        if bound is None or days <= bound:
            return tier
    return "normal"


def relecture_due(days: int | None) -> bool:
    """C7 : passé le palier `normal`, la séance est une relecture imposée, sans
    nouvel épisode ; l'épisode prêt attend la séance suivante."""
    return absence_tier(days) != "normal"


# ── Analyse hebdomadaire (T8-T11) ─────────────────────────────────────────────

def week_start(day: str) -> str:
    d = _as_date(day)
    return (d - timedelta(days=d.weekday())).isoformat()


def _streaks(days: list[str]) -> tuple[int, list[int]]:
    """(plus longue suite de jours consécutifs, longueurs des trous)."""
    if not days:
        return 0, []
    ds = sorted(_as_date(d) for d in days)
    longest = current = 1
    gaps = []
    for a, b in zip(ds, ds[1:]):
        delta = (b - a).days
        if delta == 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
            gaps.append(delta - 1)
    return longest, gaps


def weekly_aggregates(profile_id: int, today: str) -> dict:
    """T8 : agrégats CALCULÉS de la semaine écoulée et des quatre dernières."""
    short, long_ = LANG_WEEKLY_WINDOWS_DAYS
    end = _as_date(today) - timedelta(days=1)
    since_long = (end - timedelta(days=long_ - 1)).isoformat()
    since_short = (end - timedelta(days=short - 1)).isoformat()
    rows = [r for r in store.list_daily_activity(profile_id, since=since_long) if r["study_date"] <= end.isoformat()]
    counted = [r for r in rows if r["counted"]]
    days_short = [r["study_date"] for r in counted if r["study_date"] >= since_short]
    longest, gaps = _streaks([r["study_date"] for r in counted])
    hours = []
    for r in counted:
        try:
            hours.append(int((r["first_start_local"] or "")[11:13]))
        except ValueError:
            continue
    runs = store.runs_between(profile_id, since_long, end.isoformat())
    completed = [r for r in runs if r["status"] == "completed"]
    modes: dict[str, int] = {}
    for r in completed:
        if r["study_date"] >= since_short:
            modes[r["mode"]] = modes.get(r["mode"], 0) + 1
    weekly: dict[str, dict] = {}
    for r in completed:
        signals = (r.get("plan") or {}).get("signals") or {}
        week = weekly.setdefault(week_start(r["study_date"]), {"reveal": [], "understood": [], "games": [], "days": set()})
        week["days"].add(r["study_date"])
        if signals.get("reveal_rate") is not None:
            week["reveal"].append(signals["reveal_rate"])
        if signals.get("understood"):
            week["understood"].append(1.0 if signals["understood"] == "compris" else 0.0)
        if signals.get("games_rate") is not None:
            week["games"].append(signals["games_rate"])

    def _mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    evolution = [
        {"week": w, "study_days": len(v["days"]), "reveal_rate": _mean(v["reveal"]),
         "understood": _mean(v["understood"]), "games": _mean(v["games"])}
        for w, v in sorted(weekly.items())
    ]
    regular = [e["reveal_rate"] for e in evolution if e["study_days"] >= 5 and e["reveal_rate"] is not None]
    irregular = [e["reveal_rate"] for e in evolution if e["study_days"] <= 2 and e["reveal_rate"] is not None]
    durations = [r["effective_seconds"] for r in counted]
    return {
        "study_days_7": len(days_short),
        "study_days_28": len(counted),
        "gaps": gaps,
        "longest_streak": longest,
        "usual_hour": int(statistics.median(hours)) if hours else None,
        "mean_minutes": round(statistics.mean(durations) / 60, 1) if durations else None,
        "modes_7": modes,
        "evolution": evolution,
        "reveal_rate_regular_weeks": _mean(regular),
        "reveal_rate_irregular_weeks": _mean(irregular),
    }


def maybe_trigger_weekly(profile: dict, language: str, today: str | None = None) -> bool:
    """T9 : à la première séance d'une nouvelle semaine ISO, en arrière-plan,
    priorité basse ; résultat mis en cache dans lang_weekly_analysis."""
    today = today or study_date()
    week = week_start(today)
    if store.get_weekly(profile["id"], week):
        return False
    if not store.last_counted_study_date(profile["id"], before=week):
        return False  # aucune semaine écoulée à analyser
    aggregates = weekly_aggregates(profile["id"], week)
    store.save_weekly(profile["id"], week, aggregates=aggregates, analysis=None, status="pending")

    def _job() -> None:
        from config.settings import OLLAMA_BACKGROUND_QUEUE_WAIT_S
        from llm.ollama_client import generate_lang_weekly_analysis_async
        from services.lang_episodes import explain_lang_of, prompt_params
        from services.llm_bridge import run_llm_sync

        lang = explain_lang_of(profile)
        try:
            analysis = run_llm_sync(lambda ok, err: generate_lang_weekly_analysis_async(
                {"language_label": prompt_params(language, lang)["language_label"], "aggregates": aggregates,
                 "explain_lang": lang}, ok, err,
            ), queue_wait_s=OLLAMA_BACKGROUND_QUEUE_WAIT_S)
            store.save_weekly(profile["id"], week, aggregates=aggregates, analysis=analysis, status="ready")
        except Exception as exc:
            logger.info("Analyse hebdomadaire indisponible (%s) : %s", language, exc)
            store.save_weekly(profile["id"], week, aggregates=aggregates, analysis=None, status="failed")

    if RUN_IN_BACKGROUND:
        threading.Thread(target=_job, daemon=True, name=f"lang-weekly-{profile['id']}").start()
    else:
        _job()
    return True


def message_tone(profile_id: int) -> str:
    """T10-T11 : ton des messages de rappel et de reprise (usage interne)."""
    latest = store.latest_weekly(profile_id)
    analysis = (latest or {}).get("analysis") or {}
    return analysis.get("tone") or "encourager"
