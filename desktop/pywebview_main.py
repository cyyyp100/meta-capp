#!/usr/bin/env python3
# desktop/pywebview_main.py — Coque desktop native (pywebview).
#
# Lance le serveur FastAPI local dans un thread démon, attend qu'il réponde,
# puis ouvre une FENÊTRE NATIVE pointant dessus. C'est le mode "logiciel" :
# aucun navigateur, aucune URL visible pour l'utilisateur. Le frontend compilé
# (frontend/dist) est servi par FastAPI lui-même (même origine).
#
# Usage :  python desktop/pywebview_main.py
#          python desktop/pywebview_main.py --server-only   # smoke test headless
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "nwol"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import uvicorn  # noqa: E402
import webview  # noqa: E402
from webview.menu import Menu, MenuAction, MenuSeparator  # noqa: E402

from i18n import t  # noqa: E402
from server import security  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import FRONTEND_DIST, HOST, PORT  # noqa: E402
from services.secrets_store import register_secret  # noqa: E402
from services.updates import RELEASES_PAGE  # noqa: E402

logger = logging.getLogger("desktop")


class NativeApi:
    """Actions natives de la coque : sélecteur de fichier et ponts du menu.

    UNE seule de ces méthodes est joignable depuis le JavaScript : `pick_pdf`,
    publiée par `_create_window`. L'objet n'est jamais passé en `js_api` — voir
    `_create_window` pour la raison. Les autres méthodes ne sont appelées que
    par la barre de menu, côté Python."""

    def __init__(self) -> None:
        self.window = None

    def pick_pdf(self) -> str | None:
        """Ouvre le dialogue fichier natif et renvoie le chemin choisi.

        Accepte les PDF ET les fichiers de code/texte (le backend valide
        réellement le format et refuse les binaires)."""
        if self.window is None:
            return None
        code_glob = (
            "*.py;*.pyw;*.js;*.mjs;*.cjs;*.jsx;*.ts;*.tsx;*.java;*.kt;*.scala;*.c;*.h;"
            "*.cpp;*.cc;*.hpp;*.cs;*.go;*.rs;*.swift;*.rb;*.php;*.pl;*.lua;*.dart;*.sh;"
            "*.bash;*.zsh;*.ps1;*.sql;*.r;*.jl;*.m;*.html;*.htm;*.xml;*.css;*.scss;*.less;"
            "*.vue;*.svelte;*.json;*.yaml;*.yml;*.toml;*.ini;*.cfg;*.md;*.markdown;*.txt;"
            "*.log;*.tf;*.proto;*.gradle;*.clj;*.ex;*.exs;*.hs;*.ml"
        )
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=(
                f"Documents lisibles (*.pdf;{code_glob})",
                "PDF (*.pdf)",
                f"Fichiers de code ({code_glob})",
                "Tous les fichiers (*.*)",
            ),
        )
        if result:
            return result[0] if isinstance(result, (list, tuple)) else str(result)
        return None

    # ── Ponts menu natif → routes React ─────────────────────────────────────
    #
    # La barre de menu vit côté Python, l'application côté JS : le seul lien
    # entre les deux est `evaluate_js`. On pousse la route dans l'historique du
    # navigateur embarqué puis on notifie React — un `location.href = …`
    # rechargerait tout le bundle à chaque clic de menu.

    def navigate(self, route: str) -> None:
        """Pousse une route côté React. Best-effort : la fenêtre peut être fermée."""
        if self.window is None:
            return
        safe = json.dumps(str(route or "/"))
        try:
            self.window.evaluate_js(
                "(function(r){"
                " window.history.pushState({}, '', r);"
                " window.dispatchEvent(new PopStateEvent('popstate'));"
                f"}})({safe});"
            )
        except Exception:  # pragma: no cover - dépend de la coque native
            logger.debug("Navigation menu ignorée : %s", route, exc_info=True)

    def open_document(self) -> None:
        """« Fichier ▸ Ouvrir un document… » : le dialogue natif, puis le lecteur.

        Réutilise `pick_pdf` et le MÊME chemin d'import que la ligne de commande
        (`_open_document`) : le menu n'est qu'un déclencheur, pas une seconde
        implémentation de l'import."""
        path = self.pick_pdf()
        if not path:
            return
        doc_id = _open_document(path)
        self.navigate(f"/reader/{doc_id}" if doc_id else "/")

    def set_theme(self, theme: str) -> None:
        """« Affichage ▸ Thème clair/sombre ».

        Le menu ne pose PAS l'attribut lui-même : il émet un événement que le
        store de thème écoute. Écrire `data-theme` directement laisserait le
        store React sur l'ancienne valeur, et le premier clic sur la bascule de
        la barre latérale reviendrait au thème qu'on vient de quitter."""
        if theme not in ("light", "dark", "system") or self.window is None:
            return
        try:
            self.window.evaluate_js(
                "window.dispatchEvent(new CustomEvent('metacapp:theme',"
                f" {{ detail: {json.dumps(theme)} }}));"
            )
        except Exception:  # pragma: no cover - dépend de la coque native
            logger.debug("Bascule de thème ignorée", exc_info=True)

    def zoom(self, direction: int) -> None:
        """« Affichage ▸ Zoom + / − ». Bornes dures : 70 % à 160 %.

        Sans bornes, quelques clics de trop rendent l'application inutilisable
        et il n'existe aucun raccourci natif pour revenir (`MenuAction` n'a pas
        de raccourci clavier en pywebview 6.2.1)."""
        if self.window is None:
            return
        step = 0.1 if direction > 0 else -0.1
        try:
            self.window.evaluate_js(
                "(function(step){"
                " var root = document.documentElement;"
                " var current = parseFloat(root.style.zoom || '1') || 1;"
                " root.style.zoom = String(Math.min(1.6, Math.max(0.7, current + step)));"
                f"}})({step});"
            )
        except Exception:  # pragma: no cover - dépend de la coque native
            logger.debug("Zoom ignoré", exc_info=True)

    def toggle_fullscreen(self) -> None:
        if self.window is None:
            return
        try:
            self.window.toggle_fullscreen()
        except Exception:  # pragma: no cover - dépend de la coque native
            logger.debug("Plein écran ignoré", exc_info=True)

    def start_tour(self) -> None:
        """« Aide ▸ Tutoriel » : rejoue la visite guidée du premier lancement.

        Deux gestes, dans cet ordre : on ramène l'accueil (la première bulle
        s'ancre sur son bouton d'import), PUIS on émet l'événement. Le menu ne
        remet pas les préférences à zéro lui-même — il le demande au store, qui
        est le seul à savoir ce qu'une visite « recommencée » veut dire
        (`frontend/src/features/tour/useTour.ts`)."""
        if self.window is None:
            return
        self.navigate("/")
        try:
            self.window.evaluate_js(
                "window.dispatchEvent(new CustomEvent('metacapp:tour'));"
            )
        except Exception:  # pragma: no cover - dépend de la coque native
            logger.debug("Relance de la visite ignorée", exc_info=True)

    def open_releases_page(self) -> None:
        """Ouvre la page de téléchargement — l'URL EN DUR, jamais une URL reçue.

        Voir `services/updates.py` : sur macOS, `webbrowser.open()` passe par
        `open(1)`, qui honore `file://` et les schémas d'application. Une URL
        issue d'une réponse réseau y serait une primitive d'exécution locale."""
        import webbrowser

        webbrowser.open(RELEASES_PAGE)


