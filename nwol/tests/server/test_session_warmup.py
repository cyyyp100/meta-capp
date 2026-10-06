# La révision éclair, du lecteur au profil : `start_reading` porte les temps,
# le serveur les juge une fois, les jauges live en portent l'effet, le bilan de
# Clikoda les reçoit et la note de métacognition du sas de sortie les garde.
from config.settings import WARMUP_RUSH_ATTENTION, WARMUP_RUSH_META

SPAMMED = {"front_ms": 200, "back_ms": 150}  # cliquée sans lire, recto et verso


def _session_with_card(client, tmp_path, make_pdf) -> tuple[int, int, int]:
    from services.flashcards import create_flashcard

    path = make_pdf(tmp_path / "warmup.pdf", ["Contenu de test"])
    doc_id = client.post("/api/library/import", json={"path": path}).json()["id"]
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    card = create_flashcard(front="Quel pourcentage minimal d'occupation retient une coupe ?", back="5 %")
    return doc_id, sid, card


def _sync(ws) -> None:
    """Aller-retour sur le canal : tout message envoyé avant est traité."""
    ws.send_json({"type": "mode", "mode": "normal"})
    while ws.receive_json()["type"] != "system":
        pass


def test_start_reading_judges_the_warmup_once_and_moves_the_live_gauges(client, tmp_path, make_pdf):
    from db.session_gauges import get_first_gauges, get_latest_gauges
    from db.session_warmup import get_session_warmup

    doc_id, sid, card = _session_with_card(client, tmp_path, make_pdf)
    warmup = [{"card_id": card, **SPAMMED}]

    with client.websocket_connect(f"/api/reader/{doc_id}/stream") as ws:
        ws.send_json({"type": "start_reading", "session_id": sid, "warmup": warmup})
        ws.send_json({"type": "start_reading", "session_id": sid, "warmup": warmup})  # renvoi
        _sync(ws)

    rows = get_session_warmup(sid)
    assert [(r["front_pace"], r["back_pace"]) for r in rows] == [("rushed", "rushed")]
    seed, latest = get_first_gauges(sid), get_latest_gauges(sid)
    # Versé une fois, APRÈS l'amorce : la finalisation y voit une jauge exercée.
    assert latest["attention"] == seed["attention"] - 2 * WARMUP_RUSH_ATTENTION
    assert latest["meta_cognition"] == seed["meta_cognition"] - 2 * WARMUP_RUSH_META
    assert latest["retention"] == seed["retention"]


def test_a_warmup_sent_before_the_session_id_waits_for_it(client, tmp_path, make_pdf):
    from db.session_warmup import get_session_warmup

    doc_id, sid, card = _session_with_card(client, tmp_path, make_pdf)

    with client.websocket_connect(f"/api/reader/{doc_id}/stream") as ws:
        # La création de séance était encore en vol à la sortie du sas.
        ws.send_json({"type": "start_reading", "warmup": [{"card_id": card, **SPAMMED}]})
        _sync(ws)
        assert get_session_warmup(sid) == []
        ws.send_json({"type": "viewport", "page": 1, "session_id": sid})
        _sync(ws)

    assert len(get_session_warmup(sid)) == 1


def test_malformed_warmup_entries_are_dropped_not_the_message(client, tmp_path, make_pdf):
    from db.session_warmup import get_session_warmup

    doc_id, sid, card = _session_with_card(client, tmp_path, make_pdf)
    warmup = [{"card_id": "x"}, {"card_id": card, "front_ms": 10**12, "back_ms": -5}]

    with client.websocket_connect(f"/api/reader/{doc_id}/stream") as ws:
        ws.send_json({"type": "start_reading", "session_id": sid, "warmup": warmup})
        _sync(ws)

    rows = get_session_warmup(sid)
    assert len(rows) == 1
    assert rows[0]["front_ms"] == 3_600_000  # borné à une heure
    assert rows[0]["back_ms"] == 0


def test_the_session_debrief_receives_the_warmup(client, monkeypatch):
    from db.documents import upsert_document
    from db.sessions import start_session
    from llm import ollama_client
    from services import session, warmup

    doc_id = upsert_document("/tmp/debrief.pdf", "debrief.pdf", 3, "pdfium", False)
    sid = start_session(doc_id)
    warmup.record(sid, [{"card_id": 0, "front_ms": 4_000, "back_ms": 90_000}])

    seen: dict = {}

    def fake_summary(context, on_success, _on_error):
        seen.update(context["session_data"])
        on_success({"session_summary": {"qualitative_summary": "ok", "metacognitive_questions": []}})

    monkeypatch.setattr(ollama_client, "generate_session_summary_async", fake_summary)
    session.session_analysis(sid)

    assert seen["warmup"]["cards"] == 1
    assert seen["warmup"]["total_s"] == 94.0
    assert seen["warmup"]["per_card"][0]["answer_pace"] == "drifted"


def test_the_exit_reflection_score_keeps_the_warmup_cost(client, monkeypatch):
    """La note du sas de sortie REMPLACE la jauge live de métacognition : sans
    report, une révision cliquée sans lire s'effaçait dès qu'on écrivait."""
    from db.answers import save_answer
    from db.documents import upsert_document
    from db.session_gauges import record_gauges
    from db.sessions import start_session
    from services import session, warmup

    doc_id = upsert_document("/tmp/meta.pdf", "meta.pdf", 3, "pdfium", False)
    sid = start_session(doc_id)
    record_gauges(sid, {"meta_cognition": 40.0}, t=0.0)
    record_gauges(sid, {"meta_cognition": 37.0}, t=1.0)
    save_answer(question_id=None, user_id=1, answer_text="a", verdict="correct", session_id=sid)
    warmup.record(sid, [{"card_id": 0, **SPAMMED}])

    monkeypatch.setattr(session, "_measure_meta_cognition", lambda *_a, **_k: 70.0)
    captured: dict = {}

    def fake_update_profile(_user_id, session_score, _sid, confidence=1.0, **_kwargs):
        captured.update(session_score)
        return session_score

    monkeypatch.setattr(session, "update_profile", fake_update_profile)
    session.finalize_session(sid, ["J'ai compris l'essentiel."])

    assert captured["meta_cognition"] == 70.0 - 2 * WARMUP_RUSH_META
