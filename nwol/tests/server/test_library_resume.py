# test_library_resume.py — La carte « Reprendre » : quel document, combien de temps.
#
# Elle prenait le premier document ouvert « au moins une fois » — `last_page`
# vaut 1 dès l'import, donc le dernier PDF importé, même jamais lu, passait
# devant le manuel en cours.


def _import(client, tmp_path, make_pdf, name: str, pages: int) -> int:
    path = make_pdf(tmp_path / name, [f"Page {n}" for n in range(1, pages + 1)])
    return client.post("/api/library/import", json={"path": path}).json()["id"]


def _read(doc_id: int, dwell: dict[int, float]) -> int:
    from db.page_dwell import save_page_dwell
    from db.sessions import start_session, update_session_progress

    sid = start_session(doc_id)
    save_page_dwell(sid, dwell, {page: 1 for page in dwell})
    update_session_progress(sid, pages_read=sum(1 for s in dwell.values() if s >= 5.0))
    return sid


def test_an_imported_but_unread_pdf_does_not_jump_ahead(client, tmp_path, make_pdf):
    from db.documents import update_last_page

    current = _import(client, tmp_path, make_pdf, "manuel.pdf", 8)
    _read(current, {p: 60.0 for p in range(1, 6)})
    update_last_page(current, 6)
    _import(client, tmp_path, make_pdf, "nouveau.pdf", 3)  # importé après, jamais lu

    payload = client.get("/api/library/resume").json()
    assert payload["document"]["id"] == current
    remaining = payload["remaining"]
    assert remaining["pages"] == 3  # pages 6, 7 et 8
    assert remaining["measured"] is True
    assert remaining["scope"] == "document"
    assert remaining["minutes"] == 3


def test_a_session_left_from_the_entry_sas_does_not_designate_the_document(client, tmp_path, make_pdf):
    from db.sessions import start_session

    read = _import(client, tmp_path, make_pdf, "lu.pdf", 4)
    _read(read, {1: 30.0})
    left = _import(client, tmp_path, make_pdf, "sas.pdf", 4)
    start_session(left)  # ouverte, rien lu

    assert client.get("/api/library/resume").json()["document"]["id"] == read


def test_nothing_read_yet_falls_back_to_the_most_recent(client, tmp_path, make_pdf):
    _import(client, tmp_path, make_pdf, "a.pdf", 2)
    latest = _import(client, tmp_path, make_pdf, "b.pdf", 5)

    payload = client.get("/api/library/resume").json()
    assert payload["document"]["id"] == latest
    assert payload["remaining"]["pages"] == 5
    assert payload["remaining"]["measured"] is False
    assert payload["remaining"]["scope"] == "default"


def test_an_empty_library_resumes_nothing(client):
    assert client.get("/api/library/resume").json() == {"document": None, "remaining": None}
