"""API des dossiers de bibliothèque et de la recherche (/api/library/...).

Le garde-fou de cycle est testé ICI en plus du service : le client refuse le
dépôt illégal pour l'ergonomie, mais c'est le serveur qui fait foi — un appel
forgé à la main doit être rejeté.
"""


def _create(client, name, parent_id=None):
    response = client.post("/api/library/folders", json={"name": name, "parent_id": parent_id})
    assert response.status_code == 200, response.text
    return response.json()


def _document(client, filename="cours.pdf"):
    from db.documents import upsert_document

    return upsert_document(f"/tmp/{filename}", filename, 10, "pymupdf_scroll", False)


def test_folders_start_empty(client):
    assert client.get("/api/library/folders").json() == []


def test_create_nested_folders_and_read_the_tree(client):
    maths = _create(client, "Maths")
    _create(client, "Algèbre", parent_id=maths["id"])

    tree = client.get("/api/library/folders").json()
    assert [f["name"] for f in tree] == ["Maths"]
    assert [c["name"] for c in tree[0]["children"]] == ["Algèbre"]


def test_rename_and_move_a_folder(client):
    maths = _create(client, "Maths")
    physique = _create(client, "Physique")

    renamed = client.post(f"/api/library/folders/{physique['id']}/rename", json={"name": "Physique-chimie"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Physique-chimie"

    moved = client.post(f"/api/library/folders/{physique['id']}/move", json={"parent_id": maths["id"]})
    assert moved.status_code == 200
    assert moved.json()["parent_id"] == maths["id"]


def test_moving_a_folder_into_its_own_descendant_is_rejected(client):
    maths = _create(client, "Maths")
    algebre = _create(client, "Algèbre", parent_id=maths["id"])

    response = client.post(f"/api/library/folders/{maths['id']}/move", json={"parent_id": algebre["id"]})

    assert response.status_code == 400
    assert "sous-dossier" in response.json()["detail"]


def test_move_a_document_into_a_folder_and_back(client):
    folder = _create(client, "Maths")
    doc_id = _document(client)

    moved = client.post(f"/api/library/doc/{doc_id}/folder", json={"folder_id": folder["id"]})
    assert moved.status_code == 200
    assert moved.json()["document"]["folder_id"] == folder["id"]

    back = client.post(f"/api/library/doc/{doc_id}/folder", json={"folder_id": None})
    assert back.json()["document"]["folder_id"] is None


def test_moving_a_document_to_an_unknown_folder_is_rejected(client):
    doc_id = _document(client)

    response = client.post(f"/api/library/doc/{doc_id}/folder", json={"folder_id": 999})

    assert response.status_code == 400


def test_deleting_a_folder_detaches_its_documents_without_deleting_them(client):
    folder = _create(client, "Maths")
    doc_id = _document(client)
    client.post(f"/api/library/doc/{doc_id}/folder", json={"folder_id": folder["id"]})

    deleted = client.delete(f"/api/library/folders/{folder['id']}")

    assert deleted.status_code == 200
    assert deleted.json() == {"deleted_folders": 1, "detached_documents": 1}
    # Le document existe toujours et est redevenu « non classé ».
    assert client.get(f"/api/library/doc/{doc_id}").json()["folder_id"] is None


def test_documents_endpoint_carries_the_classification_fields(client):
    _document(client)

    doc = client.get("/api/library/documents").json()[0]

    for key in ("folder_id", "summary", "keywords", "digest_status"):
        assert key in doc, f"{key} absent du contrat d'API du document"


def test_search_endpoint_matches_generated_keywords(client):
    from db.documents import update_document_digest

    doc_id = _document(client, "scan-042.pdf")
    update_document_digest(doc_id, "biologie", "La conversion de la lumière en énergie.", ["photosynthèse"])

    found = client.get("/api/library/search", params={"q": "photosynthese"}).json()

    assert [d["title"] for d in found] == ["scan-042.pdf"]


def test_search_with_a_blank_query_returns_nothing(client):
    _document(client)

    assert client.get("/api/library/search", params={"q": "  "}).json() == []
