#!/usr/bin/env python3
# server/main.py — Démarrage du serveur local (uvicorn).
#
# Usage (depuis le dossier nwol/) :  python -m server.main
# Mono-process volontaire : la file LLM sérialise déjà le travail lourd, et un
# seul writer SQLite évite la contention pendant la migration.
from __future__ import annotations

import logging

import uvicorn

from server.app import create_app
from server.config import HOST, PORT


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(), host=HOST, port=PORT, workers=1, log_level="info")


if __name__ == "__main__":
    run()
