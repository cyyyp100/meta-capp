#!/usr/bin/env python3
# main.py — Point d'entrée Meta-Capp.
#
# L'application est une fenêtre native (pywebview) qui affiche le frontend React
# servi par un serveur FastAPI local. C'est le SEUL mode : l'ancienne UI Tkinter
# a été retirée après portage complet de ses comportements dans `nwol/services/`.
import argparse
import logging
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
APP_DIR = ROOT_DIR / "nwol"


def _reexec_inside_nwol_conda_env() -> None:
    """Re-exécute dans l'interpréteur de l'env conda `nwol` si besoin.

    `conda activate nwol` ne suffit pas toujours à ce que `python` pointe sur le
    bon interpréteur (alias shell, IDE). On force celui de l'env, qui porte les
    dépendances natives (PyMuPDF, pywebview)."""
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


_reexec_inside_nwol_conda_env()

# Le code applicatif utilise des imports internes absolus (config, db, services…).
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from config.logging_config import setup_logging  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Meta-Capp — Compagnon d'apprentissage adaptatif")
    parser.add_argument("--debug", action="store_true", help="Activer les logs DEBUG")
    parser.add_argument("pdf", nargs="?", help="Ouvrir directement un PDF ou un fichier de code")
    # Conservé pour ne pas casser les scripts existants : le mode web est le seul.
    parser.add_argument("--web", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    setup_logging(debug=args.debug)
    logger = logging.getLogger("main")
    if args.web:
        logger.debug("--web est désormais implicite (l'UI web est le seul mode).")

    logger.info("Démarrage Meta-Capp v1.3")

    from desktop.pywebview_main import main as run_web

    run_web(pdf_path=str(Path(args.pdf).resolve()) if args.pdf else None, debug=args.debug)


if __name__ == "__main__":
    main()
