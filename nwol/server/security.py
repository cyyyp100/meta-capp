# server/security.py — Garde locale du serveur (S1/S2 du plan de durcissement).
#
# S1 — CSRF / DNS-rebinding vers localhost : le port 127.0.0.1:8756 n'a pas
# d'auth. Un onglet web quelconque peut tenter de POSTer dessus (CSRF) ou de le
# lire via DNS-rebinding (Host: evil.com résout vers 127.0.0.1). Défenses :
#   1. rejet de tout `Host` non-loopback (tue le DNS-rebinding) ;
#   2. rejet de tout `Origin` étranger (tue le CSRF cross-site direct) ;
#   3. nonce de lancement : la coque desktop (pywebview) génère un jeton
#      aléatoire, le passe au frontend via l'URL d'ouverture ; toute requête
#      /api doit le présenter (header, cookie ou query). Sans coque (dev),
#      aucun jeton n'est configuré et seule la garde Host/Origin s'applique.
#
# S2 — confinement de l'import PDF : POST /api/library/import acceptait tout
# chemin absolu ; combiné à S1 c'était une primitive de lecture de fichier.
# `import_path_allowed()` résout les liens symboliques et confine aux dossiers
# utilisateur autorisés.
from __future__ import annotations

import os
import secrets
from pathlib import Path

from server.config import DEV_ORIGINS, HOST, PORT

# Hôtes loopback acceptés (avec le port du serveur).
ALLOWED_HOSTS = {
    f"{HOST}:{PORT}",
    f"localhost:{PORT}",
}

# Origines acceptées : le serveur lui-même (pywebview / prod même-origine)
# + les origines de dev (Vite). Les requêtes sans header Origin (navigation,
# outils locaux type curl) passent la garde Origin mais restent soumises au
# Host et au nonce.
ALLOWED_ORIGINS = {
    f"http://{HOST}:{PORT}",
    f"http://localhost:{PORT}",
    *DEV_ORIGINS,
}

# Le nonce est exigé sur /api/* sauf le health-check (sonde de démarrage de la
# coque, ne révèle aucune donnée).
TOKEN_EXEMPT_PATHS = {"/api/health"}

TOKEN_HEADER = "x-launch-token"
TOKEN_COOKIE = "nwol_lt"
TOKEN_QUERY = "lt"

_launch_token: str | None = None


def set_launch_token(token: str | None) -> None:
    """Configure le nonce de lancement (appelé par la coque desktop)."""
    global _launch_token
    _launch_token = token or None


def get_launch_token() -> str | None:
    return _launch_token


def new_launch_token() -> str:
    return secrets.token_urlsafe(32)


def _token_matches(candidate: str | None) -> bool:
    if not _launch_token or not candidate:
        return False
    return secrets.compare_digest(candidate, _launch_token)


def _header(scope: dict, name: bytes) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == name:
            return value.decode("latin-1")
    return None


def _cookie_token(scope: dict) -> str | None:
    raw = _header(scope, b"cookie") or ""
    for part in raw.split(";"):
        name, _, value = part.strip().partition("=")
        if name == TOKEN_COOKIE:
            return value
    return None


def _query_token(scope: dict) -> str | None:
    raw = (scope.get("query_string") or b"").decode("latin-1")
    for part in raw.split("&"):
        name, _, value = part.partition("=")
        if name == TOKEN_QUERY:
            return value
    return None


class LocalOnlyGuard:
    """Middleware ASGI pur : couvre HTTP **et** WebSocket (les middlewares
    `@app.middleware("http")` de Starlette ignorent les scopes websocket, or
    les deux endpoints WS du lecteur/brainstorming doivent être gardés avant
    `ws.accept()`)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        host = _header(scope, b"host")
        if host not in ALLOWED_HOSTS:
            await self._reject(scope, receive, send, "forbidden host")
            return

        origin = _header(scope, b"origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            await self._reject(scope, receive, send, "forbidden origin")
            return

        if self._token_required(scope) and not self._token_ok(scope):
            await self._reject(scope, receive, send, "missing or invalid launch token")
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _token_required(scope: dict) -> bool:
        if _launch_token is None:
            return False  # dev sans coque : pas de nonce configuré
        path = scope.get("path") or ""
        return path.startswith("/api") and path not in TOKEN_EXEMPT_PATHS

    @staticmethod
    def _token_ok(scope: dict) -> bool:
        # Cookie (posé par le frontend au premier chargement -> couvre fetch,
        # <img> et WebSocket), header (client API) ou query (handshake WS).
        return (
            _token_matches(_cookie_token(scope))
            or _token_matches(_header(scope, TOKEN_HEADER.encode()))
            or _token_matches(_query_token(scope))
        )

    @staticmethod
    async def _reject(scope, receive, send, reason: str) -> None:
        if scope["type"] == "websocket":
            # Refus du handshake avant tout accept (uvicorn répond 403).
            await receive()
            await send({"type": "websocket.close", "code": 4403})
            return
        body = ('{"error": "%s"}' % reason).encode()
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})


# ── S2 : confinement de l'import PDF ────────────────────────────────────────

# Racines supplémentaires (tests, dossiers hors home) : chemins séparés par
# os.pathsep dans NWOL_IMPORT_ROOTS.
IMPORT_ROOTS_ENV = "NWOL_IMPORT_ROOTS"


def import_roots() -> list[Path]:
    roots = [Path.home()]
    extra = os.environ.get(IMPORT_ROOTS_ENV, "")
    for raw in extra.split(os.pathsep):
        raw = raw.strip()
        if raw:
            roots.append(Path(raw))
    return [Path(os.path.realpath(r)) for r in roots]


def import_path_allowed(path: str) -> bool:
    """Vrai si `path` est un vrai fichier importable (PDF ou code) confiné aux
    racines autorisées.

    Résout les liens symboliques (`realpath`) : un lien home -> /etc/x.pdf est
    rejeté car la cible résolue sort des racines."""
    if not path or ".." in Path(path).parts:
        return False
    real = Path(os.path.realpath(path))
    if not real.is_file():
        return False
    if real.suffix.lower() != ".pdf":
        # Fichier de code/texte : même confinement, format validé plus loin.
        from services import code_reader

        if not code_reader.is_code_file(str(real)):
            return False
    return any(real.is_relative_to(root) for root in import_roots())
