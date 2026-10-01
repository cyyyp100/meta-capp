"""Choix de la coque : fenêtre native, ou navigateur quand elle est impossible.

Meta-Capp doit s'ouvrir partout où Python tourne. pywebview exige un moteur web
natif — WebKit (macOS), WebView2 (Windows), GTK/WebKitGTK ou Qt (Linux) — et
sans lui `webview.start()` levait une exception : l'application ne s'ouvrait
pas du tout. Ces tests figent le repli : MÊME serveur, mêmes gardes, l'interface
dans le navigateur par défaut ; et un second lancement rouvre le premier au lieu
de produire une fenêtre au nonce inconnu (403 partout).
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import types
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop import pywebview_main as shell  # noqa: E402


# ── Le moteur natif est-il utilisable ? ─────────────────────────────────────


def _fake_guilib(monkeypatch, renderer: str | None = None, error: Exception | None = None, lib=None):
    import importlib

    guilib = importlib.import_module("webview.guilib")  # pas `webview.guilib`, attribut à None

    def initialize(*_args, **_kwargs):
        if error is not None:
            raise error
        return lib if lib is not None else types.SimpleNamespace(renderer=renderer)

    monkeypatch.setattr(guilib, "initialize", initialize)


def test_linux_without_display_goes_to_the_browser(monkeypatch):
    monkeypatch.setattr(shell.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    _fake_guilib(monkeypatch, renderer="gtkwebkit2")
    assert "affichage" in shell._native_window_unavailable()


def test_missing_gtk_and_qt_goes_to_the_browser(monkeypatch):
    monkeypatch.setattr(shell.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    _fake_guilib(monkeypatch, error=RuntimeError("You must have either QT or GTK"))
    assert "QT or GTK" in shell._native_window_unavailable()


@pytest.mark.parametrize("renderer", ["mshtml", "qtwebkit"])
def test_engines_too_old_for_the_bundle_go_to_the_browser(monkeypatch, renderer):
    """Windows sans WebView2 : pywebview se rabat sur Internet Explorer 11, qui
    ouvrirait une fenêtre blanche (le bundle est en ES2020)."""
    monkeypatch.setattr(shell.sys, "platform", "win32")
    _fake_guilib(monkeypatch, renderer=renderer)
    assert renderer in shell._native_window_unavailable()


@pytest.mark.parametrize("renderer", ["wkwebview", "edgechromium", "gtkwebkit2", "qtwebengine"])
def test_modern_engines_keep_the_native_window(monkeypatch, renderer):
    monkeypatch.setattr(shell.sys, "platform", "darwin")
    _fake_guilib(monkeypatch, renderer=renderer)
    assert shell._native_window_unavailable() is None


def test_gtk_application_is_recreated_with_the_menu(monkeypatch):
    """`initialize()` crée l'application GTK sans menu, et `webview.start(menu=…)`
    ne la recrée pas : sans cet oubli volontaire, la barre de menu disparaissait
    sous Linux."""
    monkeypatch.setattr(shell.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    lib = types.SimpleNamespace(renderer="gtkwebkit2", _app=object())
    _fake_guilib(monkeypatch, lib=lib)
    assert shell._native_window_unavailable() is None
    assert lib._app is None


@pytest.mark.skipif(sys.platform != "darwin", reason="moteur WebKit réel de macOS")
def test_the_real_engine_of_this_mac_is_detected():
    """Sans le faux guilib : `webview.guilib` est un ATTRIBUT à None jusqu'à
    `webview.start()` — l'importer par erreur envoyait tout Mac au navigateur."""
    assert shell._native_window_unavailable() is None


# ── Lancement complet, sans vrai serveur ni vraie fenêtre ───────────────────


@pytest.fixture
def launch(monkeypatch, tmp_path):
    """`shell.main()` avec tout ce qui touche l'OS remplacé ; renvoie le journal."""
    seen: dict = {"served": False, "native": [], "browser": []}

    class FakeServer:
        should_exit = False

    def fake_serve(holder, sock):
        seen["served"] = sock
        holder["server"] = seen["server"] = FakeServer()

    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.setattr(shell, "DB_PATH", str(tmp_path / "nwol.db"))
    monkeypatch.setattr(shell, "_build_frontend_if_needed", lambda: None)
    monkeypatch.setattr(shell, "_serve", fake_serve)
    monkeypatch.setattr(shell, "_wait_until_ready", lambda: True)
    monkeypatch.setattr(shell, "_claim_or_reopen", lambda: ("socket-réservé", None))
    monkeypatch.setattr(shell, "_native_window_unavailable", lambda: None)
    monkeypatch.setattr(shell, "_run_native", lambda url: seen["native"].append(url))
    monkeypatch.setattr(
        shell, "_run_in_browser",
        lambda url, reason, thread, stop=None: seen["browser"].append((url, reason, thread)) or seen.update(stop=stop),
    )
    monkeypatch.setattr(shell.security, "set_launch_token", lambda token: seen.setdefault("token", token))
    return seen


