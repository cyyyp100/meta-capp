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
from services.updates import RELEASES_PAGE  # noqa: E402

logger = logging.getLogger("desktop")


class NativeApi:
    """API native exposée au frontend via window.pywebview.api.*"""

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

    if not FRONTEND_DIST.is_dir():
        logger.info("Frontend non compilé — build automatique (npm run build)…")
        import subprocess

        try:
            subprocess.run(["npm", "run", "build"], cwd=str(ROOT / "frontend"), check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            logger.error(
                "Build du frontend impossible (%s). Lance manuellement :\n"
                "    cd frontend && npm install && npm run build",
                exc,
            )
            sys.exit(1)

    # S1 : nonce de lancement — généré ici, exigé par l'API/WS, transmis au
    # frontend via l'URL d'ouverture (il le pose en cookie SameSite=Strict).
    launch_token = security.new_launch_token()
    security.set_launch_token(launch_token)

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

    api = NativeApi()
    window = webview.create_window(
        "Meta-Capp",
        start_url,
        js_api=api,
        width=1280,
        height=860,
    )
    api.window = window
    # La langue du menu est celle qu'a restaurée le lifespan du serveur : le
    # menu est construit APRÈS `_wait_until_ready()`, donc après cette
    # restauration. Sans cet ordre, le menu serait toujours en français.
    webview.start(menu=_build_menu(api))  # bloque sur le thread principal (macOS)

    server = holder.get("server")
    if server is not None:
        server.should_exit = True


if __name__ == "__main__":
    main()
