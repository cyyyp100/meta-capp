# Révision éclair du sas d'entrée — ce que dit le RYTHME des cartes (services/warmup.py).
#
# Trop vite : on clique sans se tester (attention, métacognition). Trop lent,
# surtout sur la réponse : trace fragile (rétention). Beaucoup trop long : on
# n'est plus là (attention seulement).
import pytest

from config.settings import (
    WARMUP_DRIFT_ATTENTION,
    WARMUP_MAX_CARDS,
    WARMUP_RUSH_ATTENTION,
    WARMUP_RUSH_META,
    WARMUP_SLOW_BACK_RETENTION,
    WARMUP_SLOW_FRONT_RETENTION,
)
from services.warmup import face_pace, gauge_deltas

# 30 mots : survol 3 s, lecture 7,5 s.
LONG_QUESTION = " ".join(["mot"] * 30)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    import db
    from db import close_connection

    close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nwol.db"))
    from db.schema import initialize_schema

    initialize_schema()
    yield
    close_connection()


def _session() -> int:
    from db.documents import upsert_document
    from db.sessions import start_session

    return start_session(upsert_document("/tmp/warmup.pdf", "warmup.pdf", 3, "pdfium", False))


def test_the_pace_of_a_face_follows_the_length_of_its_text():
    assert face_pace(LONG_QUESTION, 500, "front") == "rushed"
    assert face_pace(LONG_QUESTION, 2_500, "front") == "rushed"  # sous le survol de 30 mots
    assert face_pace(LONG_QUESTION, 6_000, "front") == "steady"
    assert face_pace(LONG_QUESTION, 30_000, "front") == "slow"
    assert face_pace(LONG_QUESTION, 90_000, "front") == "drifted"
    # Une réponse d'un mot se lit d'un coup d'œil, mais pas en un clic réflexe.
    assert face_pace("4", 400, "back") == "rushed"
    assert face_pace("4", 1_500, "back") == "steady"


def test_the_question_leaves_more_time_than_the_answer():
    # Chercher la réponse prend plus longtemps que la confronter à la sienne.
    assert face_pace("Capitale du Pérou ?", 12_000, "front") == "steady"
    assert face_pace("Capitale du Pérou ?", 12_000, "back") == "slow"


def test_each_pace_costs_its_own_gauges():
    rushed = gauge_deltas([{"front_pace": "rushed", "back_pace": "rushed"}])
    assert rushed == {
        "attention": -2 * WARMUP_RUSH_ATTENTION,
        "meta_cognition": -2 * WARMUP_RUSH_META,
    }
    slow = gauge_deltas([{"front_pace": "slow", "back_pace": "slow"}])
    assert slow == {"retention": -(WARMUP_SLOW_FRONT_RETENTION + WARMUP_SLOW_BACK_RETENTION)}
    assert WARMUP_SLOW_BACK_RETENTION > WARMUP_SLOW_FRONT_RETENTION  # surtout sur la réponse
    # Un décrochage ne dit plus rien de la mémoire : il ne coûte que l'attention.
    assert gauge_deltas([{"front_pace": "drifted", "back_pace": "steady"}]) == {"attention": -WARMUP_DRIFT_ATTENTION}
    assert gauge_deltas([{"front_pace": "steady", "back_pace": "steady"}]) == {}


def test_record_judges_on_stored_text_and_counts_once(fresh_db):
    from services.flashcards import create_flashcard
    from services.warmup import record, session_deltas, summary

    sid = _session()
    card = create_flashcard(front=LONG_QUESTION, back="4")
    timings = [
        {"card_id": card, "front_ms": 400, "back_ms": 300},  # cliquée sans lire
        {"card_id": 999_999, "front_ms": 5_000, "back_ms": 2_000},  # carte disparue
    ]

    deltas = record(sid, timings)
    assert deltas == {"attention": -2 * WARMUP_RUSH_ATTENTION, "meta_cognition": -2 * WARMUP_RUSH_META}
    # Renvoyé à la reconnexion : rien n'est versé deux fois.
    assert record(sid, timings) is None
    assert session_deltas(sid) == deltas

    recap = summary(sid)
    assert recap["cards"] == 2
    assert recap["total_s"] == 7.7
    assert recap["faces_rushed"] == 2
    assert recap["per_card"][0] == {"question_s": 0.4, "question_pace": "rushed", "answer_s": 0.3, "answer_pace": "rushed"}
    assert recap["per_card"][1]["question_pace"] == "steady"


def test_record_keeps_at_most_the_warmup_cards(fresh_db):
    from db.session_warmup import get_session_warmup
    from services.warmup import record

    sid = _session()
    record(sid, [{"card_id": 0, "front_ms": 5_000, "back_ms": 2_000}] * (WARMUP_MAX_CARDS + 3))
    rows = get_session_warmup(sid)
    assert len(rows) == WARMUP_MAX_CARDS
    assert all(row["card_id"] is None for row in rows)


def test_a_session_without_warmup_has_nothing_to_tell(fresh_db):
    from services.warmup import record, session_deltas, summary

    sid = _session()
    assert record(sid, []) is None
    assert summary(sid) is None
    assert session_deltas(sid) == {}
