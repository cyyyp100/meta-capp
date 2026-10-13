# server/routers/llm.py — État de Clikoda (le modèle local), en lecture seule.
#
# Volontairement PAS dans `/api/health` : cette sonde-là est interrogée en
# boucle par la coque desktop AVANT l'ouverture de la fenêtre
# (`desktop/pywebview_main.py`). Y mettre un service tiers — Ollama, trois
# secondes de timeout, souvent éteint — placerait un processus qu'on ne contrôle
# pas sur le chemin critique du démarrage. Deux durées de vie, deux endpoints.
#
# AUCUNE entrée : le modèle se choisit par `POST /api/preferences`, et nulle part
# ailleurs. Deux chemins d'écriture pour un même réglage, c'est exactement la
# duplication que CLAUDE.md décrit. Aucun bouton « installer », non plus : un
# `ollama pull` lancé par l'application serait un téléchargement réseau, et cette
# édition n'a qu'un seul appel sortant (`services/updates.py`, opt-in). On donne
# la commande à copier, l'utilisateur la lance s'il veut.
from __future__ import annotations

from fastapi import APIRouter

from services.llm_models import refresh_active
from services.orchestrator import llm_status

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/status")
def status() -> dict:
    """Ollama répond-il, quel modèle tourne, tient-il dans cette machine.

    `refresh_active()` d'abord : c'est l'appel que l'interface refait juste après
    avoir écrit le réglage du modèle, donc l'endroit explicite où le changement
    est journalisé et le nouveau modèle calibré. Puis la lecture, servie par le
    catalogue que le rafraîchissement vient de mettre en cache — un seul
    aller-retour vers Ollama.

    Ne lève jamais : Ollama éteint est un état, pas une panne de l'API."""
    refresh_active()
    return llm_status()
