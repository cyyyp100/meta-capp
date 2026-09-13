"""Renommage d'un document de la bibliothèque (POST /api/library/doc/{id}/rename).

Le geste part du clic droit sur la carte. C'est le TITRE qui change, jamais le
fichier de l'utilisateur ; le nouveau titre doit se voir partout où la base
affiche un document (catalogue, recherche, flashcards) et SURVIVRE à un
ré-import du même chemin.
"""
import os


def _import_doc(client, tmp_path, make_pdf, name="a-renommer.pdf"):
    path = make_pdf(tmp_path / name, ["Contenu à renommer"])
    return client.post("/api/library/import", json={"path": path}).json()["id"], path


def test_rename_changes_the_title_everywhere_but_not_the_file(client, tmp_path, make_pdf):
    doc_id, path = _import_doc(client, tmp_path, make_pdf)

    response = client.post(f"/api/library/doc/{doc_id}/rename", json={"title": "  Analyse —  chapitre 3 "})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # Blancs repliés, comme un nom de dossier.
    assert body["document"]["title"] == "Analyse — chapitre 3"
    assert client.get(f"/api/library/doc/{doc_id}").json()["title"] == "Analyse — chapitre 3"
    listed = next(d for d in client.get("/api/library/documents").json() if d["id"] == doc_id)
    assert listed["title"] == "Analyse — chapitre 3"
    # La recherche pèse le titre en premier : elle doit connaître le nouveau.
    assert any(d["id"] == doc_id for d in client.get("/api/library/search", params={"q": "analyse"}).json())
    assert os.path.exists(path) and os.path.basename(path) == "a-renommer.pdf"


def test_rename_survives_a_reimport_of_the_same_path(client, tmp_path, make_pdf):
    doc_id, path = _import_doc(client, tmp_path, make_pdf)
    client.post(f"/api/library/doc/{doc_id}/rename", json={"title": "Mon titre"})

    again = client.post("/api/library/import", json={"path": path}).json()

    assert again["id"] == doc_id
    assert again["title"] == "Mon titre", "ré-importer ne doit pas défaire un renommage"


def test_rename_propagates_to_flashcards_document_title(client, tmp_path, make_pdf):
    from services.flashcards import create_flashcard, list_flashcards

    doc_id, _ = _import_doc(client, tmp_path, make_pdf)
    card_id = create_flashcard(front="Q", back="R", document_id=doc_id)
    client.post(f"/api/library/doc/{doc_id}/rename", json={"title": "Titre choisi"})

    card = next(c for c in list_flashcards() if c["id"] == card_id)
    assert card["document_title"] == "Titre choisi"


def test_rename_rejects_an_empty_title(client, tmp_path, make_pdf):
    doc_id, _ = _import_doc(client, tmp_path, make_pdf)
    assert client.post(f"/api/library/doc/{doc_id}/rename", json={"title": "   "}).status_code == 400
    assert client.get(f"/api/library/doc/{doc_id}").json()["title"] == "a-renommer.pdf"


def test_rename_unknown_document_is_404(client):
    assert client.post("/api/library/doc/9999/rename", json={"title": "X"}).status_code == 404
