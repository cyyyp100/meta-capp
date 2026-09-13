"""Suppression d'un document de la bibliothèque (DELETE /api/library/doc/{id}).

Le geste part d'un clic droit sur la carte. Ce qu'il emporte, ce qu'il laisse :
le fichier de l'utilisateur n'est JAMAIS touché, les flashcards survivent
(détachées), les sessions et questions du document partent avec lui.
"""
import os


def _import_doc(client, tmp_path, make_pdf, name="a-supprimer.pdf"):
    path = make_pdf(tmp_path / name, ["Contenu à supprimer"])
    return client.post("/api/library/import", json={"path": path}).json()["id"], path


def test_delete_removes_the_document_but_not_the_file(client, tmp_path, make_pdf):
    doc_id, path = _import_doc(client, tmp_path, make_pdf)
    assert any(d["id"] == doc_id for d in client.get("/api/library/documents").json())

    response = client.delete(f"/api/library/doc/{doc_id}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "id": doc_id}
    assert all(d["id"] != doc_id for d in client.get("/api/library/documents").json())
    assert client.get(f"/api/library/doc/{doc_id}").status_code == 404
    assert os.path.exists(path), "le PDF de l'utilisateur doit rester sur le disque"


def test_delete_unknown_document_is_404(client):
    assert client.delete("/api/library/doc/9999").status_code == 404


def test_delete_cascades_sessions_and_detaches_flashcards(client, tmp_path, make_pdf):
    from db.flashcards import get_flashcard, save_flashcard
    from db.sessions import get_session

    doc_id, _ = _import_doc(client, tmp_path, make_pdf)
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    card_id = save_flashcard(1, None, front="Q", back="R", document_id=doc_id, session_id=sid)

    assert client.delete(f"/api/library/doc/{doc_id}").status_code == 200

    assert get_session(sid) is None
    card = get_flashcard(card_id)
    assert card is not None, "les flashcards appartiennent aux révisions, pas au document"
    assert card["document_id"] is None


def test_delete_purges_the_rendered_pages(client, tmp_path, make_pdf):
    from pdf_viewer.page_renderer import page_cache_dir

    doc_id, path = _import_doc(client, tmp_path, make_pdf)
    assert client.get(f"/api/library/doc/{doc_id}/page/1.png?zoom=0.5").status_code == 200
    cache = page_cache_dir(path)
    assert any(cache.glob("page_*.png"))

    client.delete(f"/api/library/doc/{doc_id}")

    assert not any(cache.glob("page_*.png"))
