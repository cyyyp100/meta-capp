# services/secrets_store.py — Coffre à secrets (S8, socle P2).
#
# Règle : un secret ne vit JAMAIS en DB, ni en settings, ni en
# logs. Stockage : **keychain OS** via `keyring` ; repli fichier 0600 dans le
# dossier de données si aucun backend keychain n'est disponible (Linux headless).
# Toute valeur lue/écrite est enregistrée auprès du filtre de logs qui la masque.
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from config.settings import DB_PATH

logger = logging.getLogger("services.secrets")

KEYRING_SERVICE = "Meta-Capp"
_FALLBACK_FILENAME = "secrets.json"

# Valeurs sensibles connues du process : le filtre de logs les caviarde.
_known_secrets: set[str] = set()


def mask(value: str | None) -> str:
    """Représentation loggable d'un secret : `ab…yz` (jamais la valeur)."""
    if not value:
        return "∅"
    if len(value) <= 6:
        return "•••"
    return f"{value[:2]}…{value[-2:]}"


class RedactSecretsFilter(logging.Filter):
    """Caviarde toute occurrence d'un secret connu dans les messages de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        if _known_secrets:
            try:
                message = record.getMessage()
            except Exception:
                return True
            redacted = message
            for secret in _known_secrets:
                if secret in redacted:
                    redacted = redacted.replace(secret, "•••REDACTED•••")
            if redacted is not message:
                record.msg = redacted
                record.args = ()
        return True


def _register(value: str | None) -> None:
    if value:
        _known_secrets.add(value)


def _fallback_path() -> Path:
    return Path(DB_PATH).parent / _FALLBACK_FILENAME


def _keyring():
    try:
        import keyring
        from keyring.errors import NoKeyringError  # noqa: F401

        # Backend « fail » = pas de keychain utilisable -> repli fichier.
        if keyring.get_keyring().__class__.__module__.endswith("fail"):
            return None
        return keyring
    except Exception:
        return None


def set_secret(name: str, value: str) -> str:
    """Stocke un secret ; renvoie le backend utilisé ('keychain' ou 'file')."""
    _register(value)
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(KEYRING_SERVICE, name, value)
            logger.info("Secret '%s' stocké dans le keychain OS (%s).", name, mask(value))
            return "keychain"
        except Exception as exc:
            logger.warning("Keychain indisponible (%s) : repli fichier.", exc)
    path = _fallback_path()
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    data[name] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - Windows
        pass
    logger.info("Secret '%s' stocké en repli fichier 0600 (%s).", name, mask(value))
    return "file"


def get_secret(name: str) -> str | None:
    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(KEYRING_SERVICE, name)
            if value:
                _register(value)
                return value
        except Exception:
            pass
    path = _fallback_path()
    if path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get(name)
        except (OSError, ValueError):
            value = None
        if value:
            _register(value)
            return value
    return None


def delete_secret(name: str) -> None:
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(KEYRING_SERVICE, name)
        except Exception:
            pass
    path = _fallback_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if name in data:
                del data[name]
                path.write_text(json.dumps(data), encoding="utf-8")
        except (OSError, ValueError):  # pragma: no cover - best-effort
            pass
