# server/routers/data.py — Sauvegarde/restauration des données utilisateur.
#
# L'import prend le fichier en corps brut (application/octet-stream) : pas de
# dépendance multipart, et le frontend envoie simplement le File lu en bytes.
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from services import data_export

router = APIRouter(prefix="/data", tags=["data"])


def _serve_then_cleanup(path: str, media_type: str) -> FileResponse:
    def _cleanup() -> None:
        try:
            os.unlink(path)
            os.rmdir(Path(path).parent)
        except OSError:
            pass

    return FileResponse(
        path,
        media_type=media_type,
        filename=Path(path).name,
        background=BackgroundTask(_cleanup),
    )


@router.get("/export")
def export_db() -> FileResponse:
    return _serve_then_cleanup(data_export.export_db(), "application/vnd.sqlite3")


@router.get("/export-logs")
def export_logs() -> FileResponse:
    path = data_export.export_logs()
    if path is None:
        raise HTTPException(status_code=404, detail="Aucun log à exporter")
    return _serve_then_cleanup(path, "application/zip")


@router.post("/import")
async def import_db(request: Request) -> dict:
    content = await request.body()
    try:
        return data_export.import_db(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class PurgeBody(BaseModel):
    confirm: str


@router.post("/purge")
def purge(body: PurgeBody) -> dict:
    # Action destructive : confirmation textuelle exacte exigée (anti-clic malheureux
    # et anti-CSRF de seconde ligne, en plus des gardes S1).
    if body.confirm != "EFFACER":
        raise HTTPException(status_code=400, detail='Confirmation attendue : "EFFACER"')
    return data_export.purge_all_data()
