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
# Copie de la base prise juste avant une restauration : `nwol.db.pre-import-…`.
SAFETY_BACKUP_MARK = ".pre-import-"


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

            # Copie de sécurité de la base actuelle avant remplacement. VACUUM
            # INTO et non une copie du fichier : en WAL, les dernières écritures
            # vivent dans `nwol.db-wal` tant qu'aucun point de contrôle ne les a
            # reversées — copier `nwol.db` seul donnait une base ancienne, voire
            # vide. Une seule copie est gardée, celle d'avant la DERNIÈRE
            # restauration : chacune est un double complet des données de
            # l'étudiant, et « Tout effacer » les retire aussi.
            target = db.get_connection()
            safety = None
            if os.path.isfile(db.DB_PATH):
                _discard_safety_backups()
                safety = db.DB_PATH + time.strftime(SAFETY_BACKUP_MARK + "%Y%m%d-%H%M%S")
                target.execute("VACUUM INTO ?", (safety,))
                os.chmod(safety, 0o600)

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
    # En WAL, l'ancien contenu reste dans `nwol.db` jusqu'au prochain point de
    # contrôle : on le force, journal tronqué, pour que l'effacement soit fait
    # sur le disque et pas seulement aux yeux de SQLite.
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    _discard_safety_backups()

    shutil.rmtree(ASSETS_DIR, ignore_errors=True)
    # Copies des documents envoyés depuis le navigateur : des données de
    # l'étudiant comme les autres (les fichiers ouverts par chemin ne sont
    # jamais à nous, on n'y touche pas).
    from services import uploads

    uploads.discard_all()
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


def _discard_safety_backups() -> None:
    """Efface les copies de sécurité laissées par `import_db`."""
    current = Path(db.DB_PATH)
    for path in current.parent.glob(current.name + SAFETY_BACKUP_MARK + "*"):
        try:
            path.unlink()
        except OSError:  # pragma: no cover - fichier verrouillé (Windows)
            logger.warning("Copie de sécurité non effacée : %s", path.name)


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
