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

from server import security  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import FRONTEND_DIST, HOST, PORT  # noqa: E402

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


def main() -> None:
    # Logging fichier + console (rotation) : indispensable en app packagée pour
    # que « Exporter les logs » ait de la matière (diagnostic sur consentement).
    from config.logging_config import setup_logging

    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--server-only",
        action="store_true",
        help="Serveur seul, sans fenêtre native (smoke test CI / usage headless)",
    )
    # parse_known_args : quand on arrive ici via `python main.py --web`, argv
    # contient encore les options de main.py (--web, --debug, pdf) — les ignorer.
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

    api = NativeApi()
    window = webview.create_window(
        "Meta-Capp",
        f"http://{HOST}:{PORT}/?lt={launch_token}",
        js_api=api,
        width=1280,
        height=860,
    )
    api.window = window
    webview.start()  # bloque sur le thread principal (requis sous macOS)

    server = holder.get("server")
    if server is not None:
        server.should_exit = True


if __name__ == "__main__":
    main()
