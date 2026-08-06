# server/routers/library.py
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from server.security import import_path_allowed
from services.library import (
    get_document,
    list_recent_documents,
    page_words,
    render_page,
    search_page,
)

router = APIRouter(prefix="/library", tags=["library"])


class ImportBody(BaseModel):
    path: str


@router.get("/recent")
def recent(limit: int = 10) -> list[dict]:
    return list_recent_documents(limit)


@router.post("/import")
def import_document(body: ImportBody) -> dict:
    from services import code_reader

    if not body.path or not os.path.isfile(body.path):
        raise HTTPException(status_code=400, detail="Fichier introuvable")
    is_pdf = body.path.lower().endswith(".pdf")
    is_code = code_reader.is_code_file(body.path)
    if not is_pdf and not is_code:
        raise HTTPException(status_code=400, detail="Format non pris en charge (PDF ou fichier de code)")
    # S2 : confinement aux dossiers utilisateur (realpath, symlinks résolus).
    if not import_path_allowed(body.path):
        raise HTTPException(status_code=400, detail="Chemin non autorisé")
    real = os.path.realpath(body.path)
    if is_pdf:
        from services.orchestrator import import_pdf

        return import_pdf(real)
    from services.orchestrator import import_code

    try:
        return import_code(real)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/doc/{doc_id}")
def document(doc_id: int) -> dict:
    detail = get_document(doc_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return detail


@router.get("/doc/{doc_id}/page/{page}/search")
def search(doc_id: int, page: int, q: str) -> dict:
    """Rects (x0,y0,x1,y1) en points PDF où `q` apparaît sur la page."""
    return {"rects_pts": search_page(doc_id, page, q)}


@router.get("/doc/{doc_id}/page/{page}/words")
def words(doc_id: int, page: int) -> dict:
    """Boîtes de mots ([x0,y0,x1,y1,"mot"] en points PDF) pour le calque de texte
    transparent du lecteur (sélection native par-dessus l'image rendue)."""
    return {"words": page_words(doc_id, page)}


@router.get("/doc/{doc_id}/hook")
def hook(doc_id: int, page: int = 1) -> dict:
    """Accroche de curiosité (LLM) pour le SAS d'entrée. Vide si LLM indisponible."""
    from services.assistant import curiosity_hook
    from services.llm_bridge import run_llm_sync

    try:
        result = run_llm_sync(lambda ok, err: curiosity_hook(doc_id, page, ok, err), timeout=45)
        return {"hook": (result or {}).get("answer", "")}
    except Exception:
        return {"hook": ""}


@router.get("/doc/{doc_id}/page/{page}.png")
def page_image(doc_id: int, page: int, zoom: float = Query(2.5, ge=0.5, le=6.0)) -> FileResponse:
    path = render_page(doc_id, page, zoom)
    if path is None:
        raise HTTPException(status_code=404, detail="Document introuvable")
    # Le PNG est immuable pour un (doc, page, zoom) -> cache navigateur agressif.
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=31536000, immutable"})


@router.get("/doc/{doc_id}/page/{page}/blocks")
def blocks(doc_id: int, page: int) -> dict:
    from services.library import page_blocks

    result = page_blocks(doc_id, page)
    if result is None:
        # Document rendu en image (PDF) : le frontend bascule sur la vue image.
        return {"blocks": None}
    return {"blocks": result}
