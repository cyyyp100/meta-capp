# Dégradation gracieuse quand Ollama est absent (les tests CI n'ont JAMAIS de
# LLM) : les endpoints doivent répondre proprement, pas de 500.
import pytest


def test_run_llm_sync_success_and_error_paths():
    from services.llm_bridge import run_llm_sync

    assert run_llm_sync(lambda ok, err: ok({"answer": "x"}), timeout=1) == {"answer": "x"}

    with pytest.raises(RuntimeError):
        run_llm_sync(lambda ok, err: err("Ollama indisponible"), timeout=1)

    with pytest.raises(TimeoutError):
        run_llm_sync(lambda ok, err: None, timeout=0.05)  # aucun callback (LLM muet)


def test_hook_endpoint_returns_empty_when_llm_down(client, monkeypatch):
    # curiosity_hook signale l'échec (Ollama down) -> le routeur renvoie "".
    from services import assistant

    def failing_hook(doc_id, page, on_success, on_error, **_kw):
        on_error("connexion refusée")

    monkeypatch.setattr(assistant, "curiosity_hook", failing_hook)
    # L'import du routeur est fait à l'intérieur du endpoint : patcher le service suffit.
    import server.routers.library as library_router

    monkeypatch.setattr(library_router, "curiosity_hook", failing_hook, raising=False)
    res = client.get("/api/library/doc/1/hook")
    assert res.status_code == 200
    assert res.json() == {"hook": ""}


def test_health_reports_llm_offline_without_failing(client):
    # Sans Ollama, /api/health doit répondre 200 (état LLM = dégradé, pas erreur).
    res = client.get("/api/health")
    assert res.status_code == 200


def test_reader_ws_reports_llm_error_as_event(client, monkeypatch):
    # Une erreur LLM sur une question doit devenir un événement {"type": "error"}
    # côté client, pas une fermeture brutale du WebSocket.
    from services import assistant

    monkeypatch.setattr(
        assistant, "answer_question",
        lambda d, p, q, ok, err, **kw: err("Ollama absent"),
    )
    with client.websocket_connect("/api/reader/1/stream") as ws:
        ws.send_json({"type": "ask", "question": "test ?", "page": 1})
        assert ws.receive_json()["type"] == "loading"
        evt = ws.receive_json()
        assert evt["type"] == "error"
        assert "Ollama" in evt["message"]
