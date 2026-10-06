def test_quiz_questions_list(client):
    qs = client.get("/api/quiz/questions", params={"n": 5}).json()
    assert isinstance(qs, list)
    for q in qs:
        assert "question" in q


def test_quiz_answer_updates_subject(client):
    resp = client.post("/api/quiz/answer", json={"category": "mathématiques", "correct": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated"] is True
    assert 0.0 <= body["level"] <= 100.0

    # Sans catégorie : pas de matière mise à jour.
    body = client.post("/api/quiz/answer", json={"correct": True}).json()
    assert body["updated"] is False
    assert "level" not in body


def test_quiz_session_moves_permanent_retention(client):
    # Un quiz de révision est une mesure directe de la mémorisation : il fait
    # bouger le critère `retention` du profil long terme — par la courbe de
    # jauges de la séance, à sa clôture, et non plus réponse par réponse.
    from db.metacog import ensure_profile

    def _quiz(verdict: str) -> float:
        answers = [{"question": f"Q{i} ?", "question_type": "qcm", "verdict": verdict} for i in range(5)]
        sid = client.post("/api/quiz/session", json={"answers": answers}).json()["session_id"]
        client.post("/api/quiz/finalize", json={"session_id": sid})
        return float(ensure_profile()["retention"])

    good = _quiz("correct")
    assert good > 50.0
    assert _quiz("incorrect") < good


def test_import_pdf(client, tmp_path, make_pdf):
    pdf_path = make_pdf(tmp_path / "mini.pdf", ["Bonjour Meta-Capp"])

    resp = client.post("/api/library/import", json={"path": pdf_path})
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["page_count"] == 1
    assert len(detail["page_sizes_pts"]) == 1

    recent = client.get("/api/library/recent").json()
    assert any(d["id"] == detail["id"] for d in recent)

    # Recherche de surlignage : le texte inséré doit être localisé sur la page 1.
    search = client.get(f"/api/library/doc/{detail['id']}/page/1/search", params={"q": "Bonjour"}).json()
    assert len(search["rects_pts"]) >= 1
    assert len(search["rects_pts"][0]) == 4

    # Chemin inexistant -> 400.
    assert client.post("/api/library/import", json={"path": "/does/not/exist.pdf"}).status_code == 400
