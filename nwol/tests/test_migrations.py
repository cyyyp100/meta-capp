# Tests des migrations SQLite (trou 🔴 de l'audit : aucun test jusqu'ici).
import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """DB vide isolée (même mécanique que le fixture `client` serveur)."""
    import db

    db.close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nwol.db"))
    yield
    db.close_connection()


def _schema_version(conn) -> int:
    row = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
    return int(row["version"]) if row else 0


def test_initialize_schema_reaches_target_version(fresh_db):
    from config.settings import DB_SCHEMA_VERSION
    from db import get_connection
    from db.schema import initialize_schema

    initialize_schema()
    assert _schema_version(get_connection()) == DB_SCHEMA_VERSION


def test_initialize_schema_is_idempotent(fresh_db):
    from config.settings import DB_SCHEMA_VERSION
    from db import get_connection
    from db.schema import initialize_schema

    initialize_schema()
    initialize_schema()  # relance -> aucune erreur, version inchangée
    assert _schema_version(get_connection()) == DB_SCHEMA_VERSION


def test_rerun_preserves_existing_data(fresh_db):
    from db import get_connection
    from db.schema import initialize_schema

    initialize_schema()
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO documents (path, filename, page_count) VALUES (?, ?, ?)",
            ("/tmp/doc.pdf", "doc.pdf", 12),
        )
    initialize_schema()
    row = get_connection().execute("SELECT filename, page_count FROM documents").fetchone()
    assert row["filename"] == "doc.pdf"
    assert row["page_count"] == 12


def test_connection_sets_busy_timeout(fresh_db):
    # F2 : get_connection() doit poser busy_timeout (anti « database is locked »).
    from db import get_connection

    timeout = get_connection().execute("PRAGMA busy_timeout").fetchone()[0]
    assert int(timeout) >= 5000


# ── v35 : module langues, méthode feuilleton (plan D22) ──────────────────────

V35_TABLES = (
    "lang_program_points", "lang_script_units", "lang_placement_items", "lang_story_bibles",
    "lang_story_arcs", "lang_episodes", "lang_runs", "lang_run_steps", "lang_reveal_events",
    "lang_item_attempts", "lang_second_wave_ratings", "lang_lexicon", "lang_script_progress",
    "lang_program_progress", "lang_level_history", "lang_vocalized_forms", "lang_reports",
    "lang_daily_activity", "lang_weekly_analysis",
)
V35_PROFILE_COLUMNS = (
    "flow", "episode_n", "program_order", "ladder_step", "interests_json", "onboarding_done",
    "second_wave_started", "last_bilan_episode_n", "force_respiration", "replay_queue_json",
)


def _tables(conn) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_v35_creates_every_feuilleton_table(fresh_db):
    from db import get_connection
    from db.schema import initialize_schema

    initialize_schema()
    conn = get_connection()
    assert set(V35_TABLES) <= _tables(conn)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(lang_profiles)")}
    assert set(V35_PROFILE_COLUMNS) <= columns


def test_v35_upgrades_a_populated_v34_database_without_touching_it(fresh_db, monkeypatch):
    """Une base v34 avec un profil de langue hérité : la migration ajoute les
    tables et colonnes, ne perd rien, et laisse le profil sur le flux hérité
    (le passage au feuilleton se fait au premier accès, pas en migration)."""
    from db import get_connection, migrations
    from db.schema import SCHEMA_SQL, _ensure_default_user

    conn = get_connection()
    monkeypatch.setattr(migrations, "TARGET_SCHEMA_VERSION", 34)
    with conn:
        conn.executescript(SCHEMA_SQL)
        migrations.run_migrations(conn)
        _ensure_default_user(conn)
    assert _schema_version(conn) == 34
    assert "lang_episodes" not in _tables(conn)
    with conn:
        conn.execute("INSERT INTO lang_profiles (user_id, language, level, placement_done) VALUES (1, 'espagnol', 'B1', 1)")
        conn.execute(
            "INSERT INTO flashcards (user_id, front, back, language, source, dedup_key) "
            "VALUES (1, 'maison en espagnol', 'casa', 'espagnol', 'lang_vocab', 'k1')"
        )
    monkeypatch.setattr(migrations, "TARGET_SCHEMA_VERSION", 35)
    with conn:
        migrations.run_migrations(conn)
        migrations.run_migrations(conn)  # rejouée : aucune erreur, rien ne change
    assert _schema_version(conn) == 35
    profile = conn.execute("SELECT * FROM lang_profiles WHERE language='espagnol'").fetchone()
    assert profile["level"] == "B1" and profile["placement_done"] == 1
    assert profile["flow"] == "legacy" and profile["episode_n"] == 0
    assert conn.execute("SELECT COUNT(*) FROM flashcards").fetchone()[0] == 1
    assert set(V35_TABLES) <= _tables(conn)


# ── v36 : langue d'explication du feuilleton (§ 14, n° 14) ───────────────────

