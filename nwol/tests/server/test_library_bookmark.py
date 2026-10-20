"""Marque-page de reprise (POST /api/library/doc/{id}/bookmark).

Un seul par document, posé par l'élève, qui se déplace : le lecteur s'y
ouvre, l'accroche du sas porte sur sa page, et le temps restant en part. Il
est distinct de `last_page`, la page dominante à la fermeture, qui bouge seule.
"""


def _import(client, tmp_path, make_pdf, name="cours.pdf", pages=5):
    path = make_pdf(tmp_path / name, [f"Page {n}" for n in range(1, pages + 1)])
    return client.post("/api/library/import", json={"path": path}).json()["id"], path


def _bookmark(client, doc_id, page):
    return client.post(f"/api/library/doc/{doc_id}/bookmark", json={"page": page})


def test_a_document_has_no_bookmark_until_one_is_set(client, tmp_path, make_pdf):
    doc_id, _ = _import(client, tmp_path, make_pdf)

    assert client.get(f"/api/library/doc/{doc_id}").json()["bookmark_page"] is None
    listed = next(d for d in client.get("/api/library/documents").json() if d["id"] == doc_id)
    assert listed["bookmark_page"] is None


def test_set_move_and_remove_the_bookmark(client, tmp_path, make_pdf):
    doc_id, _ = _import(client, tmp_path, make_pdf)

    set_ = _bookmark(client, doc_id, 3)
    assert set_.status_code == 200
    assert set_.json()["ok"] is True
    assert set_.json()["document"]["bookmark_page"] == 3
    assert client.get(f"/api/library/doc/{doc_id}").json()["bookmark_page"] == 3

    moved = _bookmark(client, doc_id, 5)
    assert moved.json()["document"]["bookmark_page"] == 5, "un seul marque-page : il se déplace"

    removed = _bookmark(client, doc_id, None)
    assert removed.status_code == 200
    assert removed.json()["document"]["bookmark_page"] is None
    assert client.get(f"/api/library/doc/{doc_id}").json()["bookmark_page"] is None


def test_the_bookmark_is_distinct_from_the_last_page_seen(client, tmp_path, make_pdf):
    from db.documents import update_last_page

    doc_id, _ = _import(client, tmp_path, make_pdf)
    _bookmark(client, doc_id, 2)
    update_last_page(doc_id, 4)  # la fermeture du lecteur écrit sa page dominante

    detail = client.get(f"/api/library/doc/{doc_id}").json()
    assert (detail["bookmark_page"], detail["last_page"]) == (2, 4)


def test_a_page_outside_the_document_is_refused(client, tmp_path, make_pdf):
    doc_id, _ = _import(client, tmp_path, make_pdf)
    _bookmark(client, doc_id, 2)

    for page in (0, -1, 6):
        refused = _bookmark(client, doc_id, page)
        assert refused.status_code == 400, page
        assert refused.json()["detail"]
    assert client.get(f"/api/library/doc/{doc_id}").json()["bookmark_page"] == 2, "un refus ne change rien"


def test_an_unknown_document_is_404(client):
    assert _bookmark(client, 999, 1).status_code == 404
    assert _bookmark(client, 999, None).status_code == 404


def test_the_bookmark_follows_a_document_that_lost_pages(client, tmp_path, make_pdf):
    """PDF réécrit sur place (rapport recompilé) : le marque-page au-delà de la
    nouvelle fin est ramené à la dernière page ; sans marque-page, il n'en
    apparaît pas."""
    doc_id, path = _import(client, tmp_path, make_pdf)
    other_id, other_path = _import(client, tmp_path, make_pdf, name="autre.pdf")
    _bookmark(client, doc_id, 5)

    make_pdf(tmp_path / "cours.pdf", ["Page 1", "Page 2"])
    make_pdf(tmp_path / "autre.pdf", ["Page 1", "Page 2"])

    detail = client.get(f"/api/library/doc/{doc_id}").json()
    assert detail["page_count"] == 2
    assert detail["bookmark_page"] == 2
    from db.documents import get_document

    assert get_document(doc_id)["bookmark_page"] == 2, "borné en base aussi"
    assert client.get(f"/api/library/doc/{other_id}").json()["bookmark_page"] is None


def test_a_relinked_document_keeps_its_bookmark(client, tmp_path, make_pdf):
    """Fichier déplacé puis « Localiser le fichier » : même document, même id,
    même marque-page."""
    doc_id, path = _import(client, tmp_path, make_pdf)
    _bookmark(client, doc_id, 4)
    moved = tmp_path / "ailleurs" / "cours.pdf"
    moved.parent.mkdir()
    (tmp_path / "cours.pdf").rename(moved)

    relinked = client.post(f"/api/library/doc/{doc_id}/relink", json={"path": str(moved)})
    assert relinked.status_code == 200, relinked.text
    assert relinked.json()["document"]["id"] == doc_id
    assert relinked.json()["document"]["bookmark_page"] == 4


def test_the_resume_card_counts_from_the_bookmark(client, tmp_path, make_pdf):
    doc_id, _ = _import(client, tmp_path, make_pdf, pages=10)
    _bookmark(client, doc_id, 7)

    resume = client.get("/api/library/resume").json()
    assert resume["document"]["bookmark_page"] == 7
    assert resume["remaining"]["pages"] == 4  # la page 7 reste à lire, jusqu'à la 10
