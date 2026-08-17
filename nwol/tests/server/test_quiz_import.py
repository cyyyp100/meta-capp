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

    # Sans catégorie : pas de matière mise à jour — mais la rétention bouge quand même.
    body = client.post("/api/quiz/answer", json={"correct": True}).json()
    assert body["updated"] is False
    assert "level" not in body
    assert 0.0 <= body["retention"] <= 100.0


def test_quiz_answer_moves_permanent_retention(client):
    # Un quiz de révision est une mesure directe de la mémorisation : il doit
    # faire bouger le critère `retention` du profil long terme (comportement
    # présent en Tk, absent du web avant l'unification).
    good = client.post("/api/quiz/answer", json={"correct": True}).json()["retention"]
    bad = client.post("/api/quiz/answer", json={"correct": False}).json()["retention"]
    assert bad < good


def test_import_pdf(client, tmp_path):
    import fitz

    pdf_path = tmp_path / "mini.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Bonjour Meta-Capp")
    doc.save(str(pdf_path))
    doc.close()

    resp = client.post("/api/library/import", json={"path": str(pdf_path)})
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
