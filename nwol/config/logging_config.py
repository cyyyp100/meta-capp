# config/logging_config.py
import logging
import logging.handlers
import pathlib
import sys

from config.settings import LOG_BACKUP_COUNT, LOG_FILE, LOG_MAX_BYTES

# La console montre l'heure ; le fichier, joint aux rapports de bug, la date aussi.
_CONSOLE_FORMAT = ("%(asctime)s [%(levelname)s] [%(name)s] %(message)s", "%H:%M:%S")
_FILE_FORMAT = ("%(asctime)s [%(levelname)s] [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S")


def _formatter(fmt: str, datefmt: str) -> logging.Formatter:
    # S8 : ni secret connu (nonce de lancement) ni chemin du dossier personnel
    # dans une ligne de log — trace d'exception comprise.
    try:
        from services.secrets_store import RedactingFormatter
    except Exception:  # pragma: no cover - services/ absent (outillage isolé)
        return logging.Formatter(fmt, datefmt)
    return RedactingFormatter(fmt, datefmt)


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO

    root = logging.getLogger()
    root.setLevel(level)

    # Idempotent : setup_logging() peut être appelé plusieurs fois dans le même
    # process (main.py puis desktop/pywebview_main.py) — sans ça les handlers
    # s'accumulent et chaque ligne de log est affichée en double.
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(_formatter(*_CONSOLE_FORMAT))
    root.addHandler(console)

    # Fichier avec rotation : c'est lui que « Signaler un problème » exporte.
    try:
        pathlib.Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(_formatter(*_FILE_FORMAT))
        root.addHandler(file_handler)
    except OSError as e:
        logging.warning("Impossible d'ouvrir le fichier de log : %s", e)