def test_native_window_when_available(launch):
    shell.main()
    assert launch["served"] == "socket-réservé", "uvicorn sert le socket réservé, pas un second bind"
    assert len(launch["native"]) == 1 and launch["browser"] == []
    assert launch["native"][0].endswith(f"/?lt={launch['token']}")


def test_browser_when_no_native_engine(launch, monkeypatch):
    monkeypatch.setattr(shell, "_native_window_unavailable", lambda: "aucun moteur web natif")
    shell.main()
    assert launch["native"] == []
    url, reason, thread = launch["browser"][0]
    assert url.endswith(f"/?lt={launch['token']}")
    assert reason == "aucun moteur web natif"
    assert isinstance(thread, threading.Thread)


def test_browser_when_the_native_window_crashes(launch, monkeypatch):
    """Moteur présent mais fenêtre impossible (bibliothèque système absente) :
    l'application reste utilisable plutôt que de mourir au démarrage."""
    def broken(_url):
        raise RuntimeError("libwebkit2gtk introuvable")

    monkeypatch.setattr(shell, "_run_native", broken)
    shell.main()
    assert "libwebkit2gtk" in launch["browser"][0][1]


def test_browser_mode_receives_a_way_to_stop_the_server(launch, monkeypatch):
    """Sans terminal, rien d'autre n'arrête le serveur : « Quitter » et l'arrêt
    automatique (services/lifecycle) passent par cette fonction."""
    monkeypatch.setattr(shell, "_native_window_unavailable", lambda: "aucun moteur web natif")
    shell.main()
    launch["server"].should_exit = False  # remis par le `finally` de main()
    launch["stop"]()
    assert launch["server"].should_exit is True


