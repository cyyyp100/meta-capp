# db/__init__.py — Connexion SQLite par thread (threading.local)
import os
import sqlite3
import logging
import threading
from pathlib import Path
from config.settings import DB_PATH

logger = logging.getLogger("DB")
_local = threading.local()


def get_connection() -> sqlite3.Connection:
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        # Sous le threadpool FastAPI, plusieurs threads peuvent écrire : on attend
        # jusqu'à 5 s qu'un verrou se libère plutôt que de lever SQLITE_BUSY
        # (« database is locked ») immédiatement.
        conn.execute("PRAGMA busy_timeout=5000")
        _harden_db_files()
        _local.conn = conn
        logger.info("Connexion SQLite ouverte (thread=%s) : %s", threading.current_thread().name, DB_PATH)
    return conn


def _harden_db_files() -> None:
    """S7 : la DB contient le profil psychométrique et les Q&R de l'utilisateur
    -> lecture/écriture propriétaire uniquement (no-op silencieux sous Windows)."""
    for suffix in ("", "-wal", "-shm"):
        try:
            os.chmod(DB_PATH + suffix, 0o600)
        except OSError:
            pass


def close_connection() -> None:
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn:
        conn.close()
        _local.conn = None
        logger.info("Connexion SQLite fermée (thread=%s).", threading.current_thread().name)
