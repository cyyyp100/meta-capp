# server/routers/highlights.py — Surlignages persistants du lecteur web.
#
# CRUD HTTP sur la table reader_highlights (schéma v20). Le frontend recharge les
# surlignages à l'ouverture du PDF et les redessine ; ils enrichissent aussi le
# contexte LLM (cf. services.assistant.build_answer_context).
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from db.reader_highlights import add_highlight, delete_highlight, list_highlights

router = APIRouter(prefix="/library/doc", tags=["highlights"])


class HighlightAnchor(BaseModel):
    """Ancrage texte d'un surlignage sur page reconstruite (édition cloud)."""

    block_id: str
    start: int
    end: int


class HighlightBody(BaseModel):
    page: int
    quote: str
    rects: list[list[float]]
    color: str = "key"
    anchor: HighlightAnchor | None = None


@router.get("/{doc_id}/highlights")
def get_highlights(doc_id: int) -> list[dict]:
    return list_highlights(doc_id)


@router.post("/{doc_id}/highlights")
def create_highlight(doc_id: int, body: HighlightBody) -> dict:
    hid = add_highlight(
        document_id=doc_id,
        page=body.page,
        quote=body.quote,
        rects=body.rects,
        color=body.color,
        anchor=body.anchor.model_dump() if body.anchor else None,
    )
    return {"id": hid}


@router.delete("/{doc_id}/highlights/{highlight_id}")
def remove_highlight(doc_id: int, highlight_id: int) -> dict:
    removed = delete_highlight(highlight_id)
    return {"removed": removed}
