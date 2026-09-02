# db/app_settings.py — Accès brut à la table clé/valeur `app_settings`.
#
# La table existe depuis la v25 et n'était lue par personne. C'est le SEUL
# stockage de préférences qui survive à une restauration de sauvegarde : le
# `localStorage` du webview, lui, appartient au navigateur embarqué et n'est pas
# dans le fichier `.db` que l'utilisateur exporte. Tout réglage qu'on ne veut pas
# voir disparaître d'une machine à l'autre passe donc par ici.
#
# Ce module ne connaît QUE des chaînes : la validation, les valeurs par défaut et
# le typage vivent dans `services/preferences.py` (cf. CLAUDE.md — la politique
# n'est pas dans la couche d'accès, et surtout pas dans un routeur).
from __future__ import annotations

import logging

from db import get_connection

logger = logging.getLogger("DB.app_settings")


def get_setting(key: str, default: str | None = None) -> str | None:
    conn = get_connection()
    row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    if row is None or row["value"] is None:
        return default
    return str(row["value"])


def get_settings() -> dict[str, str]:
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    return {str(r["key"]): str(r["value"] or "") for r in rows}


def set_setting(key: str, value: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
    logger.debug("Réglage enregistré : %s", key)


def delete_setting(key: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM app_settings WHERE key=?", (key,))
