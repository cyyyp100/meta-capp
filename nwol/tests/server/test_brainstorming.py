# Tests de la page Brainstorming (REST + WebSocket avec LLM mocké).


# ── Fakes LLM (mêmes signatures callback que le code réel) ────────────────────

def _decide_no_search(history, user_message, on_success, on_error, model=None):
    on_success({"search": False, "queries": []})


def _decide_with_search(history, user_message, on_success, on_error, model=None):
    on_success({"search": True, "queries": ["vélo"]})


def _answer_fake(context, on_success, on_error, model=None):
    sources = context.get("sources") or []
    on_success(f"Réponse de test ({len(sources)} source(s)) : {context.get('user_message')}")


def _summarize_noop(previous_summary, new_messages, on_success, on_error, model=None):
    on_success("résumé de test")


# ── REST ──────────────────────────────────────────────────────────────────────

def test_brainstorm_crud(client):
    created = client.post("/api/brainstorming", json={"title": "Mon sujet"}).json()
    assert created["id"] >= 1
    assert created["title"] == "Mon sujet"

    listing = client.get("/api/brainstorming/discussions").json()
    assert any(d["id"] == created["id"] for d in listing)

    detail = client.get(f"/api/brainstorming/{created['id']}/messages").json()
    assert detail["title"] == "Mon sujet"
    assert detail["messages"] == []

    client.delete(f"/api/brainstorming/{created['id']}")
    assert client.get("/api/brainstorming/discussions").json() == []


def test_brainstorm_messages_404_on_unknown(client):
    assert client.get("/api/brainstorming/999/messages").status_code == 404


# ── WebSocket ─────────────────────────────────────────────────────────────────

def test_brainstorm_ws_answer_and_persist(client, monkeypatch):
    import services.brainstorm as svc

    monkeypatch.setattr(svc, "decide_brainstorm_search_async", _decide_no_search)
    monkeypatch.setattr(svc, "answer_brainstorm_async", _answer_fake)
    monkeypatch.setattr(svc, "summarize_brainstorm_async", _summarize_noop)

    did = client.post("/api/brainstorming", json={}).json()["id"]

    with client.websocket_connect(f"/api/brainstorming/{did}/stream") as ws:
        ws.send_json({"type": "ask", "question": "Idée sur le vélo"})
        assert ws.receive_json()["type"] == "loading"
        answer = ws.receive_json()
        assert answer["type"] == "answer"
        assert "vélo" in answer["answer"]
        assert answer["sources"] == []

    detail = client.get(f"/api/brainstorming/{did}/messages").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    # Auto-titre depuis la 1re question (discussion créée sans titre).
    assert detail["title"].startswith("Idée sur le vélo")


def test_brainstorm_ws_runs_db_search(client, monkeypatch):
    import services.brainstorm as svc

    captured = {}

    def _spy_search(query, *a, **k):
        captured["query"] = query
        return [{"source_type": "highlight", "doc_title": "PDF", "page": 3, "snippet": "passage vélo"}]

    monkeypatch.setattr(svc, "decide_brainstorm_search_async", _decide_with_search)
    monkeypatch.setattr(svc, "answer_brainstorm_async", _answer_fake)
    monkeypatch.setattr(svc, "summarize_brainstorm_async", _summarize_noop)
    monkeypatch.setattr(svc.brainstorm_search, "search_user_db", _spy_search)

    did = client.post("/api/brainstorming", json={"title": "Vélo"}).json()["id"]

    with client.websocket_connect(f"/api/brainstorming/{did}/stream") as ws:
        ws.send_json({"type": "ask", "question": "Parle-moi de vélo"})
        events = []
        # loading -> scanning(on) -> scanning(off) -> answer (ordre exact non garanti
        # pour les scanning, mais answer arrive en dernier).
        while True:
            evt = ws.receive_json()
            events.append(evt)
            if evt["type"] == "answer":
                break

    types = [e["type"] for e in events]
    assert "loading" in types
    assert "scanning" in types
    assert captured["query"] == "vélo"
    answer = events[-1]
    assert answer["sources"] and answer["sources"][0]["source_type"] == "highlight"
    assert "1 source" in answer["answer"]


def test_brainstorm_question_is_bounded(client, monkeypatch):
    """S4 : une question démesurée est TRONQUÉE, pas refusée.

    Le WebSocket du lecteur borne ses entrées depuis toujours (`ReaderMessage`) ;
    celui du brainstorming ne le faisait pas, et la chaîne partait telle quelle
    dans un prompt. On tronque plutôt que de fermer le socket : une question trop
    longue reste une question, et fermer ferait perdre la discussion."""
    from server.routers import brainstorming as router
    from services import brainstorm as svc

    seen: dict = {}

    def _capture(discussion_id, question, on_answer, on_error, on_scanning):
        seen["question"] = question
        on_answer({"answer": "ok", "sources": []})

    monkeypatch.setattr(svc, "handle_message", _capture)

    did = client.post("/api/brainstorming", json={"title": "Bornage"}).json()["id"]
    with client.websocket_connect(f"/api/brainstorming/{did}/stream") as ws:
        ws.send_json({"type": "ask", "question": "a" * 10_000})
        while ws.receive_json()["type"] != "answer":
            pass

    assert len(seen["question"]) == router._MAX_QUESTION_CHARS


def test_brainstorm_ignores_non_dict_message(client, monkeypatch):
    """Un message JSON qui n'est pas un objet ne doit pas faire tomber le socket.

    `msg.get(...)` sur une liste lève un AttributeError qui remontait jusqu'au
    gestionnaire d'exception du WebSocket et fermait le canal."""
    from services import brainstorm as svc

    def _answer(discussion_id, question, on_answer, on_error, on_scanning):
        on_answer({"answer": "ok", "sources": []})

    monkeypatch.setattr(svc, "handle_message", _answer)

    did = client.post("/api/brainstorming", json={"title": "Robuste"}).json()["id"]
    with client.websocket_connect(f"/api/brainstorming/{did}/stream") as ws:
        ws.send_json(["pas", "un", "objet"])   # ignoré
        ws.send_json({"type": "inconnu"})      # ignoré
        # Le socket est toujours vivant : un `ask` valide obtient sa réponse.
        ws.send_json({"type": "ask", "question": "toujours là ?"})
        while ws.receive_json()["type"] != "answer":
            pass
