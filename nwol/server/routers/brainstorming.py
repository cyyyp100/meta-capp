# server/routers/brainstorming.py — Page « Brainstorming » (chat libre + RAG).
#
# REST  : gestion des discussions (liste / création / messages / suppression).
# WS    : canal temps réel d'une discussion.
#   client -> serveur : {"type":"ask","question":"…"}
#   serveur -> client : {"type":"loading"} | {"type":"scanning","active":bool}
#                       {"type":"answer","answer","sources"} | {"type":"error","message"}
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from db import brainstorm as store
from server.events import push_threadsafe
from services import brainstorm

logger = logging.getLogger("server.brainstorming")

router = APIRouter(prefix="/brainstorming", tags=["brainstorming"])


class CreateBody(BaseModel):
    title: str | None = None


@router.get("/discussions")
def discussions() -> list[dict]:
    return store.list_discussions()


@router.post("")
def create(body: CreateBody) -> dict:
    discussion_id = store.create_discussion(body.title or "")
    created = store.get_discussion(discussion_id)
    return created or {"id": discussion_id, "title": (body.title or "").strip()}


@router.get("/{discussion_id}/messages")
def messages(discussion_id: int) -> dict:
    discussion = store.get_discussion(discussion_id)
    if discussion is None:
        raise HTTPException(status_code=404, detail="Discussion introuvable")
    return {
        "id": discussion["id"],
        "title": discussion["title"],
        "summary": discussion.get("summary") or "",
        "messages": store.get_messages(discussion_id),
    }


@router.delete("/{discussion_id}")
def delete(discussion_id: int) -> dict:
    store.delete_discussion(discussion_id)
    return {"ok": True}


@router.websocket("/{discussion_id}/stream")
async def brainstorm_stream(ws: WebSocket, discussion_id: int) -> None:
    await ws.accept()
    loop = asyncio.get_running_loop()
    out: asyncio.Queue = asyncio.Queue()

    async def _sender() -> None:
        while True:
            event = await out.get()
            if event is None:
                return
            await ws.send_json(event)

    sender_task = asyncio.create_task(_sender())

    def on_answer(result: dict) -> None:
        push_threadsafe(loop, out, {
            "type": "answer",
            "answer": result.get("answer", ""),
            "sources": result.get("sources", []),
        })

    def on_error(message: str) -> None:
        push_threadsafe(loop, out, {"type": "error", "message": str(message)})

    def on_scanning(active: bool) -> None:
        push_threadsafe(loop, out, {"type": "scanning", "active": bool(active)})

    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") != "ask":
                continue
            question = str(msg.get("question") or "").strip()
            if not question:
                continue
            await out.put({"type": "loading"})
            # handle_message rend la main vite (il met le travail LLM en file) ;
            # les callbacks reviennent depuis le thread worker via push_threadsafe.
            brainstorm.handle_message(discussion_id, question, on_answer, on_error, on_scanning)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        logger.warning("WebSocket brainstorming erreur : %s", exc)
    finally:
        await out.put(None)
        await sender_task