def _build_menu(api: NativeApi) -> list[Menu]:
    """Barre de menu native (pywebview 6.2.1).

    Deux limites assumées, pas contournées :

    - `MenuAction` n'a PAS de raccourci clavier en 6.2.1 (le `# TODO` est dans
      `webview/menu.py`). ⌘O et ⌘, sont donc gérés par un `keydown` global côté
      React (`frontend/src/features/shell/useAppShortcuts.ts`) — un seul endroit
      les déclare, et c'est celui-là.
    - Le menu est construit AVANT tout changement de langue en cours de session :
      ses libellés restent dans la langue du démarrage. Les Réglages le disent
      (`settings.menu_lang_note`) plutôt que de laisser croire à un bug."""
    return [
        Menu(t("menu.file"), [
            MenuAction(t("menu.open_pdf"), api.open_document),
            MenuAction(t("menu.library"), lambda: api.navigate("/")),
            MenuSeparator(),
            MenuAction(t("menu.settings"), lambda: api.navigate("/settings")),
        ]),
        Menu(t("menu.view"), [
            MenuAction(t("menu.zoom_in"), lambda: api.zoom(1)),
            MenuAction(t("menu.zoom_out"), lambda: api.zoom(-1)),
            MenuSeparator(),
            MenuAction(t("menu.theme_light"), lambda: api.set_theme("light")),
            MenuAction(t("menu.theme_dark"), lambda: api.set_theme("dark")),
            MenuSeparator(),
            MenuAction(t("menu.fullscreen"), api.toggle_fullscreen),
        ]),
        Menu(t("menu.help"), [
            MenuAction(t("menu.tutorial"), api.start_tour),
            MenuAction(t("menu.report_issue"), lambda: api.navigate("/settings/help")),
            MenuAction(t("menu.rate"), api.open_releases_page),
            MenuAction(t("menu.check_updates"), lambda: api.navigate("/settings/updates")),
            MenuSeparator(),
            MenuAction(t("menu.about"), lambda: api.navigate("/settings/about")),
        ]),
    ]


