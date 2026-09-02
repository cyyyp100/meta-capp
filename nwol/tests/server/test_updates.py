"""Durcissement de la vérification de mise à jour (§ B3 du plan de refonte).

C'est le seul appel sortant de l'édition locale. Chacune des règles vérifiées ici
couvre une attaque réelle, décrite dans `architecture/13-mises-a-jour-et-distribution.md` :
une réponse GitHub falsifiée, un compte compromis, un MITM, un SSRF local.
"""
from __future__ import annotations

import json
import pytest


@pytest.fixture
def enabled(client):
    """Active l'option (elle est fausse par défaut, et ce défaut est testé à part)."""
    assert client.post("/api/preferences", json={"updates_check": True}).status_code == 200
    return client


def _fake_release(monkeypatch, payload: dict | str) -> list[str]:
    """Remplace l'ouverture réseau et journalise les URL réellement demandées."""
    called: list[str] = []

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self, _size=None):
            raw = payload if isinstance(payload, str) else json.dumps(payload)
            return raw.encode()

    class _Opener:
        def open(self, request, timeout=None):  # noqa: ARG002
            called.append(request.full_url)
            return _Response()

    monkeypatch.setattr("urllib.request.build_opener", lambda *_handlers: _Opener())
    return called


def test_disabled_by_default_and_emits_no_request(client, monkeypatch):
    """L'état par défaut ne doit produire AUCUNE requête sortante.

    C'est la garantie que porte la promesse « 100 % local » : tant que personne
    n'a coché la case, l'application ne parle à personne."""
    def _explode(*_args, **_kwargs):
        raise AssertionError("aucune requête ne doit partir quand l'option est coupée")

    monkeypatch.setattr("urllib.request.build_opener", _explode)

    body = client.get("/api/updates/check").json()
    assert body["enabled"] is False
    assert body["checked"] is False
    assert body["update_available"] is False


def test_only_the_version_is_taken_from_the_response(enabled, monkeypatch):
    """Une réponse hostile ne peut pas imposer une URL.

    `html_url` en `file://` : sur macOS `webbrowser.open()` passe par `open(1)`,
    qui l'honore — ce serait une primitive d'exécution locale. L'URL renvoyée
    doit rester la constante compilée."""
    from services.updates import LATEST_RELEASE_API, RELEASES_PAGE

    called = _fake_release(monkeypatch, {
        "tag_name": "v9.9.9",
        "html_url": "file:///Applications/Calculator.app",
        "assets": [{"browser_download_url": "x-evil-scheme://run"}],
        "body": "<img src=x onerror=alert(1)>",
    })

    body = enabled.get("/api/updates/check").json()

    assert called == [LATEST_RELEASE_API]  # un seul hôte, celui qui est en dur
    assert body["url"] == RELEASES_PAGE
    assert "file://" not in json.dumps(body)
    assert "x-evil-scheme" not in json.dumps(body)
    # Les notes de version ne voyagent pas : rien à assainir dans le webview.
    assert "onerror" not in json.dumps(body)
    assert body["latest"] == "9.9.9"


@pytest.mark.parametrize("tag", [
    "v1.2.3; rm -rf /",
    "file:///etc/passwd",
    "1.2.3\nX",
    "v" + "9" * 64,
    "latest",
    "",
])
def test_malformed_versions_are_rejected(enabled, monkeypatch, tag):
    """La regex est appliquée AVANT tout usage, stockage ou affichage."""
    _fake_release(monkeypatch, {"tag_name": tag})
    body = enabled.get("/api/updates/check").json()
    assert body["latest"] is None
    assert body["checked"] is False
    assert body["update_available"] is False


def test_unreadable_response_fails_silently(enabled, monkeypatch):
    """Panne de GitHub ou hors ligne : ni erreur, ni blocage."""
    _fake_release(monkeypatch, "pas du json")
    response = enabled.get("/api/updates/check")
    assert response.status_code == 200
    assert response.json()["checked"] is False


def test_network_failure_fails_silently(enabled, monkeypatch):
    import urllib.error

    class _Opener:
        def open(self, *_args, **_kwargs):
            raise urllib.error.URLError("hors ligne")

    monkeypatch.setattr("urllib.request.build_opener", lambda *_h: _Opener())
    response = enabled.get("/api/updates/check")
    assert response.status_code == 200
    assert response.json()["checked"] is False


def test_endpoint_takes_no_input(enabled, monkeypatch):
    """Aucun paramètre : un endpoint local qui accepte une URL est un SSRF
    joignable depuis n'importe quel processus de la machine."""
    from services.updates import LATEST_RELEASE_API

    called = _fake_release(monkeypatch, {"tag_name": "v0.0.1"})
    enabled.get("/api/updates/check?url=http://127.0.0.1:11434/api/tags&host=evil.test")
    assert called == [LATEST_RELEASE_API]


def test_check_stays_behind_the_launch_token_guard():
    """`/api/updates/check` ne doit PAS rejoindre `TOKEN_EXEMPT_PATHS`."""
    from server.security import TOKEN_EXEMPT_PATHS

    assert "/api/updates/check" not in TOKEN_EXEMPT_PATHS


def test_no_redirect_is_ever_followed():
    """L'hôte est connu et fixe : suivre une 302 rendrait à la réponse le
    contrôle qu'on vient de lui retirer en figeant l'URL."""
    from services.updates import _NoRedirect

    handler = _NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "http://evil.test") is None