def test_browser_on_request(launch, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--browser"])
    shell.main()
    assert launch["native"] == [] and len(launch["browser"]) == 1


def test_second_launch_reopens_the_running_instance(launch, monkeypatch):
    """Avant : la fenêtre du second lancement portait un nonce que le premier
    serveur ne connaissait pas — 403 sur chaque requête."""
    monkeypatch.setattr(shell, "_claim_or_reopen", lambda: (None, "nonce-du-premier"))
    shell.main()
    assert launch["served"] is False, "le port est déjà tenu : pas de second serveur"
    assert "token" not in launch, "on ne génère pas de nonce que personne ne connaît"
    assert launch["native"] == ["http://127.0.0.1:8756/?lt=nonce-du-premier"]


def test_instance_file_is_written_then_removed(launch, tmp_path, monkeypatch):
    written: dict = {}

    def capture(url):
        written.update(json.loads((tmp_path / "instance.json").read_text()))

    monkeypatch.setattr(shell, "_run_native", capture)
    shell.main()
    assert written["token"] == launch["token"] and written["port"] == shell.PORT
    assert not (tmp_path / "instance.json").exists(), "nettoyé à la fermeture"


def test_instance_file_is_private(tmp_path, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("permissions POSIX")
    monkeypatch.setattr(shell, "DB_PATH", str(tmp_path / "nwol.db"))
    shell._write_instance("secret")
    assert (tmp_path / "instance.json").stat().st_mode & 0o777 == 0o600


def test_clearing_never_removes_another_instance_file(tmp_path, monkeypatch):
    monkeypatch.setattr(shell, "DB_PATH", str(tmp_path / "nwol.db"))
    shell._write_instance("celui-de-l-autre")
    shell._clear_instance("le-mien")
    assert (tmp_path / "instance.json").exists()


# ── Le port : à nous, ou à une instance qu'on rouvre ────────────────────────

NONCE = "n" * 43  # forme de `security.new_launch_token()`


@pytest.fixture
def free_port(monkeypatch):
    """Un vrai port libre à la place de 8756, qu'une instance de dev peut tenir."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setattr(shell, "PORT", port)
    return port


def test_two_launches_cannot_both_claim_the_port(free_port):
    """Sonder le port puis laisser uvicorn le prendre laissait réussir deux
    lancements simultanés (double-clic) : le perdant ouvrait une fenêtre au
    nonce inconnu. Le bind est désormais le test, et le socket reste réservé."""
    first = shell._claim_port()
    assert first is not None
    try:
        assert shell._claim_port() is None
    finally:
        first.close()
    again = shell._claim_port()
    assert again is not None, "libéré, le port se reprend aussitôt"
    again.close()


def test_free_port_is_claimed_without_any_probe(monkeypatch):
    monkeypatch.setattr(shell, "_claim_port", lambda: "socket")
    monkeypatch.setattr(shell, "_api_status", lambda *_a: pytest.fail("aucune sonde HTTP si le port est libre"))
    assert shell._claim_or_reopen() == ("socket", None)


def test_running_instance_is_reopened_with_its_own_token(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "DB_PATH", str(tmp_path / "nwol.db"))
    shell._write_instance(NONCE)
    monkeypatch.setattr(shell, "_claim_port", lambda: None)
    monkeypatch.setattr(
        shell, "_api_status",
        lambda path, token: 200 if path == "/api/health" or token == NONCE else 403,
    )
    assert shell._claim_or_reopen() == (None, NONCE)


def test_an_instance_still_starting_is_waited_for(monkeypatch, tmp_path):
    """Double-clic impatient : la première instance ne répond pas encore, puis
    répond et écrit son fichier — on la rouvre au lieu d'échouer."""
    monkeypatch.setattr(shell, "DB_PATH", str(tmp_path / "nwol.db"))
    monkeypatch.setattr(shell, "_claim_port", lambda: None)
    health = iter([None, None])

    def api_status(path, token):
        if path == "/api/health":
            status = next(health, 200)
            if status == 200:
                shell._write_instance(NONCE)  # dès sa première réponse (cf. `main`)
            return status
        return 200 if token == NONCE else 403

    monkeypatch.setattr(shell, "_api_status", api_status)
    assert shell._claim_or_reopen() == (None, NONCE)


def test_relaunch_right_after_quitting_takes_the_freed_port(monkeypatch, tmp_path):
    """L'instance qui se ferme efface son fichier AVANT de libérer le port : on
    attend le port plutôt que de rouvrir un serveur mourant."""
    monkeypatch.setattr(shell, "DB_PATH", str(tmp_path / "nwol.db"))
    claims = iter([None, None, "socket"])
    monkeypatch.setattr(shell, "_claim_port", lambda: next(claims))
    monkeypatch.setattr(shell, "_api_status", lambda path, token: 200 if path == "/api/health" else 403)
    assert shell._claim_or_reopen() == ("socket", None)


def test_port_held_by_an_unreachable_instance_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "DB_PATH", str(tmp_path / "nwol.db"))
    monkeypatch.setattr(shell, "_claim_port", lambda: None)
    monkeypatch.setattr(shell, "_api_status", lambda path, token: 200 if path == "/api/health" else 403)
    monkeypatch.setattr(shell, "_INSTANCE_FILE_GRACE_S", 0.4)
    with pytest.raises(RuntimeError, match="autre instance de Meta-Capp"):
        shell._claim_or_reopen()


def test_port_held_by_another_program_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(shell, "_claim_port", lambda: None)
    monkeypatch.setattr(shell, "_api_status", lambda *_a: None)
    with pytest.raises(RuntimeError, match="autre programme"):
        shell._claim_or_reopen(timeout=0.4)


@pytest.mark.parametrize("content", ['{"token": "x\\" onload=\\"alert(1)"}', "[1, 2]", "{"])
def test_a_damaged_instance_file_never_reaches_the_address(tmp_path, monkeypatch, content):
    monkeypatch.setattr(shell, "DB_PATH", str(tmp_path / "nwol.db"))
    (tmp_path / "instance.json").write_text(content)
    assert shell._instance_token() is None


def test_local_probes_ignore_the_system_proxy(monkeypatch, free_port):
    """`urlopen` applique le proxy du système même à 127.0.0.1 : derrière celui
    d'un réseau d'école, la sonde de démarrage échouait — et le nonce partait
    au proxy."""

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - API de http.server
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", free_port), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for name in ("http_proxy", "HTTP_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")  # proxy injoignable
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.setattr(urllib.request, "_opener", None)  # l'opener par défaut relirait l'environnement
    try:
        assert shell._api_status("/api/health", None) == 200
    finally:
        server.shutdown()
        server.server_close()


def test_browser_mode_prints_the_address_and_waits_for_the_server(monkeypatch, capsys):
    opened: list = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: opened.append(url) or True)
    stop = threading.Event()
    server = threading.Thread(target=stop.wait, daemon=True)
    server.start()
    threading.Timer(0.3, stop.set).start()

    shell._run_in_browser("http://127.0.0.1:8756/?lt=abc", "test", server)

    assert opened == ["http://127.0.0.1:8756/?lt=abc"]
    out = capsys.readouterr().out
    assert "http://127.0.0.1:8756/?lt=abc" in out
    assert not server.is_alive()


def test_browser_mode_enables_the_auto_stop_before_opening_the_tab(monkeypatch, capsys):
    """La connexion de présence du premier onglet doit trouver le mode actif."""
    from services import lifecycle

    order: list = []
    monkeypatch.setattr(lifecycle, "enable_browser_mode", lambda stop: order.append(("enable", stop)))
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: order.append(("open", url)) or True)
    server = threading.Thread(target=lambda: None)
    server.start()
    server.join()

    def stop():
        return None

    shell._run_in_browser("http://127.0.0.1:8756/?lt=abc", "test", server, stop)

    assert order == [("enable", stop), ("open", "http://127.0.0.1:8756/?lt=abc")]
    assert "Ctrl+C" in capsys.readouterr().out


def test_reopening_a_running_instance_enables_nothing(monkeypatch):
    """Second lancement : c'est l'instance déjà lancée qui surveille ses onglets."""
    from services import lifecycle

    monkeypatch.setattr(lifecycle, "enable_browser_mode", lambda stop: pytest.fail("rien à activer ici"))
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: True)
    shell._run_in_browser("http://127.0.0.1:8756/?lt=abc", "test", None, lambda: None)
