import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient sur une DB neuve isolée (lifespan = initialize_schema)."""
    import db
    from db import close_connection

    close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nwol.db"))
    # S2 : les tests importent leurs PDFs depuis tmp_path (hors home) -> racine
    # d'import autorisée pour la durée du test.
    monkeypatch.setenv("NWOL_IMPORT_ROOTS", str(tmp_path))

    from fastapi.testclient import TestClient

    from server.app import create_app

    # Host loopback : la garde S1 (LocalOnlyGuard) rejette tout autre Host.
    # (websocket_connect force ws://testserver -> on impose aussi le header.)
    with TestClient(create_app(), base_url="http://127.0.0.1:8756") as test_client:
        test_client.headers["host"] = "127.0.0.1:8756"
        yield test_client
    close_connection()
