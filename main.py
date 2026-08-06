#!/usr/bin/env python3
# main.py — Point d'entrée MetaC-App
import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
APP_DIR = ROOT_DIR / "nwol"


def _configure_runtime_cache_dirs() -> None:
    cache_root = Path(tempfile.gettempdir()) / "nwol_matplotlib"
    try:
        config_dir = cache_root / "config"
        xdg_cache = cache_root / "cache"
        config_dir.mkdir(parents=True, exist_ok=True)
        xdg_cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(config_dir))
        os.environ.setdefault("XDG_CACHE_HOME", str(xdg_cache))
    except OSError:
        pass


def _reexec_inside_nwol_conda_env() -> None:
    if os.environ.get("NWOL_DISABLE_CONDA_REEXEC") == "1":
        return
    if os.environ.get("NWOL_CONDA_REEXECED") == "1":
        return
    if os.environ.get("CONDA_DEFAULT_ENV") != "nwol":
        return

    conda_prefix = os.environ.get("CONDA_PREFIX")
    if not conda_prefix:
        return

    target = Path(conda_prefix) / "bin" / "python"
    if not target.exists():
        return

    try:
        current = Path(sys.executable).resolve()
        expected = target.resolve()
    except OSError:
        return

    if current == expected:
        return

    os.environ["NWOL_CONDA_REEXECED"] = "1"
    os.execv(str(expected), [str(expected), *sys.argv])


_configure_runtime_cache_dirs()
_reexec_inside_nwol_conda_env()

# Le code applicatif utilise des imports internes absolus (config, ui, db, etc.).
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from config.logging_config import setup_logging


def main():
    parser = argparse.ArgumentParser(description="MetaC-App — Compagnon d'apprentissage adaptatif")
    parser.add_argument("--debug", action="store_true", help="Activer les logs DEBUG")
    parser.add_argument("--web", action="store_true", help="Lancer la nouvelle UI web dans une fenêtre native (pywebview)")
    parser.add_argument("pdf", nargs="?", help="Ouvrir directement un fichier PDF")
    args = parser.parse_args()

    setup_logging(debug=args.debug)

    logger = logging.getLogger("main")

    # Nouvelle UI (refonte) : fenêtre native pywebview + serveur FastAPI local.
    if args.web:
        logger.info("Démarrage MetaC-App (UI web) v1.3")
        from desktop.pywebview_main import main as run_web

        run_web()
        return

    logger.info("Démarrage MetaC-App v1.3")

    from ui.app import NWoLApp

    app = NWoLApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)

    # Ouverture directe si un fichier est passé en argument
    if args.pdf:
        pdf_path = str(Path(args.pdf).resolve())
        app.after(200, lambda: app.open_pdf_path(pdf_path))

    app.mainloop()


if __name__ == "__main__":
    main()
