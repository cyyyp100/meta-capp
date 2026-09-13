# utils/text.py — Primitives de comparaison textuelle partagées.
#
# Le repli d'accents avait été réécrit dans chaque module qui en avait besoin
# (recherche brainstorming, cartes de langue, recherche de bibliothèque). Deux
# implémentations divergentes du même « est-ce que ces deux textes sont le même
# mot ? » donnent deux résultats de recherche différents pour la même requête.
from __future__ import annotations

import hashlib
import unicodedata


def fold(text: str) -> str:
    """Minuscule + suppression des accents (comparaison robuste).

    « Équations » et « equations » doivent être le même mot pour une recherche.
    """
    decomposed = unicodedata.normalize("NFKD", (text or "").strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def fingerprint(*parts: str) -> str:
    """Empreinte stable de textes comparés « au sens », pas à l'octet.

    Chaque partie est pliée (`fold`) et ses blancs sont réduits à un espace :
    « Qu'est-ce que  l'ADN ? » et « qu'est-ce que l'adn ? » donnent la même
    empreinte. Sert de clé de doublon en base (flashcards) : deux clics sur le
    même « + Flashcard », ou la même carte tapée deux fois, n'en font qu'une.
    """
    joined = "\x1f".join(" ".join(fold(part).split()) for part in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()
