# utils/text.py — Primitives de comparaison textuelle partagées.
#
# Le repli d'accents avait été réécrit dans chaque module qui en avait besoin
# (recherche brainstorming, cartes de langue, recherche de bibliothèque). Deux
# implémentations divergentes du même « est-ce que ces deux textes sont le même
# mot ? » donnent deux résultats de recherche différents pour la même requête.
from __future__ import annotations

import unicodedata


def fold(text: str) -> str:
    """Minuscule + suppression des accents (comparaison robuste).

    « Équations » et « equations » doivent être le même mot pour une recherche.
    """
    decomposed = unicodedata.normalize("NFKD", (text or "").strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))