def _create_window(start_url: str, api: NativeApi):
    """Fenêtre principale — et la liste EXHAUSTIVE de ce que le JS peut appeler.

    pywebview 6.2.1 résout un appel venu du JavaScript par une chaîne de
    `getattr` sur l'objet `js_api` (`webview/util.py:js_bridge_call`), sans
    écarter les noms en `_` ni vérifier la liste qu'il a lui-même publiée.
    Passer `NativeApi` en `js_api` rendait donc joignable tout ce qu'on atteint
    par attributs depuis lui : `window.gui` est le module de plateforme, qui
    importe `os`, et `pywebview._bridge.call("window.gui.os.system", [...])`
    était une exécution de commande offerte à n'importe quel script injecté dans
    la page. Une fonction passée à `window.expose` est cherchée par nom EXACT
    dans un dict : aucune traversée possible.

    Le frontend n'appelle que `pick_pdf` (`frontend/src/api/platform.ts`). Tout
    ajout ici élargit la surface native atteignable depuis le webview :
    `tests/test_desktop_bridge.py` fige la liste."""
    window = webview.create_window("Meta-Capp", start_url, width=1280, height=860)
    window.expose(api.pick_pdf)
    api.window = window
    return window


_WEB_SCHEMES = ("https", "http")


def _is_web_url(url: object) -> bool:
    try:
        parts = urllib.parse.urlsplit(str(url))
    except ValueError:
        return False
    return parts.scheme.lower() in _WEB_SCHEMES and bool(parts.hostname)


def _guard_external_links() -> None:
    """N'ouvre dans le navigateur système QUE des URL web.

    pywebview 6.2.1 ouvre tout lien `target="_blank"` du webview par
    `webbrowser.open(url)` sans regarder le schéma (`platforms/cocoa.py`,
    `platforms/edgechromium.py`). Sur macOS, `webbrowser.open()` passe par
    `open(1)`, qui honore `file://` et les schémas d'application : un lien
    injecté dans la page devenait, au premier clic, l'exécution locale que
    `services/updates.py` s'interdit. Le garde est posé sur `webbrowser.open`
    lui-même, par où passent les deux coques ET `open_releases_page`."""
    import webbrowser

    if getattr(webbrowser.open, "_metacapp_guard", False):
        return
    unguarded = webbrowser.open

    def guarded_open(url, new=0, autoraise=True):
        if not _is_web_url(url):
            logger.warning("Ouverture externe refusée (schéma non web) : %.80r", url)
            return False
        return unguarded(url, new, autoraise)

    guarded_open._metacapp_guard = True
    webbrowser.open = guarded_open


