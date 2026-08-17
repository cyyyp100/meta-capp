# services/secrets_store.py — Caviardage des secrets dans les logs (S8).
#
# Cette édition est 100 % locale : aucune clé d'API, aucun jeton, aucun compte.
# Il n'y a donc rien à stocker — mais les logs sont exportables par
# l'utilisateur (« Exporter les logs »), et une valeur sensible qui transiterait
# par un message de log ne doit jamais s'y retrouver en clair. On garde donc le
# filtre, branché dans `config/logging_config.py`.
from __future__ import annotations

import logging

logger = logging.getLogger("services.secrets")

# Valeurs sensibles connues du process : le filtre de logs les caviarde.
_known_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Déclare une valeur à masquer dans tous les logs ultérieurs."""
    if value:
        _known_secrets.add(value)


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
