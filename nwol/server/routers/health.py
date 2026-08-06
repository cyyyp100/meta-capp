# server/routers/health.py
from __future__ import annotations

from fastapi import APIRouter

from server.config import APP_VERSION

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "version": APP_VERSION}
