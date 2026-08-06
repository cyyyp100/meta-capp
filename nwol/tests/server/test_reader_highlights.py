def test_reader_highlights_crud(client):
    # Cycle complet : liste vide -> création -> relecture -> suppression.
    from db.documents import upsert_document

    doc_id = upsert_document("/tmp/hl.pdf", "hl.pdf", 3, "pymupdf", False)

    assert client.get(f"/api/library/doc/{doc_id}/highlights").json() == []

    created = client.post(
        f"/api/library/doc/{doc_id}/highlights",
        json={"page": 2, "quote": "un passage clé", "rects": [[10, 20, 100, 30]], "color": "key"},
    ).json()
    hid = created["id"]
    assert hid > 0

    items = client.get(f"/api/library/doc/{doc_id}/highlights").json()
    assert len(items) == 1
    assert items[0]["quote"] == "un passage clé"
    assert items[0]["page"] == 2
    assert items[0]["rects"] == [[10, 20, 100, 30]]

    removed = client.delete(f"/api/library/doc/{doc_id}/highlights/{hid}").json()
    assert removed["removed"] == 1
    assert client.get(f"/api/library/doc/{doc_id}/highlights").json() == []


def test_answer_context_includes_user_highlights(client):
    # Les surlignages mémorisés enrichissent le contexte de réponse du LLM.
    from db.documents import upsert_document
    from db.reader_highlights import add_highlight
    from services.assistant import build_answer_context

    doc_id = upsert_document("/tmp/hl2.pdf", "hl2.pdf", 3, "pymupdf", False)
    add_highlight(doc_id, 1, "passage surligné par l'étudiant", [[1, 2, 3, 4]])

    ctx = build_answer_context(doc_id, 1, "Une question")
    assert "passage surligné par l'étudiant" in ctx["user_highlights"]


def test_highlight_color_is_validated(client):
    # Une couleur inconnue retombe sur 'key'.
    from db.documents import upsert_document
    from db.reader_highlights import add_highlight, list_highlights

    doc_id = upsert_document("/tmp/hl3.pdf", "hl3.pdf", 3, "pymupdf", False)
    add_highlight(doc_id, 1, "abc", [[0, 0, 1, 1]], color="rainbow")
    items = list_highlights(doc_id)
    assert items[0]["color"] == "key"


def test_highlight_anchor_roundtrip(client):
    # Ancrage texte {block_id,start,end} persisté et relu (documents servis en
    # blocs) ; absent (null) pour les surlignages raster.
    from db.documents import upsert_document

    doc_id = upsert_document("/tmp/hl4.py", "hl4.py", 3, "code", False)
    created = client.post(
        f"/api/library/doc/{doc_id}/highlights",
        json={
            "page": 1,
            "quote": "théorème central limite",
            "rects": [],
            "color": "key",
            "anchor": {"block_id": "p1_b003", "start": 12, "end": 36},
        },
    ).json()
    assert created["id"] > 0

    client.post(
        f"/api/library/doc/{doc_id}/highlights",
        json={"page": 2, "quote": "sans ancre", "rects": [[1, 2, 3, 4]]},
    )

    items = client.get(f"/api/library/doc/{doc_id}/highlights").json()
    anchored = next(i for i in items if i["quote"] == "théorème central limite")
    assert anchored["anchor"] == {"block_id": "p1_b003", "start": 12, "end": 36}
    assert anchored["rects"] == []
    legacy = next(i for i in items if i["quote"] == "sans ancre")
    assert legacy["anchor"] is None
