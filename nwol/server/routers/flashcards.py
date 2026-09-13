# server/routers/flashcards.py
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from services.flashcards import (
    create_flashcard,
    delete_flashcards,
    due_flashcards,
    find_flashcard,
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
    """Crée une carte. `created: false` = elle existait déjà (même recto/verso
    au sens près) ; c'est alors son id qui est renvoyé, rien n'est écrit."""
    existing = find_flashcard(body.front, body.back)
    if existing is not None:
        return {"id": existing, "created": False}
    card_id = create_flashcard(
        front=body.front,
        back=body.back,
        tags=body.tags,
        difficulty=body.difficulty,
        source=body.source,
    )
    return {"id": card_id, "created": True}


@router.post("/from-exchange")
def from_exchange(body: FromExchangeBody) -> dict:
    """Crée une flashcard AUTOPORTANTE à partir d'un échange (recto/verso bruts).

    Le LLM réécrit le recto en question autonome (remplace « selon ce texte » par
    le concept). Repli sur les textes bruts si le LLM est indisponible.

    DOUBLON : l'échange BRUT est la clé (la réécriture LLM change à chaque
    appel). Un second « + Flashcard » sur la même réponse rend la carte
    existante (`created: false`) sans même solliciter le LLM.
    """
    from services.assistant import make_flashcard
    from services.llm_bridge import run_llm_sync

    front, back = body.front, body.back
    existing = find_flashcard(front, back)
    if existing is not None:
        return {"id": existing, "front": front, "back": back, "created": False}
    card: dict | None = None
    try:
        result = run_llm_sync(
            lambda ok, err: make_flashcard(body.doc_id or 0, body.page or 1, front, back, ok, err),
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
        origin=(front, back),
    )
    return {"id": card_id, "front": final_front, "back": final_back, "created": True}


@router.post("/{card_id}/review")
def review(card_id: int, body: ReviewBody) -> dict:
    review_flashcard(card_id, body.verdict)
    return {"ok": True}


@router.delete("/{card_id}")
def delete(card_id: int) -> dict:
    removed = delete_flashcards([card_id])
    return {"removed": removed}
