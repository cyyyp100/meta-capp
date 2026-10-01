# server/routers/shell.py — La coque vue du frontend : mode navigateur, présence, Quitter.
#
# Toute la politique vit dans `services/lifecycle.py`. AUCUNE entrée sur ces
# trois routes, et elles restent derrière `LocalOnlyGuard` + nonce, comme le
# reste de l'API (WebSocket compris : la garde est un middleware ASGI).
from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket

from services import lifecycle

router = APIRouter(prefix="/shell", tags=["shell"])


@router.get("")
def shell() -> dict:
    """`browser_mode` : le frontend n'affiche « Quitter » et n'ouvre la présence
    que s'il est vrai. Faux en fenêtre native comme en dev (`server.main`)."""
    return {"browser_mode": lifecycle.browser_mode()}


@router.post("/quit")
def quit_app() -> dict:
    if not lifecycle.quit_app():
        raise HTTPException(status_code=409, detail="not in browser mode")
    return {"stopping": True}


@router.websocket("/presence")
async def presence(ws: WebSocket) -> None:
    """Un onglet ouvert = une connexion. Le client n'envoie rien ; tout message
    est ignoré. L'arrêt du serveur ferme la connexion (1012), ce qui dit au
    frontend que Meta-Capp s'est arrêté."""
    await ws.accept()
    lifecycle.tab_opened()
    try:
        while (await ws.receive())["type"] != "websocket.disconnect":
            pass
    finally:
        lifecycle.tab_closed()
