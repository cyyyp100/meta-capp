# server/routers/about.py — « À propos » : les mentions des licences tierces.
#
# Aucune entrée : le chemin du fichier est fixé par `services/about.py`, jamais
# par la requête. Derrière `LocalOnlyGuard` + nonce, comme le reste de l'API.
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from services.about import third_party_notices

router = APIRouter(prefix="/about", tags=["about"])


@router.get("/notices", response_class=PlainTextResponse)
def notices() -> str:
    text = third_party_notices()
    if text is None:
        raise HTTPException(status_code=404, detail="notices not generated")
    return text
