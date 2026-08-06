# server/routers/flashcards.py
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from services.flashcards import (
    create_flashcard,
    delete_flashcards,
    due_flashcards,
    list_flashcards,
    review_flashcard,
    session_start_cards,
)

router = APIRouter(prefix="/flashcards", tags=["flashcards"])


class ReviewBody(BaseModel):
    verdict: str  # "correct" | "partial" | "incorrect"


class CreateBody(BaseModel):
    front: str
    back: str
    tags: list[str] | None = None
    difficulty: int = 2
    source: str = "manual"


class FromExchangeBody(BaseModel):
    front: str
    back: str
    doc_id: int | None = None
    page: int | None = None


@router.get("")
def list_cards(
    document_id: int | None = None,
    difficulty: int | None = None,
    tags: str | None = None,
) -> list[dict]:
    filters: dict = {}
    if document_id is not None:
        filters["document_id"] = document_id
    if difficulty is not None:
        filters["difficulty"] = difficulty
    if tags:
        filters["tags"] = tags
    return list_flashcards(**filters)


@router.get("/due")
def due(doc_id: int | None = None, limit: int = 5) -> list[dict]:
    return due_flashcards(doc_id, limit)


@router.get("/session-start")
def session_start(doc_id: int | None = None, limit: int = 5) -> list[dict]:
    """Cartes du warm-up de début de session (sélection par pertinence)."""
    return session_start_cards(doc_id, limit)


@router.post("")
def create(body: CreateBody) -> dict:
    card_id = create_flashcard(
        front=body.front,
        back=body.back,
        tags=body.tags,
        difficulty=body.difficulty,
        source=body.source,
    )
    return {"id": card_id}


@router.post("/from-exchange")
def from_exchange(body: FromExchangeBody) -> dict:
    """Crée une flashcard AUTOPORTANTE à partir d'un échange (recto/verso bruts).

    Le LLM réécrit le recto en question autonome (remplace « selon ce texte » par
    le concept). Repli sur les textes bruts si le LLM est indisponible.
    """
    from services.assistant import make_flashcard
    from services.llm_bridge import run_llm_sync

    front, back = body.front, body.back
    card: dict | None = None
    try:
        result = run_llm_sync(
            lambda ok, err: make_flashcard(body.doc_id or 0, body.page or 1, front, back, ok, err),
            timeout=30,
        )
        if isinstance(result, dict):
            card = result
    except Exception:
        card = None

    final_front = (card or {}).get("front") or front
    final_back = (card or {}).get("back") or back
    card_id = create_flashcard(
        front=final_front,
        back=final_back,
        tags=(card or {}).get("tags"),
        difficulty=(card or {}).get("difficulty") or 2,
        source="manual",
        document_id=body.doc_id,
    )
    return {"id": card_id, "front": final_front, "back": final_back}


@router.post("/{card_id}/review")
def review(card_id: int, body: ReviewBody) -> dict:
    review_flashcard(card_id, body.verdict)
    return {"ok": True}


@router.delete("/{card_id}")
def delete(card_id: int) -> dict:
    removed = delete_flashcards([card_id])
    return {"removed": removed}
