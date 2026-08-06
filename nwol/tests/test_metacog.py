# Tests du cœur métacognitif (trou 🔴 de l'audit : aucun test direct).
import pytest

from db.metacog import CRITERIA


# ── Jauges (pur, sans DB) ────────────────────────────────────────────────────

def test_initialize_session_gauges_inherits_profile():
    from metacog.gauges import SESSION_INHERITANCE_FACTOR, initialize_session_gauges

    values = initialize_session_gauges({"attention": 80.0})
    assert values["attention"] == pytest.approx(80.0 * SESSION_INHERITANCE_FACTOR)
    # Critère absent du profil -> base 50 héritée.
    assert values["curiosity"] == pytest.approx(50.0 * SESSION_INHERITANCE_FACTOR)
    assert set(values) == set(CRITERIA)


def test_gauges_always_clamped_0_100():
    from metacog.gauges import GaugeState

    g = GaugeState("retention", 99.0)
    for _ in range(10):
        g.update(signal=2.0, verdict="correct")
    assert g.value == 100.0
    for _ in range(50):
        g.update(signal=-2.0, verdict="incorrect")
    assert g.value == 0.0


def test_update_from_evaluation_moves_targeted_gauge_more():
    from metacog.gauges import make_gauges, update_gauges_from_evaluation

    # Question de curiosité : la jauge curiosity doit bouger plus que retention.
    gauges = make_gauges({c: 50.0 for c in CRITERIA})
    before = {k: g.value for k, g in gauges.items()}
    update_gauges_from_evaluation(
        gauges,
        {
            "verdict": "correct",
            "question_type": "curiosity",
            "metacog_signals": {c: 1.0 for c in CRITERIA},
        },
    )
    curiosity_delta = gauges["curiosity"].value - before["curiosity"]
    retention_delta = gauges["retention"].value - before["retention"]
    assert curiosity_delta > retention_delta > 0


def test_update_from_evaluation_tolerates_garbage_signals():
    from metacog.gauges import make_gauges, update_gauges_from_evaluation

    gauges = make_gauges()
    # Signaux non numériques, types inattendus -> pas d'exception, valeurs clampées.
    values = update_gauges_from_evaluation(
        gauges,
        {
            "verdict": "partial",
            "metacog_signals": {"attention": "beaucoup", "curiosity": None},
            "curiosity_signals": "pas-un-dict",
            "creativity_signals": {"depth_of_reflection": "??"},
        },
    )
    assert all(0.0 <= v <= 100.0 for v in values.values())


def test_attention_penalizes_slow_and_wrong_answers():
    from metacog.gauges import GaugeState

    slow = GaugeState("attention", 50.0)
    slow.update(signal=0.0, verdict="incorrect", response_time_ms=30000, consecutive_incorrect=3)
    fast = GaugeState("attention", 50.0)
    fast.update(signal=0.0, verdict="correct", response_time_ms=2000)
    assert slow.value < 50.0 < fast.value


def test_profile_update_blends_session_and_profile():
    from metacog.gauges import update_profile_gauges_from_session

    updates = update_profile_gauges_from_session(
        {c: 40.0 for c in CRITERIA}, {c: 90.0 for c in CRITERIA}, session_weight=0.1
    )
    for criterion in CRITERIA:
        assert updates[criterion] == pytest.approx(45.0)  # 40*0.9 + 90*0.1


# ── Profil permanent (avec DB isolée) ────────────────────────────────────────

@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    import db

    db.close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nwol.db"))
    from db.schema import initialize_schema

    initialize_schema()
    yield
    db.close_connection()


def test_compute_alpha_decreases_with_experience():
    from metacog.profile import ALPHA_MIN, compute_alpha

    assert compute_alpha(0) == 1.0
    assert compute_alpha(5) == pytest.approx(0.5)
    assert compute_alpha(10_000) == ALPHA_MIN


def test_update_profile_persists_and_increments_sessions(fresh_db):
    from db.user import DEFAULT_USER_ID
    from metacog.profile import update_profile

    profile = update_profile(DEFAULT_USER_ID, {c: 100.0 for c in CRITERIA}, session_id=None)
    assert profile["sessions_count"] == 1
    # Première session (alpha=1.0) : le profil adopte le score de session.
    assert float(profile["attention"]) == pytest.approx(100.0)

    profile = update_profile(DEFAULT_USER_ID, {c: 0.0 for c in CRITERIA}, session_id=None)
    assert profile["sessions_count"] == 2
    # Les sessions suivantes pèsent moins : la chute est amortie.
    assert 0.0 < float(profile["attention"]) < 100.0


def test_update_retention_from_quiz(fresh_db):
    from db.user import DEFAULT_USER_ID
    from metacog.profile import update_retention_from_quiz

    before = update_retention_from_quiz(DEFAULT_USER_ID, verdict=None)  # cible neutre 50
    after = update_retention_from_quiz(DEFAULT_USER_ID, verdict="correct")
    assert float(after["retention"]) > float(before["retention"])
    worst = update_retention_from_quiz(DEFAULT_USER_ID, verdict="incorrect")
    assert float(worst["retention"]) < float(after["retention"])
