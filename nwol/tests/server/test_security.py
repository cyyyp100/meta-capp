# Tests sécurité P0 : S1 (Host/Origin/nonce), S2 (confinement import), S3
# (handler d'erreur global) + invariant réseau (anti-0.0.0.0).
import os

import pytest


# ── Invariant réseau ─────────────────────────────────────────────────────────

def test_server_binds_loopback_only():
    from server.config import HOST

    assert HOST == "127.0.0.1"


# ── S1 : garde Host (anti DNS-rebinding) ────────────────────────────────────

def test_foreign_host_rejected(client):
    res = client.get("/api/health", headers={"host": "evil.example:8756"})
    assert res.status_code == 403


def test_loopback_hosts_accepted(client):
    assert client.get("/api/health", headers={"host": "127.0.0.1:8756"}).status_code == 200
    assert client.get("/api/health", headers={"host": "localhost:8756"}).status_code == 200


def test_foreign_host_rejected_on_websocket(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/reader/1/stream", headers={"host": "evil.example:8756"}):
            pass


# ── S1 : garde Origin (anti CSRF cross-site) ────────────────────────────────

def test_foreign_origin_rejected(client):
    res = client.get("/api/library/recent", headers={"origin": "https://evil.example"})
    assert res.status_code == 403


def test_dev_and_same_origins_accepted(client):
    assert client.get("/api/health", headers={"origin": "http://localhost:5173"}).status_code == 200
    assert client.get("/api/health", headers={"origin": "http://127.0.0.1:8756"}).status_code == 200


# ── S1 : nonce de lancement (coque desktop) ─────────────────────────────────

@pytest.fixture
def launch_token():
    from server import security

    security.set_launch_token("nonce-de-test")
    yield "nonce-de-test"
    security.set_launch_token(None)


def test_token_required_when_configured(client, launch_token):
    assert client.get("/api/library/recent").status_code == 403


def test_health_exempt_from_token(client, launch_token):
    # Sonde de démarrage de la coque : ne révèle aucune donnée.
    assert client.get("/api/health").status_code == 200


def test_token_accepted_via_header_cookie_and_query(client, launch_token):
    ok = client.get("/api/library/recent", headers={"x-launch-token": launch_token})
    assert ok.status_code == 200
    ok = client.get("/api/library/recent", headers={"cookie": f"nwol_lt={launch_token}"})
    assert ok.status_code == 200
    ok = client.get(f"/api/library/recent?lt={launch_token}")
    assert ok.status_code == 200


def test_wrong_token_rejected(client, launch_token):
    res = client.get("/api/library/recent", headers={"x-launch-token": "faux-nonce"})
    assert res.status_code == 403


def test_websocket_requires_token(client, launch_token):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/reader/1/stream"):
            pass
    # Avec le nonce en query (comme le frontend) : le handshake passe.
    with client.websocket_connect(f"/api/reader/1/stream?lt={launch_token}"):
        pass


def test_static_frontend_not_token_gated(client, launch_token):
    # Hors /api : la coquille statique reste servie (le nonce protège les données).
    res = client.get("/")
    assert res.status_code in (200, 404)  # 404 si frontend/dist absent (CI)


# ── S2 : confinement de l'import PDF ────────────────────────────────────────

@pytest.fixture
def allowed_root(tmp_path, monkeypatch):
    root = tmp_path / "autorise"
    root.mkdir()
    monkeypatch.setenv("NWOL_IMPORT_ROOTS", str(root))
    # import_roots() inclut toujours Path.home(). Sur Windows le tmp_path de
    # pytest vit SOUS le profil utilisateur (C:\Users\...\AppData\Local\Temp),
    # donc un dossier « hors racine » y resterait autorisé par la racine home.
    # On confine home à un dossier dédié qui ne contient pas « ailleurs ».
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))          # POSIX
    monkeypatch.setenv("USERPROFILE", str(home))   # Windows
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    return root


def test_import_rejects_nonexistent_and_non_pdf(client):
    assert client.post("/api/library/import", json={"path": "/nulle/part.pdf"}).status_code == 400
    assert client.post("/api/library/import", json={"path": "/etc/hosts"}).status_code == 400


def test_import_rejects_path_outside_allowed_roots(client, tmp_path, allowed_root):
    outside = tmp_path / "ailleurs"
    outside.mkdir()
    rogue = outside / "doc.pdf"
    rogue.write_bytes(b"%PDF-1.4 fake")
    res = client.post("/api/library/import", json={"path": str(rogue)})
    assert res.status_code == 400


def test_import_rejects_parent_traversal(client, allowed_root):
    sneaky = str(allowed_root / ".." / "ailleurs" / "doc.pdf")
    assert client.post("/api/library/import", json={"path": sneaky}).status_code == 400


def test_import_rejects_symlink_escaping_root(client, tmp_path, allowed_root):
    outside = tmp_path / "ailleurs"
    outside.mkdir()
    target = outside / "vrai.pdf"
    target.write_bytes(b"%PDF-1.4 fake")
    link = allowed_root / "lien.pdf"
    os.symlink(target, link)
    res = client.post("/api/library/import", json={"path": str(link)})
    assert res.status_code == 400


def test_import_accepts_pdf_in_allowed_root(client, monkeypatch, allowed_root):
    pdf = allowed_root / "cours.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    import services.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "import_pdf", lambda path: {"id": 1, "path": path})
    res = client.post("/api/library/import", json={"path": str(pdf)})
    assert res.status_code == 200
    assert res.json()["id"] == 1


# ── S3 : handler d'erreur global ────────────────────────────────────────────

def test_unhandled_exception_returns_normalized_json(tmp_path, monkeypatch):
    import db

    db.close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nwol.db"))

    from fastapi.testclient import TestClient

    import server.routers.library as library_router
    from server.app import create_app

    def boom(limit=10):
        raise RuntimeError("boom interne")

    monkeypatch.setattr(library_router, "list_recent_documents", boom)
    with TestClient(
        create_app(), base_url="http://127.0.0.1:8756", raise_server_exceptions=False
    ) as tc:
        res = tc.get("/api/library/recent")
    db.close_connection()
    assert res.status_code == 500
    assert res.json() == {"error": "internal"}
    # La trace ne fuit jamais au client.
    assert "boom interne" not in res.text
