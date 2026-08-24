# services/data_export.py — Sauvegarde / restauration des données utilisateur
# (priorité 4.3 du plan : export/import de nwol.db + export des logs, base de
# la portabilité P2). UI-agnostique, comme le reste de services/.
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

import db
from config.settings import ASSETS_DIR, LOG_FILE

logger = logging.getLogger("services.data_export")

SQLITE_MAGIC = b"SQLite format 3\x00"
MAX_IMPORT_BYTES = 512 * 1024 * 1024  # garde-fou grossier (DB locale ~Mo)


def export_db() -> str:
    """Snapshot cohérent de la DB (VACUUM INTO : sûr sous WAL, DB compactée).

    Renvoie le chemin d'un fichier temporaire à servir puis supprimer."""
    conn = db.get_connection()
    dest = Path(tempfile.mkdtemp(prefix="nwol_export_")) / (
        time.strftime("meta-capp-backup-%Y%m%d-%H%M%S") + ".db"
    )
    conn.execute("VACUUM INTO ?", (str(dest),))
    os.chmod(dest, 0o600)
    return str(dest)


def import_db(content: bytes) -> dict:
    """Restaure une sauvegarde : validation stricte puis copie du contenu dans
    la DB vivante via l'API backup (les connexions des autres threads restent
    valides), backup de sécurité de l'existant, et re-migration.

    Lève ValueError si le fichier n'est pas une sauvegarde exploitable."""
    if not content or len(content) > MAX_IMPORT_BYTES:
        raise ValueError("Fichier de sauvegarde vide ou trop volumineux")
    if not content.startswith(SQLITE_MAGIC):
        raise ValueError("Ce fichier n'est pas une base SQLite Meta-Capp")

    tmp = Path(tempfile.mkdtemp(prefix="nwol_import_")) / "candidate.db"
    tmp.write_bytes(content)
    try:
        src = sqlite3.connect(str(tmp))
        try:
            ok = src.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok":
                raise ValueError("Sauvegarde corrompue (integrity_check)")
            has_docs = src.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='documents'"
            ).fetchone()
            if has_docs is None:
                raise ValueError("Sauvegarde invalide (schéma Meta-Capp absent)")

            # Backup de sécurité de la DB actuelle avant remplacement.
            current = db.DB_PATH
            safety = None
            if os.path.isfile(current):
                safety = current + time.strftime(".pre-import-%Y%m%d-%H%M%S")
                shutil.copy2(current, safety)

            target = db.get_connection()
            src.backup(target)
            target.commit()
        finally:
            src.close()
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)

    # La sauvegarde peut venir d'une version antérieure : remonter le schéma.
    from db.schema import initialize_schema

    initialize_schema()
    logger.info("Base restaurée depuis une sauvegarde (backup de sécurité : %s).", safety)
    return {"restored": True, "safety_backup": safety}


def purge_all_data() -> dict:
    """Effacement total (S10/RGPD) : toutes les données personnelles — contenu
    de la base (profil, Q&R, documents, flashcards…), caches de pages et logs.

    On vide table par table plutôt que supprimer le fichier : les connexions
    SQLite des autres threads restent valides. `initialize_schema()` re-seede
    ensuite l'utilisateur par défaut."""
    conn = db.get_connection()
    tables = [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    # SQLite ignore silencieusement `PRAGMA foreign_keys` à l'intérieur d'une
    # transaction : les deux pragmas doivent rester *hors* du `with conn`, sinon
    # la réactivation est un no-op et la connexion (mise en cache par thread et
    # jamais fermée) écrit sans intégrité référentielle pour le reste du process.
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        with conn:
            for table in tables:
                if table != "schema_version":
                    conn.execute(f'DELETE FROM "{table}"')
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("VACUUM")

    shutil.rmtree(ASSETS_DIR, ignore_errors=True)
    log_dir = Path(LOG_FILE).parent
    if log_dir.is_dir():
        for f in log_dir.glob(Path(LOG_FILE).name + "*"):
            try:
                f.unlink()
            except OSError:  # pragma: no cover - log ouvert (Windows)
                pass

    from db.schema import initialize_schema

    initialize_schema()
    logger.info("Effacement total des données effectué (%d tables purgées).", len(tables))
    return {"purged": True, "tables": len(tables)}


def export_logs() -> str | None:
    """Zip des fichiers de logs (rotation comprise) pour partage volontaire
    (support / diagnostic). Renvoie None s'il n'y a aucun log."""
    log_dir = Path(LOG_FILE).parent
    if not log_dir.is_dir():
        return None
    files = sorted(p for p in log_dir.iterdir() if p.is_file() and p.name.startswith(Path(LOG_FILE).name))
    if not files:
        return None
    dest = Path(tempfile.mkdtemp(prefix="nwol_logs_")) / (
        time.strftime("meta-capp-logs-%Y%m%d-%H%M%S") + ".zip"
    )
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f.name)
    os.chmod(dest, 0o600)
    return str(dest)
