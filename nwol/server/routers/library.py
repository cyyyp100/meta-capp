# server/routers/library.py
from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from config.settings import LIBRARY_MAX_DOCUMENTS, LIBRARY_SEARCH_LIMIT, UPLOAD_MAX_BYTES
from server.security import import_path_allowed
from services.library import (
    delete_document as delete_document_service,
    get_document,
    list_all_documents,
    list_recent_documents,
    page_words,
    rename_document as rename_document_service,
    render_page,
    search_documents,
    search_page,
)

if TYPE_CHECKING:
    from services.relink import RelinkError

router = APIRouter(prefix="/library", tags=["library"])


class ImportBody(BaseModel):
    path: str


class RelinkBody(BaseModel):
    path: str
    # Relier même si le contenu diffère de celui de l'import (nouvelle version) :
    # l'interface ne l'envoie qu'après confirmation (`different_file`).
    force: bool = False


class FolderBody(BaseModel):
    name: str
    parent_id: int | None = None


class FolderNameBody(BaseModel):
    name: str


class FolderParentBody(BaseModel):
    parent_id: int | None = None


class DocumentFolderBody(BaseModel):
    folder_id: int | None = None


class DocumentTitleBody(BaseModel):
    title: str


@router.get("/recent")
def recent(limit: int = 10) -> list[dict]:
    return list_recent_documents(limit)


@router.get("/documents")
def documents(limit: int = Query(LIBRARY_MAX_DOCUMENTS, ge=1, le=5000)) -> list[dict]:
    """Catalogue complet, du plus récemment ouvert au plus ancien.

    Servi d'un bloc : le rail de dossiers filtre côté client, ce qui rend un
    glisser-déposer instantané et évite une clé de cache par dossier.
    """
    return list_all_documents(limit)


@router.get("/search")
def search_library(q: str, limit: int = Query(LIBRARY_SEARCH_LIMIT, ge=1, le=200)) -> list[dict]:
    """Recherche globale : nom de fichier + résumé généré + mots-clés + matière."""
    return search_documents(q, limit)


# ── Dossiers de la bibliothèque ─────────────────────────────────────────────
# La politique (cycles, profondeur, sort des documents) est dans
# services/folders.py ; ici on ne fait que traduire ses ValueError en 400.


@router.get("/folders")
def folders() -> list[dict]:
    from services.folders import folder_tree

    return folder_tree()


