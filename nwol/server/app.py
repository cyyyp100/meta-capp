# server/app.py — Factory de l'application FastAPI.
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    preferences,
    progress,
    quiz,
    reading,
    session,
    stats,
    updates,
)

logger = logging.getLogger("server")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Initialisation DB (idempotente) au démarrage, comme NWoLApp.__init__.
    from db.schema import initialize_schema

    initialize_schema()
    # Restaure la langue choisie : elle pilote l'i18n backend ET les prompts LLM.
    preferences.apply_stored_lang()
    logger.info("Serveur Meta-Capp prêt (v%s).", APP_VERSION)
    yield


class _SpaStaticFiles(StaticFiles):
    """Bundle React avec repli SPA.

    Les routes du client (`/reader/12`, `/stats`…) n'existent pas sur disque :
    sans repli, un rechargement de page ou un deep-link renvoie 404. On sert
    `index.html` et react-router prend le relais. Les routes `/api` sont
    déclarées avant ce mount : elles gardent la priorité."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


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
    app.include_router(progress.router, prefix="/api")
    app.include_router(preferences.router, prefix="/api")
    app.include_router(lang.router, prefix="/api")
    app.include_router(brainstorming.router, prefix="/api")
    app.include_router(data.router, prefix="/api")
    app.include_router(updates.router, prefix="/api")

    # En production, sert le frontend compilé depuis la même origine.
    if FRONTEND_DIST.is_dir():
        app.mount("/", _SpaStaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
        logger.info("Frontend servi depuis %s", FRONTEND_DIST)

    return app
