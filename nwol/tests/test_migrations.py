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
