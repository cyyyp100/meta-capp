# server/events.py — Pont entre le worker LLM (thread démon) et la boucle asyncio.
#
# Les callbacks du client Ollama tournent sur un thread séparé ; pour pousser un
# événement vers un WebSocket, on doit repasser dans la boucle asyncio via
# loop.call_soon_threadsafe. C'est l'analogue serveur de l'ancien self.after(0).
from __future__ import annotations

import asyncio
from typing import Any


def push_threadsafe(loop: asyncio.AbstractEventLoop, queue: "asyncio.Queue[Any]", event: dict) -> None:
    """Dépose un événement dans la file asyncio depuis n'importe quel thread."""
    loop.call_soon_threadsafe(queue.put_nowait, event)
