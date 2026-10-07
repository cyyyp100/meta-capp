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


# ── Les matières de l'apprenant (services/subjects.py) ──────────────────────

def _subjects():
    from services.stats import get_metacog_overview

    return {s["subject"]: s for s in get_metacog_overview()["subjects"]}


def test_a_discipline_comes_with_its_document_and_leaves_with_it(fresh_db):
    """Le LLM classe le document à l'import : sa matière est à l'apprenant tant
    qu'un document la porte. Supprimé sans avoir rien mesuré, elle s'en va."""
    from db.documents import delete_document
    from subject_helpers import import_document

    doc_id = import_document("physique")
    physique = _subjects()["physique"]
    assert physique["kind"] == "discipline" and physique["flag"] == ""
    assert physique["level"] == 50.0

    delete_document(doc_id)
    assert "physique" not in _subjects()


def test_a_measured_discipline_outlives_its_document(fresh_db):
    """Des réponses données en quiz sont des mesures : elles gardent la matière."""
    from db.documents import delete_document
    from db.subjects import update_subject_from_answer
    from db.user import DEFAULT_USER_ID
    from subject_helpers import import_document

    doc_id = import_document("histoire")
    update_subject_from_answer(DEFAULT_USER_ID, "histoire", False)
    delete_document(doc_id)
    assert _subjects()["histoire"]["level"] < 50.0


def test_a_language_appears_after_its_first_session(fresh_db):
    """Une langue seulement ouverte n'est pas une matière ; une séance terminée
    l'en fait une, avec son drapeau, son niveau CECR et ses séances — sans niveau
    de maîtrise inventé tant qu'aucun quiz ne l'a mesuré."""
    from subject_helpers import complete_language_session

    complete_language_session("espagnol", status="abandoned")
    assert "espagnol" not in _subjects()

    complete_language_session("espagnol")
    complete_language_session("espagnol")
    espagnol = _subjects()["espagnol"]
    assert espagnol["kind"] == "language" and espagnol["flag"] == "🇪🇸"
    assert espagnol["sessions"] == 2 and espagnol["cefr"] == "A1"
    assert espagnol["level"] is None and espagnol["recommendation"] is None


def test_each_language_is_its_own_subject(fresh_db):
    """Une matière par langue : deux langues pratiquées, deux cartes ; la maîtrise
    mesurée en quiz va à la langue jouée, pas à un « Langues » commun."""
    from db.subjects import update_subject_from_answer
    from db.user import DEFAULT_USER_ID
    from subject_helpers import complete_language_session

    complete_language_session("anglais")
    complete_language_session("mandarin")
    update_subject_from_answer(DEFAULT_USER_ID, "anglais", True)

    subjects = _subjects()
    assert {"anglais", "mandarin"} <= set(subjects) and "langues" not in subjects
    assert subjects["anglais"]["level"] > 50.0 and subjects["anglais"]["recommendation"]
    assert subjects["mandarin"]["level"] is None


def test_reading_a_language_document_is_a_session_in_that_language(fresh_db):
    """Importer un cours de langue ne suffit pas ; le lire, si."""
    from db.sessions import end_session, start_session
    from subject_helpers import import_document

    doc_id = import_document("allemand")
    assert "allemand" not in _subjects()

    end_session(start_session(doc_id), duration_s=60)
    allemand = _subjects()["allemand"]
    assert allemand["sessions"] == 1
    assert allemand["cefr"] is None  # jamais jouée dans le module Langues


def test_disciplines_come_first_then_languages(fresh_db):
    from subject_helpers import own

    own("physique", "anglais", "biologie", "espagnol")
    assert list(_subjects()) == ["biologie", "physique", "anglais", "espagnol"]
