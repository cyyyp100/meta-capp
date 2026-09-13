# Annulation d'une génération EN VOL.
#
# `cancel_pending_generations()` se contentait d'invalider un token : les tâches
# encore en file étaient jetées, mais celle déjà partie chez Ollama tournait
# jusqu'au bout — GPU occupé, et la première réponse du document suivant
# attendait derrière. Ces tests figent le nouveau contrat : la socket est coupée,
# l'appel en vol se termine tout de suite par `GenerationCancelled`, et rien
# n'est rejoué.
from __future__ import annotations

import socket
import threading
import time

import pytest


@pytest.fixture
def silent_server(monkeypatch):
    """Un « Ollama » qui accepte la connexion, lit la requête et ne répond jamais."""
    from llm import ollama_client

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    accepted: list[socket.socket] = []
    stop = threading.Event()

    def serve() -> None:
        srv.settimeout(0.1)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            accepted.append(conn)
            conn.settimeout(0.1)
            while not stop.is_set():
                try:
                    if not conn.recv(4096):
                        break
                except socket.timeout:
                    continue
                except OSError:
                    break

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    monkeypatch.setattr(ollama_client, "OLLAMA_URL", f"http://127.0.0.1:{port}/api/generate")
    # Un timeout socket confortable : c'est l'annulation qui doit terminer l'appel.
    monkeypatch.setattr(ollama_client, "task_timeout_s", lambda _task: 30.0)
    yield accepted
    stop.set()
    thread.join(timeout=2)
    for conn in accepted:
        conn.close()
    srv.close()


def test_cancel_cuts_the_inflight_call_immediately(silent_server):
    from llm import ollama_client

    outcome: dict = {}

    def call() -> None:
        try:
            ollama_client._call_ollama_http("prompt", "model", task="question")
        except Exception as exc:  # noqa: BLE001 - on veut le type exact
            outcome["exc"] = exc

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    # Attendre que la requête soit réellement partie (connexion acceptée).
    deadline = time.monotonic() + 3
    while not silent_server and time.monotonic() < deadline:
        time.sleep(0.01)
    assert silent_server, "la connexion n'a jamais atteint le serveur"

    t0 = time.monotonic()
    ollama_client.cancel_pending_generations()
    worker.join(timeout=3)

    assert not worker.is_alive(), "l'appel en vol est resté bloqué malgré l'annulation"
    assert time.monotonic() - t0 < 2
    assert isinstance(outcome.get("exc"), ollama_client.GenerationCancelled)


def test_cancelled_generation_is_not_retried(monkeypatch):
    """`_generate_json` rejoue une panne ; une annulation, jamais."""
    from llm import ollama_client

    calls = []

    def cut(*_a, **_k):
        calls.append(1)
        raise ollama_client.GenerationCancelled("coupée")

    monkeypatch.setattr(ollama_client, "_call_ollama", cut)
    with pytest.raises(ollama_client.GenerationCancelled):
        ollama_client._generate_json("question", "p", lambda raw: {}, model="m", retries=3)
    assert len(calls) == 1


def test_cancel_without_inflight_call_is_harmless():
    from llm import ollama_client

    before = ollama_client._generation_token
    ollama_client.cancel_pending_generations()
    assert ollama_client._generation_token == before + 1
