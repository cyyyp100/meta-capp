# server/routers/highlights.py — Prise de notes d'un document du lecteur.
#
# Surlignages (table reader_highlights, v20 ; étiquette, style et note en v45),
# post-it et signets (reader_notes, v45), et l'export Markdown du carnet. Le
# frontend recharge tout à l'ouverture du document ; les citations surlignées
# enrichissent aussi le contexte LLM (cf. services.assistant.build_answer_context).
# Routeur fin : la validation est celle de services/annotations.py, ses refus
# deviennent des 400, et ce qui est introuvable un 404.
from __future__ import annotations

from urllib.parse import quote as url_quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from db.reader_highlights import list_highlights
from services import annotations

router = APIRouter(prefix="/library/doc", tags=["highlights"])


def _fail(exc: ValueError) -> HTTPException:
    status = 404 if isinstance(exc, annotations.AnnotationNotFound) else 400
    return HTTPException(status_code=status, detail=str(exc))


class HighlightAnchor(BaseModel):
    """Ancrage texte d'un surlignage sur page reconstruite (fichiers de code)."""

    block_id: str
    start: int
    end: int


class HighlightBody(BaseModel):
    page: int
    quote: str
    rects: list[list[float]]
    # L'ancienne couleur (« key », « explain », « reference ») : traduite en
    # étiquette quand `label_id` n'est pas donné.
    color: str | None = None
    anchor: HighlightAnchor | None = None
    label_id: int | None = None
    style: str | None = None
    note: str | None = None


class HighlightEditBody(BaseModel):
    # Un champ ABSENT ne change pas ; un champ à null efface (étiquette, note).
    label_id: int | None = None
    style: str | None = None
    note: str | None = None


class NoteBody(BaseModel):
    kind: str
    page: int
    x: float | None = None
    y: float | None = None
    body: str = ""
    label_id: int | None = None


class NoteEditBody(BaseModel):
    body: str | None = None
    label_id: int | None = None
    x: float | None = None
    y: float | None = None


def _set_fields(body: BaseModel) -> dict:
    """Les seuls champs envoyés par le client (`model_fields_set`)."""
    return {name: getattr(body, name) for name in body.model_fields_set}


@router.get("/{doc_id}/highlights")
def get_highlights(doc_id: int) -> list[dict]:
    return list_highlights(doc_id)


@router.get("/{doc_id}/annotations")
def get_annotations(doc_id: int) -> dict:
    """Surlignages, post-it et signets du document."""
    try:
        return annotations.document_annotations(doc_id)
    except ValueError as exc:
        raise _fail(exc)


@router.post("/{doc_id}/highlights")
def create_highlight(doc_id: int, body: HighlightBody) -> dict:
    data = _set_fields(body)
    if body.anchor is not None:
        data["anchor"] = body.anchor.model_dump()
    try:
        highlight = annotations.create_highlight(doc_id, data)
    except ValueError as exc:
        raise _fail(exc)
    return {"id": highlight["id"], "highlight": highlight}


@router.post("/{doc_id}/highlights/{highlight_id}/edit")
def edit_highlight(doc_id: int, highlight_id: int, body: HighlightEditBody) -> dict:
    try:
        return {"highlight": annotations.update_highlight(doc_id, highlight_id, _set_fields(body))}
    except ValueError as exc:
        raise _fail(exc)


@router.delete("/{doc_id}/highlights/{highlight_id}")
def remove_highlight(doc_id: int, highlight_id: int) -> dict:
    return {"removed": annotations.delete_highlight(doc_id, highlight_id)}


@router.post("/{doc_id}/notes")
def create_note(doc_id: int, body: NoteBody) -> dict:
    try:
        return {"note": annotations.create_note(doc_id, _set_fields(body) | {"kind": body.kind, "page": body.page})}
    except ValueError as exc:
        raise _fail(exc)


@router.post("/{doc_id}/notes/{note_id}/edit")
def edit_note(doc_id: int, note_id: int, body: NoteEditBody) -> dict:
    try:
        return {"note": annotations.update_note(doc_id, note_id, _set_fields(body))}
    except ValueError as exc:
        raise _fail(exc)


@router.delete("/{doc_id}/notes/{note_id}")
def remove_note(doc_id: int, note_id: int) -> dict:
    return {"removed": annotations.delete_note(doc_id, note_id)}


@router.get("/{doc_id}/annotations.md")
def export_annotations(doc_id: int) -> Response:
    """Le carnet du document, à enregistrer (`Content-Disposition: attachment`)."""
    try:
        filename, text = annotations.export_markdown(doc_id)
    except ValueError as exc:
        raise _fail(exc)
    return Response(
        content=text.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{url_quote(filename)}",
        },
    )
