# server/app.py — Factory de l'application FastAPI.
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server import security
from server.config import APP_VERSION, DEV_ORIGINS, FRONTEND_DIST
from server.routers import (
    brainstorming,
    data,
    flashcards,
    health,
    highlights,
    lang,
    library,
    quiz,
    reading,
    session,
    stats,
)

logger = logging.getLogger("server")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Initialisation DB (idempotente) au démarrage, comme NWoLApp.__init__.
    from db.schema import initialize_schema

    initialize_schema()
    logger.info("Serveur Meta-Capp prêt (v%s).", APP_VERSION)
    yield


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    # S3 : réponse uniforme, la trace ne part JAMAIS au client (log serveur).
    logger.exception("Erreur non gérée sur %s %s", request.method, request.url.path)
    return JSONResponse({"error": "internal"}, status_code=500)


def create_app() -> FastAPI:
    # Nonce de lancement : posé par la coque desktop (env) avant création.
    env_token = os.environ.get("NWOL_LAUNCH_TOKEN")
    if env_token:
        security.set_launch_token(env_token)

    app = FastAPI(title="Meta-Capp", version=APP_VERSION, lifespan=_lifespan)
    app.add_exception_handler(Exception, _unhandled_error)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Ajouté en dernier -> exécuté en premier (garde la plus externe, HTTP + WS).
    app.add_middleware(security.LocalOnlyGuard)

    app.include_router(health.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")
    app.include_router(flashcards.router, prefix="/api")
    app.include_router(library.router, prefix="/api")
    app.include_router(highlights.router, prefix="/api")
    app.include_router(reading.router, prefix="/api")
    app.include_router(quiz.router, prefix="/api")
    app.include_router(session.router, prefix="/api")
    app.include_router(session.streak_router, prefix="/api")
    app.include_router(lang.router, prefix="/api")
    app.include_router(brainstorming.router, prefix="/api")
    app.include_router(data.router, prefix="/api")

    # En production, sert le frontend compilé depuis la même origine.
    if FRONTEND_DIST.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
        logger.info("Frontend servi depuis %s", FRONTEND_DIST)

    return app