def test_v36_gives_existing_profiles_french_explanations(fresh_db, monkeypatch):
    """Un profil feuilleton déjà écrit en français le reste : la colonne
    `explain_lang` arrive avec 'fr' par défaut, et la migration rejouée ne
    change rien."""
    from db import get_connection, migrations
    from db.schema import SCHEMA_SQL, _ensure_default_user

    conn = get_connection()
    monkeypatch.setattr(migrations, "TARGET_SCHEMA_VERSION", 35)
    with conn:
        conn.executescript(SCHEMA_SQL)
        migrations.run_migrations(conn)
        _ensure_default_user(conn)
        conn.execute("INSERT INTO lang_profiles (user_id, language, flow, episode_n) VALUES (1, 'espagnol', 'feuilleton', 4)")
    monkeypatch.setattr(migrations, "TARGET_SCHEMA_VERSION", 36)
    with conn:
        migrations.run_migrations(conn)
        migrations.run_migrations(conn)
    assert _schema_version(conn) == 36
    profile = conn.execute("SELECT * FROM lang_profiles WHERE language='espagnol'").fetchone()
    assert profile["explain_lang"] == "fr" and profile["flow"] == "feuilleton" and profile["episode_n"] == 4


# ── v38 : séances de pratique (quiz, langues) ────────────────────────────────

def test_v38_adds_practice_sessions_without_touching_reading_history(fresh_db, monkeypatch):
    """Une base v37 avec une lecture finalisée : la migration ajoute la table des
    séances de pratique, sa courbe de jauges, les réponses de quiz, et rattache
    `metacog_history` et `session_reflections` — sans rien perdre, rejouable."""
    from db import get_connection, migrations
    from db.schema import SCHEMA_SQL, _ensure_default_user

    conn = get_connection()
    monkeypatch.setattr(migrations, "TARGET_SCHEMA_VERSION", 37)
    with conn:
        conn.executescript(SCHEMA_SQL)
        migrations.run_migrations(conn)
        _ensure_default_user(conn)
        conn.execute("INSERT OR IGNORE INTO metacog_profile (user_id) VALUES (1)")
        conn.execute(
            "INSERT INTO metacog_history (user_id, criterion, value_before, value_after, session_score, alpha) "
            "VALUES (1, 'retention', 50, 60, 70, 0.5)"
        )
    assert "practice_sessions" not in _tables(conn)
    monkeypatch.setattr(migrations, "TARGET_SCHEMA_VERSION", 38)
    with conn:
        migrations.run_migrations(conn)
        migrations.run_migrations(conn)  # rejouée : aucune erreur, rien ne change
    assert _schema_version(conn) == 38
    assert {"practice_sessions", "practice_session_gauges", "quiz_session_answers"} <= _tables(conn)
    for table in ("metacog_history", "session_reflections"):
        columns = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert "practice_session_id" in columns
    row = conn.execute("SELECT * FROM metacog_history").fetchone()
    assert row["value_after"] == 60 and row["practice_session_id"] is None


# ── v39 : une matière par langue ─────────────────────────────────────────────

def test_v39_spreads_the_old_languages_subject(fresh_db, monkeypatch):
    """« langues » disparaît : le vocabulaire anglais du catalogue et la maîtrise
    qu'il a mesurée passent à « anglais », un document de langue prend la langue
    qu'il nomme, et toute matière écrite autrement que sa clé la rejoint —
    fusion comprise. Rejouée, la migration ne change plus rien."""
    from db import get_connection, migrations
    from db.schema import SCHEMA_SQL, _ensure_default_user

    conn = get_connection()
    monkeypatch.setattr(migrations, "TARGET_SCHEMA_VERSION", 38)
    with conn:
        conn.executescript(SCHEMA_SQL)
        migrations.run_migrations(conn)
        _ensure_default_user(conn)
        conn.execute(
            "INSERT INTO quiz_static_questions (question, answer, category) "
            "VALUES ('Que signifie « to borrow » ?', 'Emprunter', 'langues')"
        )
        for path, filename, subject, summary in (
            ("/tmp/a.pdf", "Spanish_basics.pdf", "langues", ""),
            ("/tmp/b.pdf", "notes.pdf", "langues", "Des notes."),
            ("/tmp/c.pdf", "demo.pdf", "Informatique", ""),
            ("/tmp/d.pdf", "demo-en.pdf", "Computer science", ""),
            ("/tmp/e.pdf", "cours.pdf", "physique", ""),
        ):
            conn.execute(
                "INSERT INTO documents (path, filename, page_count, subject, auto_summary) "
                "VALUES (?, ?, 1, ?, ?)",
                (path, filename, subject, summary),
            )
        conn.executemany(
            "INSERT INTO subject_profile (user_id, subject, level, questions_count, correct_count) "
            "VALUES (1, ?, ?, ?, ?)",
            [("langues", 75.0, 12, 9), ("Informatique", 40.0, 2, 1), ("informatique", 80.0, 2, 2)],
        )
        conn.executemany(
            "INSERT INTO subject_history (user_id, subject, value_before, value_after, source) "
            "VALUES (1, ?, 50, 60, 'quiz')",
            [("langues",), ("langues",), ("Informatique",)],
        )

    monkeypatch.setattr(migrations, "TARGET_SCHEMA_VERSION", 39)
    with conn:
        migrations.run_migrations(conn)
        migrations.run_migrations(conn)
    assert _schema_version(conn) == 39

    assert [r["category"] for r in conn.execute("SELECT category FROM quiz_static_questions")] == ["anglais"]
    subjects = dict(conn.execute("SELECT filename, subject FROM documents").fetchall())
    assert subjects == {
        "Spanish_basics.pdf": "espagnol",
        "notes.pdf": "culture",
        "demo.pdf": "informatique",
        "demo-en.pdf": "informatique",
        "cours.pdf": "physique",
    }
    profile = {r["subject"]: r for r in conn.execute("SELECT * FROM subject_profile")}
    assert set(profile) == {"anglais", "informatique"}
    assert profile["anglais"]["level"] == 75.0 and profile["anglais"]["questions_count"] == 12
    # Fusion : effectifs additionnés, niveau pondéré par les questions.
    assert profile["informatique"]["questions_count"] == 4
    assert profile["informatique"]["correct_count"] == 3
    assert profile["informatique"]["level"] == 60.0
    history = [r["subject"] for r in conn.execute("SELECT subject FROM subject_history ORDER BY id")]
    assert history == ["anglais", "anglais", "informatique"]


