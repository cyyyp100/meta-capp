# Tests sauvegarde/restauration (export/import DB + logs) — priorité 4.3.
import sqlite3

SQLITE_MAGIC = b"SQLite format 3\x00"


def _insert_document(client, path="/tmp/x.pdf", filename="x.pdf") -> None:
    import db

    conn = db.get_connection()
    with conn:
        conn.execute(
            "INSERT INTO documents (path, filename, page_count) VALUES (?, ?, ?)",
            (path, filename, 3),
        )


def test_export_db_is_valid_snapshot(client, tmp_path):
    _insert_document(client, filename="export-me.pdf")
    res = client.get("/api/data/export")
    assert res.status_code == 200
    assert res.content.startswith(SQLITE_MAGIC)

    snapshot = tmp_path / "snapshot.db"
    snapshot.write_bytes(res.content)
    conn = sqlite3.connect(str(snapshot))
    try:
        row = conn.execute("SELECT filename FROM documents").fetchone()
    finally:
        conn.close()
    assert row[0] == "export-me.pdf"


def test_import_db_restores_data(client):
    import db

    _insert_document(client, filename="avant-backup.pdf")
    backup = client.get("/api/data/export").content

    # La base évolue après la sauvegarde…
    with db.get_connection() as conn:
        conn.execute("DELETE FROM documents")

    res = client.post("/api/data/import", content=backup)
    assert res.status_code == 200
    assert res.json()["restored"] is True
    row = db.get_connection().execute("SELECT filename FROM documents").fetchone()
    assert row["filename"] == "avant-backup.pdf"


def test_import_rejects_garbage(client):
    assert client.post("/api/data/import", content=b"").status_code == 400
    assert client.post("/api/data/import", content=b"pas une base sqlite").status_code == 400
    # SQLite valide mais pas un schéma Meta-Capp -> rejet.
    import sqlite3 as s
    import tempfile
    from pathlib import Path

    other = Path(tempfile.mkdtemp()) / "other.db"
    conn = s.connect(str(other))
    conn.execute("CREATE TABLE etranger (id INTEGER)")
    conn.commit()
    conn.close()
    res = client.post("/api/data/import", content=other.read_bytes())
    assert res.status_code == 400


def test_purge_requires_exact_confirmation(client):
    _insert_document(client, filename="a-garder.pdf")
    assert client.post("/api/data/purge", json={"confirm": "oui"}).status_code == 400
    assert client.post("/api/data/purge", json={}).status_code == 422
    # Rien n'a été effacé.
    import db

    assert db.get_connection().execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_purge_erases_everything_and_reseeds(client, tmp_path, monkeypatch):
    import db
    from services import data_export

    # Cache assets + logs factices : la purge doit les vider aussi.
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "page.png").write_bytes(b"png")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "nwol.log").write_text("trace")
    monkeypatch.setattr(data_export, "ASSETS_DIR", str(assets))
    monkeypatch.setattr(data_export, "LOG_FILE", str(log_dir / "nwol.log"))

    _insert_document(client, filename="perso.pdf")
    res = client.post("/api/data/purge", json={"confirm": "EFFACER"})
    assert res.status_code == 200
    assert res.json()["purged"] is True

    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    # Utilisateur par défaut re-seedé : l'app reste utilisable immédiatement.
    assert conn.execute("SELECT COUNT(*) FROM user").fetchone()[0] == 1
    assert not (assets / "page.png").exists()
    assert not (log_dir / "nwol.log").exists()


def test_purge_leaves_foreign_keys_enabled(client):
    """`PRAGMA foreign_keys` est ignoré dans une transaction : si la purge
    réactive les FK *dedans*, la connexion (mise en cache par thread et jamais
    fermée) reste sans intégrité référentielle pour toute la vie du process.

    On appelle le service directement : passer par le client HTTP exécuterait la
    purge dans un thread du pool, donc sur une *autre* connexion que celle que
    le test inspecte — et le test passerait même avec le bug."""
    import db
    from services.data_export import purge_all_data

    _insert_document(client, filename="perso.pdf")
    conn = db.get_connection()
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    purge_all_data()

    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_export_logs(client, tmp_path, monkeypatch):
    from services import data_export

    # Aucun log -> 404.
    monkeypatch.setattr(data_export, "LOG_FILE", str(tmp_path / "vide" / "nwol.log"))
    assert client.get("/api/data/export-logs").status_code == 404

    # Logs présents (rotation comprise) -> zip.
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "nwol.log").write_text("ligne 1\n")
    (log_dir / "nwol.log.1").write_text("ancienne rotation\n")
    monkeypatch.setattr(data_export, "LOG_FILE", str(log_dir / "nwol.log"))
    res = client.get("/api/data/export-logs")
    assert res.status_code == 200
    assert res.content[:2] == b"PK"  # zip
