"""Série d'ÉTUDE : record, tolérance d'un jour, et pas d'effet de bord (§ B5).

Trois défauts de la v1 corrigés ensemble (migration v27) : la série
s'incrémentait sur un `GET`, ne gardait aucun record, et repartait à 1 dès le
premier jour manqué.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import db
    from db.schema import initialize_schema

    db.close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "streak.db"))
    initialize_schema()
    yield
    db.close_connection()


def _set_last_study_day(days_ago: int, streak: int) -> None:
    from db import get_connection
    from db.user import DEFAULT_USER_ID, ensure_default_user

    ensure_default_user()
    day = (date.today() - timedelta(days=days_ago)).isoformat()
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM login_streak")
        conn.execute(
            "INSERT INTO login_streak (user_id, streak, longest_streak, last_study_day)"
            " VALUES (?, ?, ?, ?)",
            (DEFAULT_USER_ID, streak, streak, day),
        )


def test_reading_the_streak_never_writes(db_path):
    from db.user import get_streak

    assert get_streak()["streak"] == 0
    assert get_streak()["streak"] == 0
    assert get_streak()["active"] is False


def test_first_study_day_starts_the_series(db_path):
    from db.user import record_study_day

    assert record_study_day()["streak"] == 1
    # Deux sessions le même jour ne comptent qu'une fois.
    assert record_study_day()["streak"] == 1


def test_consecutive_day_extends_the_series(db_path):
    from db.user import record_study_day

    _set_last_study_day(days_ago=1, streak=4)
    assert record_study_day()["streak"] == 5


def test_one_missed_day_does_not_break_the_series(db_path):
    """La tolérance est une décision de produit : un streak qui punit fait
    abandonner ceux qui viennent justement de rater une journée."""
    from db.user import record_study_day

    _set_last_study_day(days_ago=2, streak=6)
    assert record_study_day()["streak"] == 7


def test_two_missed_days_restart_the_series_but_keep_the_record(db_path):
    from db.user import get_streak, record_study_day

    _set_last_study_day(days_ago=4, streak=11)
    # Avant même d'étudier, la série affichée est finie — sans rien écrire.
    assert get_streak()["streak"] == 0
    assert get_streak()["longest_streak"] == 11

    after = record_study_day()
    assert after["streak"] == 1
    # Casser sa série n'efface pas la preuve de l'avoir tenue.
    assert after["longest_streak"] == 11
