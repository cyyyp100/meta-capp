# config/logging_config.py
import logging
import logging.handlers
import sys
from config.settings import LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    fmt = "[%(levelname)s] [%(name)s] %(message)s"
    datefmt = "%H:%M:%S"

    root = logging.getLogger()
    root.setLevel(level)

    # Idempotent : setup_logging() peut être appelé plusieurs fois dans le même
    # process (main.py puis desktop/pywebview_main.py) — sans ça les handlers
    # s'accumulent et chaque ligne de log est affichée en double.
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()

    # S8 : caviarde toute valeur secrète connue (clés API…) dans les logs.
    try:
        from services.secrets_store import RedactSecretsFilter

        redact = RedactSecretsFilter()
    except Exception:  # pragma: no cover - services/ absent (outillage isolé)
        redact = None

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter(fmt, datefmt))
    if redact is not None:
        ch.addFilter(redact)
    root.addHandler(ch)

    # File handler with rotation
    try:
        import pathlib
        pathlib.Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(fmt, datefmt))
        if redact is not None:
            fh.addFilter(redact)
        root.addHandler(fh)
    except OSError as e:
        logging.warning(f"Impossible d'ouvrir le fichier de log : {e}")
