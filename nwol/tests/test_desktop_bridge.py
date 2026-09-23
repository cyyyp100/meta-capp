"""Surface native atteignable depuis le JavaScript du webview.

Deux portes relient la page à l'OS, et un script ou un lien injecté dans la page
(sortie de LLM mal échappée, contenu de document) les trouve toutes les deux :

1. le pont `pywebview._bridge.call(nom, args)` — pywebview 6.2.1 résout `nom` par
   une chaîne de `getattr` sur `js_api`, sans écarter les noms en `_` ;
2. les liens `target="_blank"`, ouverts par `webbrowser.open(url)` sans regarder
   le schéma.

Les tests du pont passent par le VRAI `webview.util.js_bridge_call` : une mise à
jour de pywebview qui changerait la résolution des noms doit échouer ici.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
import webview
import webview.util

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop import pywebview_main as shell  # noqa: E402


class _SyncThread:
    """`js_bridge_call` exécute l'appel dans un Thread : synchrone ici, pour
    constater ce qui a tourné sans attente arbitraire."""

    def __init__(self, target, args=(), **_kwargs):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


@pytest.fixture
def shell_window(monkeypatch):
    """La fenêtre telle que la coque la crée. Sans GUI : `create_window` ne fait
    qu'enregistrer un objet `Window`, rien n'est affiché avant `webview.start()`."""
    api = shell.NativeApi()
    window = shell._create_window("http://127.0.0.1:8756/", api)
    # Au démarrage, `Window._initialize()` pose sur `window.gui` le module de
    # plateforme (cocoa, edgechromium…), qui importe `os`. On le simule.
    executed: list = []
    window.gui = types.SimpleNamespace(os=types.SimpleNamespace(system=lambda *a: executed.append(a)))
    # Tout appel résolu par le pont se termine par un `evaluate_js` (valeur de
    # retour ou erreur renvoyée au JS) : c'est ce qui le rend observable.
    returned: list[str] = []
    monkeypatch.setattr(window, "evaluate_js", lambda script, *_a, **_k: returned.append(script))
    monkeypatch.setattr(webview.util, "Thread", _SyncThread)
    try:
        yield window, executed, returned
    finally:
        webview.windows.remove(window)


def test_only_pick_pdf_is_exposed(shell_window):
    window, _executed, _returned = shell_window
    assert window._js_api is None
    assert set(window._functions) == {"pick_pdf"}


def test_pick_pdf_reaches_python(shell_window, monkeypatch):
    """Témoin : le harnais voit bien un appel qui aboutit."""
    window, _executed, returned = shell_window
    monkeypatch.setattr(window, "create_file_dialog", lambda *_a, **_k: ["/tmp/cours.pdf"])

    webview.util.js_bridge_call(window, "pick_pdf", [], "1")

    assert len(returned) == 1 and "/tmp/cours.pdf" in returned[0]


@pytest.mark.parametrize("name", [
    "window.gui.os.system",                      # exécution de commande
    "window.load_url",
    "window.evaluate_js",
    "pick_pdf.__self__.window.gui.os.system",    # remonter depuis la fonction exposée
    "pick_pdf.__func__.__globals__.update",      # réécrire les globales de la coque
    "open_releases_page",                        # méthodes du menu : Python seulement
    "navigate",
])
def test_bridge_cannot_reach_past_the_exposed_functions(shell_window, name):
    window, executed, returned = shell_window

    webview.util.js_bridge_call(window, name, ["open -a Calculator"], "1")

    assert executed == []
    assert returned == [], f"{name} a été résolu et appelé depuis le JS"


def test_external_links_open_only_web_urls(monkeypatch):
    import webbrowser

    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url, new=0, autoraise=True: opened.append(url) or True)
    shell._guard_external_links()
    shell._guard_external_links()  # idempotent : pas de double emballage

    for hostile in (
        "file:///Applications/Calculator.app",
        "x-apple.systempreferences:com.apple.preference.security",
        "vscode://file/etc/passwd",
        "javascript:alert(1)",
        "//evil.test/x",
        "https://",
    ):
        assert webbrowser.open(hostile) is False, hostile

    assert webbrowser.open(shell.RELEASES_PAGE) is True
    assert webbrowser.open("https://doi.org/10.1037/a0012345", 2, True) is True
    assert opened == [shell.RELEASES_PAGE, "https://doi.org/10.1037/a0012345"]
