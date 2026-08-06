import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Une DB SQLite neuve, isolée, avec schéma complet et utilisateur par défaut."""
    import db
    from db import close_connection

    close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nwol.db"))
    from db.schema import initialize_schema

    initialize_schema()
    yield
    close_connection()


def test_overview_shape_empty(fresh_db):
    from services.stats import CRITERIA, get_metacog_overview

    ov = get_metacog_overview()
    assert set(ov) >= {
        "user", "sessions_count", "updated_at",
        "global_score", "trend", "criteria", "subjects",
    }
    assert [c["key"] for c in ov["criteria"]] == list(CRITERIA)
    # Profil neuf : tous les critères à 50, aucun historique.
    assert all(c["value"] == 50.0 for c in ov["criteria"])
    assert all(c["history"] == [] for c in ov["criteria"])
    assert ov["global_score"] == 50.0
    assert ov["trend"] == {"category": "stable", "delta": 0.0}
    assert ov["subjects"] == []


def test_overview_with_history(fresh_db):
    from db.metacog import insert_history
    from db.user import DEFAULT_USER_ID
    from services.stats import get_metacog_overview

    # Deux points pour "attention" : 50 -> 60 (delta +10 => in_progress).
    insert_history(DEFAULT_USER_ID, None, "attention", 50.0, 50.0, 70.0, 0.1)
    insert_history(DEFAULT_USER_ID, None, "attention", 50.0, 60.0, 70.0, 0.1)

    ov = get_metacog_overview()
    attention = next(c for c in ov["criteria"] if c["key"] == "attention")
    assert attention["history"] == [50.0, 60.0]
    assert attention["delta"] == 10.0
    # La tendance globale moyenne les deltas des critères ayant >=2 points.
    assert ov["trend"]["category"] == "in_progress"
    assert ov["trend"]["delta"] == 10.0


def test_subjects_present_and_recommended(fresh_db):
    from db.subjects import update_subject_from_answer
    from db.user import DEFAULT_USER_ID
    from services.stats import get_metacog_overview

    update_subject_from_answer(DEFAULT_USER_ID, "mathématiques", True)

    ov = get_metacog_overview()
    subjects = {s["subject"]: s for s in ov["subjects"]}
    assert "mathématiques" in subjects
    maths = subjects["mathématiques"]
    assert 0.0 <= maths["level"] <= 100.0
    assert maths["updates"] == len(maths["history"])
    assert maths["recommendation"] in {"solid", "progressing", "to_review", "to_improve"}


def test_parity_values_match_db(fresh_db):
    """Les valeurs du service == calcul direct depuis la DB (filet de régression)."""
    from db.metacog import CRITERIA, ensure_profile
    from db.user import get_default_user
    from services.stats import get_metacog_overview

    ov = get_metacog_overview()
    user = get_default_user()
    profile = ensure_profile(user["id"])

    expected = {c: max(0.0, min(100.0, float(profile.get(c, 50.0)))) for c in CRITERIA}
    got = {c["key"]: c["value"] for c in ov["criteria"]}
    assert got == expected
    assert abs(ov["global_score"] - sum(expected.values()) / len(expected)) < 1e-9
