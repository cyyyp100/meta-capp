# server/routers/brainstorming.py — Page « Brainstorming » (chat libre + RAG).
#
# REST  : gestion des discussions (liste / création / messages / suppression,
#         épinglage, lien à un dossier de la bibliothèque).
# WS    : canal temps réel d'une discussion.
#   client -> serveur : {"type":"ask","question":"…"}
#   serveur -> client : {"type":"loading"} | {"type":"title","title"}
#                       {"type":"scanning","active":bool}
#                       {"type":"answer","answer","sources"} | {"type":"error","message"}
#
# Plafond d'épinglage et validité du dossier : `services/brainstorm.py` ; ici on
# ne fait que traduire ses ValueError en 400.
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

# Bornage des entrées client (S4) — même seuil que le WebSocket du lecteur
# (`routers/reading.py:_MAX_QUESTION_CHARS`). Sans lui, une question de taille
# arbitraire partait directement dans un prompt.
_MAX_QUESTION_CHARS = 4000


class CreateBody(BaseModel):
    title: str | None = None
    folder_id: int | None = None


class PinBody(BaseModel):
    pinned: bool


class FolderBody(BaseModel):
    folder_id: int | None = None


@router.get("/discussions")
def discussions() -> list[dict]:
    return store.list_discussions()


@router.post("")
def create(body: CreateBody) -> dict:
    try:
        return brainstorm.create_discussion(body.title or "", body.folder_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{discussion_id}/pin")
def pin(discussion_id: int, body: PinBody) -> dict:
    try:
        return brainstorm.set_pinned(discussion_id, body.pinned)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{discussion_id}/folder")
def link_folder(discussion_id: int, body: FolderBody) -> dict:
    try:
        return brainstorm.set_folder(discussion_id, body.folder_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{discussion_id}/messages")
def messages(discussion_id: int) -> dict:
    discussion = store.get_discussion(discussion_id)
    if discussion is None:
        raise HTTPException(status_code=404, detail="Discussion introuvable")
    return {
        "id": discussion["id"],
        "title": discussion["title"],
        "summary": discussion.get("summary") or "",
        "pinned_at": discussion.get("pinned_at"),
        "folder_id": discussion.get("folder_id"),
        "folder_name": discussion.get("folder_name"),
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

    def on_title(title: str) -> None:
        push_threadsafe(loop, out, {"type": "title", "title": str(title)})

    try:
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict) or msg.get("type") != "ask":
                continue
            # S4 : on tronque plutôt que de refuser — une question trop longue
            # reste une question, et fermer le socket ferait perdre la discussion.
            question = str(msg.get("question") or "").strip()[:_MAX_QUESTION_CHARS]
            if not question:
                continue
            await out.put({"type": "loading"})
            # handle_message rend la main vite (il met le travail LLM en file) ;
            # les callbacks reviennent depuis le thread worker via push_threadsafe.
            brainstorm.handle_message(
                discussion_id, question, on_answer, on_error, on_scanning, on_title=on_title,
            )
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        logger.warning("WebSocket brainstorming erreur : %s", exc)
    finally:
        await out.put(None)
        await sender_task
