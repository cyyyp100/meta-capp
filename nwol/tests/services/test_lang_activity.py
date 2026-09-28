# Jour d'étude par langue, absence et analyse hebdomadaire (plan § 14 ; V9).
from datetime import datetime

import pytest

from config.settings import LANG_STUDY_DAY_MIN_S
from services import lang_activity as activity


def test_study_day_switches_at_four_in_the_morning():
    assert activity.study_date(datetime(2026, 9, 24, 3, 59)) == "2026-09-23"
    assert activity.study_date(datetime(2026, 9, 24, 4, 0)) == "2026-09-24"


def test_counted_day():
    assert activity.is_counted({"runs_completed": 1})
    assert activity.is_counted({"rereads": 1})
    assert activity.is_counted({"effective_seconds": LANG_STUDY_DAY_MIN_S})
    assert not activity.is_counted({"effective_seconds": LANG_STUDY_DAY_MIN_S - 1})


@pytest.mark.parametrize("days,tier", [
    (None, "normal"), (1, "normal"), (2, "normal"), (3, "rappel_long"), (6, "rappel_long"),
    (7, "reprise"), (20, "reprise"), (21, "reprise_controle"), (90, "reprise_controle"),
])
def test_absence_tiers(days, tier):
    assert activity.absence_tier(days) == tier


@pytest.fixture
def profile_id(tmp_path, monkeypatch):
    import db

    db.close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "act.db"))
    from db.schema import initialize_schema
    from services.lang_runs import ensure_feuilleton, on_startup

    initialize_schema()
    on_startup()
    yield ensure_feuilleton("espagnol")["id"]
    db.close_connection()


def test_effective_time_accumulates_and_counts_the_day(profile_id):
    activity.record(profile_id, "2026-09-20", effective_seconds=120, first_start_local="2026-09-20 20:15:00")
    row = activity.record(profile_id, "2026-09-20", effective_seconds=LANG_STUDY_DAY_MIN_S)
    assert row["effective_seconds"] == 120 + LANG_STUDY_DAY_MIN_S and row["counted"]


def test_absence_days_come_from_counted_days_only(profile_id):
    activity.record(profile_id, "2026-09-01", runs_completed=1)
    activity.record(profile_id, "2026-09-10", effective_seconds=10)  # pas un jour d'étude
    assert activity.absence_days(profile_id, "2026-09-12") == 11
    assert activity.absence_days(profile_id + 99, "2026-09-12") is None


def test_weekly_aggregates(profile_id):
    for day in ("2026-09-14", "2026-09-15", "2026-09-16", "2026-09-18"):
        activity.record(profile_id, day, runs_completed=1, effective_seconds=600,
                        first_start_local=f"{day} 21:00:00")
    agg = activity.weekly_aggregates(profile_id, "2026-09-21")
    assert agg["study_days_7"] == 4 and agg["longest_streak"] == 3 and agg["gaps"] == [1]
    assert agg["usual_hour"] == 21 and agg["mean_minutes"] == 10.0


def test_weekly_analysis_runs_once_per_iso_week(profile_id, monkeypatch):
    from db import lang_episode_db as store
    from llm import ollama_client

    monkeypatch.setattr(activity, "RUN_IN_BACKGROUND", False)
    monkeypatch.setattr(ollama_client, "generate_lang_weekly_analysis_async",
                        lambda params, ok, err, on_metrics=None, model=None: ok(
                            {"observations": ["Belle régularité."], "tone": "feliciter", "suggestion": ""}))
    activity.record(profile_id, "2026-09-16", runs_completed=1)
    profile = {"id": profile_id}
    assert activity.maybe_trigger_weekly(profile, "espagnol", "2026-09-22") is True
    assert activity.maybe_trigger_weekly(profile, "espagnol", "2026-09-23") is False
    assert store.get_weekly(profile_id, "2026-09-21")["status"] == "ready"
    assert activity.message_tone(profile_id) == "feliciter"
