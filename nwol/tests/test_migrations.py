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
