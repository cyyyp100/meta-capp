# services/about.py — Ce que « Réglages ▸ À propos » montre en plus de la version.
#
# Les mentions des licences tierces (`scripts/third_party_notices.py`) sont
# embarquées dans chaque binaire publié : les licences MIT, BSD et Apache des
# dépendances exigent que leur texte accompagne le logiciel, et un fichier que
# personne ne peut ouvrir depuis l'app ne le montre qu'à moitié. On le lit tel
# quel, sans rien y ajouter.
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["NOTICES_PATH", "third_party_notices"]

# Même motif que `server/config.py` pour `FRONTEND_DIST` : la spec PyInstaller
# dépose le fichier à la racine de _MEIPASS ; en développement, il est à la
# racine du dépôt (généré par le script, ignoré par git).
if getattr(sys, "frozen", False):
    NOTICES_PATH = Path(getattr(sys, "_MEIPASS", ".")) / "THIRD_PARTY_NOTICES.txt"
else:
    NOTICES_PATH = Path(__file__).resolve().parents[2] / "THIRD_PARTY_NOTICES.txt"


def third_party_notices() -> str | None:
    """Le texte des mentions, ou None s'il n'a pas été généré (checkout de dev).

    None n'est pas une erreur : la release le génère toujours, un développeur
    seulement s'il lance le script."""
    try:
        return NOTICES_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("Mentions des licences tierces illisibles : %s", exc)
        return None
