# server/routers/stats.py
from __future__ import annotations

from fastapi import APIRouter

from services.stats import get_metacog_overview

router = APIRouter(prefix="/stats", tags=["stats"])


# Endpoints synchrones (def) -> exécutés dans le threadpool FastAPI : chaque
# thread obtient sa propre connexion SQLite (thread-local).
@router.get("/overview")
def overview() -> dict:
    return get_metacog_overview()