# ── v40 : leçon du point, expression écrite, traductions montrées ────────────

def test_v40_adds_lessons_writings_and_line_reveals(fresh_db, monkeypatch):
    """Une base v39 avec un profil et une séance : la migration ajoute les trois
    tables sans rien toucher, rejouable ; une séance n'a qu'une expression
    écrite, et une traduction montrée ne se compte qu'une fois par passe."""
    import sqlite3

    from db import get_connection, migrations
    from db.schema import SCHEMA_SQL, _ensure_default_user

    conn = get_connection()
    monkeypatch.setattr(migrations, "TARGET_SCHEMA_VERSION", 39)
    with conn:
        conn.executescript(SCHEMA_SQL)
        migrations.run_migrations(conn)
        _ensure_default_user(conn)
        conn.execute("INSERT INTO lang_profiles (user_id, language, flow, episode_n) VALUES (1, 'espagnol', 'feuilleton', 2)")
        conn.execute("INSERT INTO lang_runs (profile_id, mode, plan_json, status, study_date) "
                     "VALUES (1, 'episode', '{}', 'completed', '2026-10-01')")
        conn.execute("INSERT INTO lang_episodes (profile_id, episode_n, kind, format, ladder_step, params_json, status) "
                     "VALUES (1, 1, 'normal', 'dialogue', 0, '{}', 'played')")
    assert not {"lang_point_lessons", "lang_writings", "lang_line_reveals"} & _tables(conn)
    monkeypatch.setattr(migrations, "TARGET_SCHEMA_VERSION", 40)
    with conn:
        migrations.run_migrations(conn)
        migrations.run_migrations(conn)  # rejouée : aucune erreur, rien ne change
    assert _schema_version(conn) == 40
    assert {"lang_point_lessons", "lang_writings", "lang_line_reveals"} <= _tables(conn)
    assert conn.execute("SELECT episode_n FROM lang_profiles").fetchone()[0] == 2

    from db import lang_episode_db as store

    first = store.create_writing(1, 1, 1, task={"kind": "message"}, text="Hola", checks=None, status="pending")
    assert store.create_writing(1, 1, 1, task={}, text="otra", checks=None, status="pending") == first
    assert store.get_writing(first)["text"] == "Hola"
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("INSERT INTO lang_writings (profile_id, run_id, task_json) VALUES (1, 1, '{}')")
    events = [{"episode_id": 1, "line_idx": 0, "pass": "lecture", "via": "line"}]
    assert store.add_line_reveals(1, events) == 1 and store.add_line_reveals(1, events) == 0
    store.save_point_lesson("espagnol", "es.a1.saludos", "fr", status="ready", lesson={"rule": "r"},
                            point_hash="h1", model="m", attempts=1, generation={})
    store.save_point_lesson("espagnol", "es.a1.saludos", "fr", status="ready", lesson={"rule": "r2"},
                            point_hash="h2", model="m", attempts=2, generation={})
    lesson = store.get_point_lesson("espagnol", "es.a1.saludos", "fr")
    assert lesson["lesson"] == {"rule": "r2"} and lesson["point_hash"] == "h2"
    assert store.get_point_lesson("espagnol", "es.a1.saludos", "en") is None