@router.post("/folders")
def create_folder(body: FolderBody) -> dict:
    from services import folders as folders_service

    try:
        return folders_service.create_folder(body.name, body.parent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/folders/{folder_id}/rename")
def rename_folder(folder_id: int, body: FolderNameBody) -> dict:
    from services import folders as folders_service

    try:
        return folders_service.rename_folder(folder_id, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/folders/{folder_id}/move")
def move_folder(folder_id: int, body: FolderParentBody) -> dict:
    from services import folders as folders_service

    try:
        return folders_service.move_folder(folder_id, body.parent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: int) -> dict:
    from services import folders as folders_service

    try:
        return folders_service.delete_folder(folder_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _checked_import_path(raw: str) -> str:
    """Chemin choisi dans le sélecteur natif, passé à la garde S2. Renvoie le
    chemin résolu (realpath) : celui qu'un import enregistrerait. HTTP 400 sinon.

    Partagé par `/import` et `/relink` : relier un document à un fichier, c'est
    l'importer à nouveau — une garde plus lâche ferait de `/relink` un moyen de
    lire ce que `/import` refuse."""
    from services import code_reader

    if not raw or not os.path.isfile(raw):
        raise HTTPException(status_code=400, detail="Fichier introuvable")
    if not raw.lower().endswith(".pdf") and not code_reader.is_code_file(raw):
        raise HTTPException(status_code=400, detail="Format non pris en charge (PDF ou fichier de code)")
    # S2 : confinement aux dossiers utilisateur (realpath, symlinks résolus).
    if not import_path_allowed(raw):
        raise HTTPException(status_code=400, detail="Chemin non autorisé")
    return os.path.realpath(raw)


async def _receive_upload(request: Request, filename: str) -> tuple[str, bool]:
    """Corps brut d'un envoi → copie dans le dossier de données (services/uploads).

    Renvoie (chemin, nouveau) : `nouveau` est faux si ce contenu était déjà là
    sous ce nom — un échec ultérieur ne doit alors PAS effacer une copie qu'un
    document existant référence."""
    from services import code_reader, uploads

    name = uploads.safe_filename(filename)
    if not name.lower().endswith(".pdf") and not code_reader.is_code_file(name):
        raise HTTPException(status_code=400, detail="Format non pris en charge (PDF ou fichier de code)")

    spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    try:
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > UPLOAD_MAX_BYTES:
                raise HTTPException(status_code=413, detail="Fichier trop volumineux")
            spool.write(chunk)
        spool.seek(0)
        try:
            return await run_in_threadpool(uploads.store, name, spool)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    finally:
        spool.close()


@router.post("/import")
def import_document(body: ImportBody) -> dict:
    real = _checked_import_path(body.path)
    if real.lower().endswith(".pdf"):
        from services.orchestrator import import_pdf

        return import_pdf(real)
    from services.orchestrator import import_code

    try:
        return import_code(real)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/upload")
async def upload_document(request: Request, filename: str = Query(..., min_length=1, max_length=255)) -> dict:
    """Import d'un document ENVOYÉ (corps brut) — le pendant de `/import` quand
    l'interface tourne dans un navigateur, qui ne donne jamais de chemin.

    Mêmes gardes que tout `/api` (Host, Origin, nonce). Le fichier est copié dans
    le dossier de données (services/uploads), puis importé par le même chemin
    que `/import`."""
    from services import uploads

    path, is_new = await _receive_upload(request, filename)
    is_pdf = path.lower().endswith(".pdf")

    def _import() -> dict:
        if is_pdf:
            from services.orchestrator import import_pdf

            return import_pdf(path)
        from services.orchestrator import import_code

        return import_code(path)

    try:
        return await run_in_threadpool(_import)
    except Exception as exc:
        if is_new:
            uploads.discard(path)
        detail = str(exc) if isinstance(exc, ValueError) else "Document illisible"
        raise HTTPException(status_code=400, detail=detail)


@router.get("/doc/{doc_id}")
def document(doc_id: int) -> dict:
    detail = get_document(doc_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return detail


@router.delete("/doc/{doc_id}")
def delete_document(doc_id: int) -> dict:
    """Retire le document de la bibliothèque (jamais le fichier de l'utilisateur)."""
    try:
        return delete_document_service(doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── « Localiser le fichier » ────────────────────────────────────────────────
# Toute la politique (identité, voisins, nettoyage) est dans services/relink ;
# ici, la garde S2 et la traduction de ses refus en `{detail, code}`.


def _relink_refusal(exc: RelinkError) -> JSONResponse:
    """RelinkError → réponse lisible : `detail` traduit pour l'utilisateur, `code`
    pour l'interface (`different_file` y déclenche « Relier quand même ? »)."""
    return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=exc.status)


@router.post("/doc/{doc_id}/relink", response_model=None)
def relink_document(doc_id: int, body: RelinkBody) -> dict | JSONResponse:
    """Relie le document à l'emplacement actuel de son fichier (sélecteur natif).

    Même garde que `/import`, et les autres documents introuvables déplacés
    avec lui sont cherchés sous le nouveau dossier, chacun passant cette garde."""
    from services.relink import RelinkError
    from services.relink import relink_document as relink_service

    real = _checked_import_path(body.path)
    try:
        return relink_service(doc_id, real, force=body.force, path_allowed=import_path_allowed)
    except RelinkError as exc:
        return _relink_refusal(exc)


@router.post("/doc/{doc_id}/relink/upload", response_model=None)
async def relink_upload(
    request: Request,
    doc_id: int,
    filename: str = Query(..., min_length=1, max_length=255),
    force: bool = False,
) -> dict | JSONResponse:
    """Le pendant de `/relink` en mode navigateur : le fichier est ENVOYÉ, et
    c'est sa copie (services/uploads) qui devient le fichier du document.

    Pas de passe sur les voisins : un navigateur ne dit pas où était le fichier
    choisi. La copie n'est jetée en cas d'échec que si cet envoi l'a créée — un
    document existant peut référencer une copie identique."""
    from services import uploads
    from services.relink import RelinkError
    from services.relink import relink_document as relink_service

    path, is_new = await _receive_upload(request, filename)
    try:
        return await run_in_threadpool(lambda: relink_service(doc_id, path, force=force))
    except RelinkError as exc:
        if is_new:
            uploads.discard(path)
        return _relink_refusal(exc)
    except BaseException:
        if is_new:
            uploads.discard(path)
        raise


@router.post("/doc/{doc_id}/rename")
def rename_document(doc_id: int, body: DocumentTitleBody) -> dict:
    """Renomme le TITRE d'un document (clic droit → Renommer). Le fichier de
    l'utilisateur n'est pas renommé — même règle qu'à la suppression."""
    try:
        return {"ok": True, "document": rename_document_service(doc_id, body.title)}
    except ValueError as exc:
        missing = get_document(doc_id) is None
        raise HTTPException(status_code=404 if missing else 400, detail=str(exc))


@router.post("/doc/{doc_id}/folder")
def move_document(doc_id: int, body: DocumentFolderBody) -> dict:
    """Range un document. `folder_id: null` = racine (« Non classés »)."""
    from services import folders as folders_service

    try:
        folders_service.move_document(doc_id, body.folder_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "document": get_document(doc_id)}


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
        result = run_llm_sync(lambda ok, err: curiosity_hook(doc_id, page, ok, err))
        return {"hook": (result or {}).get("answer", "")}
    except Exception:
        return {"hook": ""}


@router.get("/doc/{doc_id}/page/{page}.png")
def page_image(doc_id: int, page: int, zoom: float = Query(2.5, ge=0.5, le=6.0)) -> FileResponse:
    try:
        path = render_page(doc_id, page, zoom)
    except ValueError as exc:
        # Page hors limites : le PDF a pu être réécrit plus court pendant la lecture.
        raise HTTPException(status_code=404, detail=str(exc))
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
