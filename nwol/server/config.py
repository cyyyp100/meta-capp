# server/config.py — Constantes du serveur local.
from __future__ import annotations

import sys
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8756  # port local fixe ; interne, jamais exposé à l'extérieur.

APP_VERSION = "1.3-web"

# Origines autorisées pendant le DÉVELOPPEMENT (Vite). En production (pywebview),
# le frontend est servi par ce même serveur → même origine, CORS inutile.
DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Bundle frontend compilé (servi en production s'il existe).
# En mode gelé (PyInstaller), les données sont extraites sous sys._MEIPASS.
if getattr(sys, "frozen", False):
    FRONTEND_DIST = Path(getattr(sys, "_MEIPASS", ".")) / "frontend" / "dist"
else:
    FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
