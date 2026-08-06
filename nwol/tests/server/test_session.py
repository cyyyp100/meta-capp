def _import_doc(client, tmp_path):
    import fitz

    p = tmp_path / "m.pdf"
    d = fitz.open()
    page = d.new_page()
    page.insert_text((72, 72), "Contenu de test")
    d.save(str(p))
    d.close()
    return client.post("/api/library/import", json={"path": str(p)}).json()["id"]


def test_session_lifecycle_and_metrics(client, tmp_path):
    doc_id = _import_doc(client, tmp_path)
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    assert isinstance(sid, int)

    # Semer des réponses pour cette session.
    from db.answers import save_answer

    save_answer(question_id=None, user_id=1, answer_text="a", verdict="correct", session_id=sid)
    save_answer(question_id=None, user_id=1, answer_text="b", verdict="partial", session_id=sid)
    save_answer(question_id=None, user_id=1, answer_text="c", verdict="incorrect", session_id=sid)

    m = client.post(f"/api/session/{sid}/end", json={"pages_read": 5, "duration_s": 120}).json()
    assert m["pages_read"] == 5
    assert m["duration_s"] == 120
    assert m["questions_answered"] == 3
    assert m["correct"] == 1
    assert m["success_rate"] == 50  # round(100*(1 + 0.5)/3)
    assert len(m["reflection_questions"]) == 3


def test_session_finalize_updates_profile(client, tmp_path):
    from db.metacog import get_profile
    from db.session_reflections import get_session_reflections

    doc_id = _import_doc(client, tmp_path)
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    before = (get_profile(1) or {}).get("sessions_count", 0)

    client.post(f"/api/session/{sid}/end", json={"pages_read": 3, "duration_s": 60})
    f = client.post(f"/api/session/{sid}/finalize", json={"responses": ["r1", "", "r3"]}).json()
    assert f["ok"] is True

    assert (get_profile(1) or {})["sessions_count"] == before + 1
    # 2 réponses non vides enregistrées.
    assert len(get_session_reflections(sid)) == 2


def test_finalize_nudges_profile_from_session_gauges(client):
    # Quand des jauges live ont été enregistrées, le profil complet glisse vers elles
    # (pas seulement les 3 critères du repli taux-de-réussite).
    from db.documents import upsert_document
    from db.metacog import get_profile
    from db.session_gauges import record_gauges
    from db.sessions import start_session
    from services.session import finalize_session

    doc_id = upsert_document("/tmp/nudge.pdf", "nudge.pdf", 5, "pymupdf", False)
    sid = start_session(doc_id)
    before = float((get_profile(1) or {})["creativity"])  # 50.0 par défaut
    record_gauges(sid, {"creativity": 80.0, "attention": 80.0}, t=1.0)

    finalize_session(sid, ["a", "b", "c"])

    after = float((get_profile(1) or {})["creativity"])
    assert after > before  # creativity tirée vers 80 (hors critères du repli)


def test_streak_endpoint(client):
    assert client.get("/api/streak").json()["streak"] >= 1
