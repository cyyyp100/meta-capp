# test_reader_find_api.py — Les deux routes du Ctrl/Cmd+F du lecteur.
#
# Le résumé du document (`/find`) et les occurrences d'une page
# (`/page/{n}/find`). La politique est dans services/reader_find ; ici, les
# formes de réponse, le document inconnu (404) et la requête trop longue (422).


def _import(client, tmp_path, make_pdf) -> int:
    path = make_pdf(tmp_path / "cours.pdf", ["Une Équation différen-\ntielle.", "Une autre equation."])
    return client.post("/api/library/import", json={"path": path}).json()["id"]


def test_the_document_summary(client, tmp_path, make_pdf):
    doc_id = _import(client, tmp_path, make_pdf)
    res = client.get(f"/api/library/doc/{doc_id}/find", params={"q": "équation"})
    assert res.status_code == 200
    assert res.json() == {
        "query": "equation",
        "total": 2,
        "pages": [{"page": 1, "count": 1}, {"page": 2, "count": 1}],
        "searchable": True,
        "too_short": False,
    }
    assert client.get(f"/api/library/doc/{doc_id}/find", params={"q": "x"}).json()["too_short"] is True


def test_the_occurrences_of_a_page(client, tmp_path, make_pdf):
    doc_id = _import(client, tmp_path, make_pdf)
    body = client.get(f"/api/library/doc/{doc_id}/page/1/find", params={"q": "differentielle"}).json()
    assert body["page"] == 1 and body["truncated"] is False
    assert len(body["rects"]) == 1 and len(body["rects"][0]) == 2  # à cheval sur deux lignes
    assert all(len(rect) == 4 for rect in body["rects"][0])


def test_a_code_file_answers_ranges(client, tmp_path):
    path = tmp_path / "demo.py"
    path.write_text("def equation():\n    return 'Équation'\n", encoding="utf-8")
    doc_id = client.post("/api/library/import", json={"path": str(path)}).json()["id"]
    body = client.get(f"/api/library/doc/{doc_id}/page/1/find", params={"q": "equation"}).json()
    assert body == {"page": 1, "ranges": [[4, 12], [28, 36]], "truncated": False}


def test_an_unknown_document_is_a_404(client):
    assert client.get("/api/library/doc/999/find", params={"q": "equation"}).status_code == 404
    assert client.get("/api/library/doc/999/page/1/find", params={"q": "equation"}).status_code == 404


def test_a_query_beyond_the_limit_is_refused(client, tmp_path, make_pdf):
    from config.settings import READER_FIND_MAX_QUERY_CHARS

    doc_id = _import(client, tmp_path, make_pdf)
    too_long = "a" * (READER_FIND_MAX_QUERY_CHARS + 1)
    assert client.get(f"/api/library/doc/{doc_id}/find", params={"q": too_long}).status_code == 422
    assert client.get(f"/api/library/doc/{doc_id}/page/1/find", params={"q": too_long}).status_code == 422
