# S4 : les messages WS malformés sont ignorés (canal ouvert), les champs bornés.
def test_malformed_messages_ignored_channel_stays_open(client, monkeypatch):
    from services import assistant

    monkeypatch.setattr(
        assistant, "answer_question",
        lambda d, p, q, ok, err, **kw: ok({"answer": f"len={len(q)}", "highlights": []}),
    )
    with client.websocket_connect("/api/reader/1/stream") as ws:
        # Salves de messages invalides : type inconnu, page non numérique,
        # payload non-dict… aucun ne doit fermer le canal.
        ws.send_json({"type": "exploit", "page": "DROP TABLE"})
        ws.send_json({"type": "ask"})  # question absente
        ws.send_json([1, 2, 3])
        ws.send_json({"page": 4})  # type absent
        # Le canal répond toujours normalement.
        ws.send_json({"type": "ask", "question": "ping", "page": "pas-un-nombre"})
        assert ws.receive_json()["type"] == "loading"
        assert ws.receive_json()["type"] == "answer"


def test_oversized_question_is_truncated(client, monkeypatch):
    from server.routers.reading import _MAX_QUESTION_CHARS
    from services import assistant

    seen = {}

    def spy(doc_id, page, question, ok, err, **kw):
        seen["len"] = len(question)
        ok({"answer": "ok", "highlights": []})

    monkeypatch.setattr(assistant, "answer_question", spy)
    with client.websocket_connect("/api/reader/1/stream") as ws:
        ws.send_json({"type": "ask", "question": "x" * (_MAX_QUESTION_CHARS * 3), "page": 1})
        ws.receive_json()
        ws.receive_json()
    assert seen["len"] == _MAX_QUESTION_CHARS


def test_snippets_capped_and_cleaned(client, monkeypatch):
    from services import assistant

    seen = {}

    def spy(doc_id, page, question, ok, err, selected_snippets=None, **kw):
        seen["snippets"] = selected_snippets
        ok({"answer": "ok", "highlights": []})

    monkeypatch.setattr(assistant, "answer_question", spy)
    with client.websocket_connect("/api/reader/1/stream") as ws:
        ws.send_json({
            "type": "ask",
            "question": "q",
            "page": 1,
            "selected_snippets": ["  a  ", "", "b", 3, "d", "e", "f", "g"],
        })
        ws.receive_json()
        ws.receive_json()
    assert len(seen["snippets"]) == 5
    assert seen["snippets"][0] == "a"
