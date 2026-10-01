"""Routes de la coque (`/api/shell`) : mode navigateur, Quitter, présence."""
from __future__ import annotations

from services import lifecycle


def test_not_in_browser_mode_by_default(client):
    assert client.get("/api/shell").json() == {"browser_mode": False}


def test_quit_is_refused_outside_browser_mode(client):
    """En fenêtre native, arrêter le serveur laisserait la fenêtre vide."""
    assert client.post("/api/shell/quit").status_code == 409


def test_quit_stops_the_server_in_browser_mode(client):
    stops: list = []
    lifecycle.enable_browser_mode(lambda: stops.append("stop"), watch=False)
    assert client.get("/api/shell").json() == {"browser_mode": True}
    res = client.post("/api/shell/quit")
    assert res.status_code == 200 and res.json() == {"stopping": True}
    assert stops == ["stop"]


def test_each_open_tab_is_counted_until_it_closes(client):
    lifecycle.enable_browser_mode(lambda: None, watch=False)
    with client.websocket_connect("/api/shell/presence") as ws:
        ws.send_text("ignoré")  # le client n'a rien à dire ; le serveur n'écoute pas
        assert lifecycle._tabs == 1
    assert lifecycle._tabs == 0


def test_shell_routes_require_the_launch_token(client, monkeypatch):
    """Comme le reste de l'API : sinon n'importe quel processus local pourrait
    arrêter l'application."""
    from server import security

    monkeypatch.setattr(security, "_launch_token", "nonce-de-test")
    assert client.get("/api/shell").status_code == 403
    assert client.post("/api/shell/quit").status_code == 403
    assert client.get("/api/shell", headers={"x-launch-token": "nonce-de-test"}).status_code == 200
