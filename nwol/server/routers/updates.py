# server/routers/updates.py — Vérification de mise à jour (opt-in).
#
# AUCUN paramètre d'entrée, volontairement : ni URL, ni hôte, ni version. Un
# endpoint local qui accepterait une URL serait un SSRF joignable par n'importe
# quel processus de la machine.
#
# Il N'EST PAS dans `security.TOKEN_EXEMPT_PATHS` : comme le reste de l'API, il
# reste derrière `LocalOnlyGuard` et exige le nonce de lancement.
from __future__ import annotations

from fastapi import APIRouter

from services.updates import check_for_update

router = APIRouter(prefix="/updates", tags=["updates"])


@router.get("/check")
def check() -> dict:
    """État de mise à jour, ou un état neutre si l'option est coupée / GitHub muet.

    Ne renvoie jamais d'erreur : une panne de vérification n'est pas un
    événement pour l'utilisateur (cf. `services/updates.check_for_update`)."""
    return check_for_update()
