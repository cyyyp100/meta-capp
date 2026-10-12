# services/secrets_store.py — Caviardage des journaux (S8).
#
# Cette édition est 100 % locale : aucune clé d'API, aucun jeton, aucun compte.
# Mais les journaux sont exportables (« Signaler un problème ») et finissent
# joints à un rapport de bug, parfois public. Deux choses n'y entrent donc
# jamais en clair :
#   - une valeur secrète connue du process : le nonce de lancement, que
#     pywebview journalise avec l'URL d'ouverture en --debug ;
#   - le chemin du dossier personnel, qui porte le nom de la session
#     (`/Users/prénom/…`, `C:\Users\prénom\…`) : il devient `~`.
# Le caviardage porte sur la ligne FORMATÉE, trace d'exception comprise : un
# filtre ne voit que le message, et une trace cite les chemins des fichiers.
from __future__ import annotations

import logging
from pathlib import Path

REDACTED = "•••REDACTED•••"

# Valeurs sensibles connues du process : le formateur les caviarde.
_known_secrets: set[str] = set()
# `/` (compte root, environnement dégradé) ne veut rien dire : on ne remplace pas.
_HOME = str(Path.home())


def register_secret(value: str | None) -> None:
    """Déclare une valeur à masquer dans tous les logs ultérieurs."""
    if value:
        _known_secrets.add(value)


def redact(text: str) -> str:
    """Le texte sans les secrets connus ni le chemin du dossier personnel."""
    for secret in _known_secrets:
        text = text.replace(secret, REDACTED)
    if len(_HOME) > 1:
        text = text.replace(_HOME, "~")
    return text


class RedactingFormatter(logging.Formatter):
    """Formateur des handlers de l'application : caviarde la ligne entière."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))