def _serve(holder: dict) -> None:
    config = uvicorn.Config(create_app(), host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    holder["server"] = server
    server.run()


def _wait_until_ready(timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://{HOST}:{PORT}/api/health", timeout=0.5)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def _open_document(path: str) -> int | None:
    """Importe un document passé en ligne de commande. Renvoie son id."""
    from services import code_reader
    from services.orchestrator import import_code, import_pdf

    try:
        if path.lower().endswith(".pdf"):
            doc = import_pdf(path)
        elif code_reader.is_code_file(path):
            doc = import_code(path)
        else:
            logger.error("Format non pris en charge : %s", path)
            return None
        return int(doc.get("id")) if doc else None
    except Exception:
        logger.exception("Import impossible : %s", path)
        return None


# Ce qui, modifié, périme `frontend/dist`. `vite.config.ts` et les manifestes en
# font partie : changer un alias ou une dépendance change le bundle sans qu'un
# seul `.tsx` ait bougé.
_FRONTEND_SOURCES = ("src", "index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json")


def _newest_mtime(path: Path) -> float:
    """Date de la modification la plus récente sous `path` (0.0 s'il n'existe pas)."""
    if not path.exists():
        return 0.0
    if path.is_file():
        return path.stat().st_mtime
    newest = 0.0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                newest = max(newest, child.stat().st_mtime)
        except OSError:
            continue
    return newest


def _build_frontend_if_needed() -> None:
    """Compile le frontend s'il manque — OU s'il date d'avant ses sources.

    La condition ne portait que sur l'ABSENCE du bundle. Un `dist/` présent mais
    périmé était donc servi tel quel : on relançait l'application après avoir
    corrigé un composant et on regardait, sans le savoir, le bundle de la veille
    — puis on cherchait le bug dans la correction. Une compilation incrémentale
    coûte quelques centaines de millisecondes ; ce quiproquo-là coûte une heure.

    En mode gelé, `frontend/` n'est pas embarqué : rien à comparer, rien à faire.
    """
    frontend = ROOT / "frontend"
    if getattr(sys, "frozen", False) or not frontend.is_dir():
        return

    has_dist = FRONTEND_DIST.is_dir()
    if has_dist:
        built = _newest_mtime(FRONTEND_DIST)
        sources = max(_newest_mtime(frontend / name) for name in _FRONTEND_SOURCES)
        if sources <= built:
            return
        logger.info("Frontend périmé — recompilation (npm run build)…")
    else:
        logger.info("Frontend non compilé — build automatique (npm run build)…")

    import subprocess

    try:
        subprocess.run(["npm", "run", "build"], cwd=str(frontend), check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.error(
            "Build du frontend impossible (%s). Lance manuellement :\n"
            "    cd frontend && npm install && npm run build",
            exc,
        )
        # Sans bundle du tout il n'y a pas d'application à montrer ; avec un
        # bundle périmé, l'ancien vaut mieux que rien.
        if not has_dist:
            sys.exit(1)


def main(pdf_path: str | None = None, debug: bool = False) -> None:
    # Logging fichier + console (rotation) : indispensable en app packagée pour
    # que « Exporter les logs » ait de la matière (diagnostic sur consentement).
    from config.logging_config import setup_logging

    setup_logging(debug=debug)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--server-only",
        action="store_true",
        help="Serveur seul, sans fenêtre native (smoke test CI / usage headless)",
    )
    # parse_known_args : lancé directement, argv peut contenir les options de
    # main.py (--debug, pdf) — elles sont déjà traitées par l'appelant.
    args, _ = parser.parse_known_args()

    if args.server_only:
        # Mode smoke test : uvicorn au premier plan, pas de webview (pas d'écran
        # en CI). La CI vérifie ensuite /api/health puis tue le process.
        import uvicorn

        uvicorn.run(create_app(), host=HOST, port=PORT, log_level="info")
        return

    _build_frontend_if_needed()

    # S1 : nonce de lancement — généré ici, exigé par l'API/WS, transmis au
    # frontend via l'URL d'ouverture (il le pose en cookie SameSite=Strict).
    launch_token = security.new_launch_token()
    security.set_launch_token(launch_token)
    # L'URL d'ouverture le porte en clair et pywebview la journalise en --debug :
    # les logs sont exportables (« Exporter les logs »), le nonce n'y va pas.
    register_secret(launch_token)

    holder: dict = {}
    threading.Thread(target=_serve, args=(holder,), daemon=True).start()

    if not _wait_until_ready():
        logger.error("Le serveur local n'a pas démarré à temps.")
        sys.exit(1)

    # Document passé en argument : importé côté serveur, puis ouvert directement
    # dans le lecteur (deep-link) plutôt que sur l'accueil.
    start_url = f"http://{HOST}:{PORT}/?lt={launch_token}"
    if pdf_path:
        doc_id = _open_document(pdf_path)
        if doc_id:
            start_url = f"http://{HOST}:{PORT}/reader/{doc_id}?lt={launch_token}"

    _guard_external_links()
    api = NativeApi()
    _create_window(start_url, api)
    # La langue du menu est celle qu'a restaurée le lifespan du serveur : le
    # menu est construit APRÈS `_wait_until_ready()`, donc après cette
    # restauration. Sans cet ordre, le menu serait toujours en français.
    webview.start(menu=_build_menu(api))  # bloque sur le thread principal (macOS)

    server = holder.get("server")
    if server is not None:
        server.should_exit = True


if __name__ == "__main__":
    main()
