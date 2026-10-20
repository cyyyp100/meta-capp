# server/routers/annotations.py — Étiquettes de la prise de notes (schéma v45).
#
# Globales à l'élève, pas à un document : « Important », « Définition »… puis
# les siennes. Routeur fin : la validation est celle de services/annotations.py.
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import annotations

router = APIRouter(prefix="/annotations", tags=["annotations"])


def _fail(exc: ValueError) -> HTTPException:
    status = 404 if isinstance(exc, annotations.AnnotationNotFound) else 400
    return HTTPException(status_code=status, detail=str(exc))


class LabelBody(BaseModel):
    name: str
    color: str


class LabelEditBody(BaseModel):
    # Absent : inchangé. `name: null` rend son nom traduit à une étiquette
    # prédéfinie.
    name: str | None = None
    color: str | None = None


class LabelOrderBody(BaseModel):
    ids: list[int]


@router.get("/labels")
def list_labels() -> dict:
    """Les étiquettes, et les bornes de `config/settings.py` que l'interface
    applique avant d'envoyer (longueur d'un nom, nombre, couleur proposée)."""
    return {"labels": annotations.labels_payload(), **annotations.label_limits()}


@router.post("/labels")
def create_label(body: LabelBody) -> dict:
    try:
        return {"label": annotations.create_label(body.name, body.color)}
    except ValueError as exc:
        raise _fail(exc)


@router.post("/labels/order")
def order_labels(body: LabelOrderBody) -> dict:
    try:
        return {"labels": annotations.reorder_labels(body.ids)}
    except ValueError as exc:
        raise _fail(exc)


@router.post("/labels/{label_id}/edit")
def edit_label(label_id: int, body: LabelEditBody) -> dict:
    fields = {name: getattr(body, name) for name in body.model_fields_set}
    try:
        return {"label": annotations.update_label(label_id, fields)}
    except ValueError as exc:
        raise _fail(exc)


@router.delete("/labels/{label_id}")
def delete_label(label_id: int) -> dict:
    try:
        return annotations.delete_label(label_id)
    except ValueError as exc:
        raise _fail(exc)
