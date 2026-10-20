"""Prise de notes du lecteur : routes HTTP (schéma v45).

Les routeurs sont fins — la validation est celle de services/annotations.py,
testée à part : ici, les formes des réponses, les codes (400 refus, 404
introuvable, 422 corps mal formé), la distinction champ absent / champ à
null des éditions, et les en-têtes de l'export Markdown.
"""


def _doc(client, tmp_path, make_pdf, pages=4):
    path = make_pdf(tmp_path / "cours.pdf", [f"Page {n}" for n in range(1, pages + 1)])
    return client.post("/api/library/import", json={"path": path}).json()["id"]


def test_labels_crud(client):
    payload = client.get("/api/annotations/labels").json()
    assert (payload["name_max"], payload["max_labels"], payload["default_color"]) == (40, 24, "yellow")
    labels = payload["labels"]
    assert [label["preset"] for label in labels][:2] == ["important", "definition"]
    assert {"id", "preset", "name", "color", "position", "usage"} <= set(labels[0])

    created = client.post("/api/annotations/labels", json={"name": "Formule", "color": "pink"})
    assert created.status_code == 200
    label = created.json()["label"]
    assert (label["name"], label["color"]) == ("Formule", "pink")
    assert client.post("/api/annotations/labels", json={"name": "Formule", "color": "fuchsia"}).status_code == 400
    assert client.post("/api/annotations/labels", json={"name": "x"}).status_code == 422

    # Champ absent : inchangé ; `name: null` rend son nom traduit au preset.
    recolored = client.post(f"/api/annotations/labels/{labels[0]['id']}/edit", json={"color": "cyan"}).json()["label"]
    assert (recolored["color"], recolored["name"]) == ("cyan", None)
    renamed = client.post(f"/api/annotations/labels/{labels[0]['id']}/edit", json={"name": "Clé"}).json()["label"]
    assert (renamed["color"], renamed["name"]) == ("cyan", "Clé")
    reset = client.post(f"/api/annotations/labels/{labels[0]['id']}/edit", json={"name": None}).json()["label"]
    assert reset["name"] is None
    assert client.post("/api/annotations/labels/9999/edit", json={"color": "red"}).status_code == 404

    ids = [row["id"] for row in client.get("/api/annotations/labels").json()["labels"]]
    ordered = client.post("/api/annotations/labels/order", json={"ids": ids[::-1]}).json()["labels"]
    assert [row["id"] for row in ordered] == ids[::-1]
    assert client.post("/api/annotations/labels/order", json={"ids": ids[1:]}).status_code == 400

    removed = client.delete(f"/api/annotations/labels/{label['id']}")
    assert removed.json() == {"removed": True, "released": 0}
    assert client.delete(f"/api/annotations/labels/{label['id']}").status_code == 404


def test_highlights_and_notes_through_the_api(client, tmp_path, make_pdf):
    doc_id = _doc(client, tmp_path, make_pdf)
    labels = client.get("/api/annotations/labels").json()["labels"]

    res = client.post(
        f"/api/library/doc/{doc_id}/highlights",
        json={"page": 2, "quote": "un passage", "rects": [[1, 2, 3, 4]], "label_id": labels[2]["id"],
              "style": "outline", "note": "À retenir"},
    )
    assert res.status_code == 200
    body = res.json()
    hid = body["id"]
    assert body["highlight"]["style"] == "outline" and body["highlight"]["note"] == "À retenir"
    assert client.post(f"/api/library/doc/{doc_id}/highlights",
                       json={"page": 9, "quote": "hors", "rects": []}).status_code == 400
    assert client.post("/api/library/doc/999/highlights",
                       json={"page": 1, "quote": "x", "rects": []}).status_code == 404

    # Édition : un champ absent ne change pas, un champ à null efface.
    edit = f"/api/library/doc/{doc_id}/highlights/{hid}/edit"
    assert client.post(edit, json={"style": "underline"}).json()["highlight"]["note"] == "À retenir"
    cleared = client.post(edit, json={"note": None}).json()["highlight"]
    assert (cleared["note"], cleared["style"], cleared["label_id"]) == (None, "underline", labels[2]["id"])
    assert client.post(edit, json={"style": "wavy"}).status_code == 400
    assert client.post(f"/api/library/doc/{doc_id}/highlights/9999/edit", json={"note": "x"}).status_code == 404

    sticky = client.post(f"/api/library/doc/{doc_id}/notes",
                         json={"kind": "sticky", "page": 1, "x": 30, "y": 40, "body": "Idée"}).json()["note"]
    assert (sticky["kind"], sticky["x"], sticky["body"]) == ("sticky", 30.0, "Idée")
    signet = client.post(f"/api/library/doc/{doc_id}/notes",
                         json={"kind": "signet", "page": 3, "label_id": labels[3]["id"]}).json()["note"]
    assert signet["kind"] == "signet" and signet["label_id"] == labels[3]["id"]
    assert client.post(f"/api/library/doc/{doc_id}/notes", json={"kind": "sticky", "page": 1}).status_code == 400
    edited = client.post(f"/api/library/doc/{doc_id}/notes/{sticky['id']}/edit", json={"body": "Autre"}).json()
    assert edited["note"]["body"] == "Autre" and edited["note"]["x"] == 30.0

    everything = client.get(f"/api/library/doc/{doc_id}/annotations").json()
    assert [h["id"] for h in everything["highlights"]] == [hid]
    assert sorted(n["kind"] for n in everything["notes"]) == ["signet", "sticky"]
    assert client.get("/api/library/doc/999/annotations").status_code == 404

    assert client.delete(f"/api/library/doc/{doc_id}/notes/{sticky['id']}").json() == {"removed": 1}
    assert client.delete(f"/api/library/doc/{doc_id}/highlights/{hid}").json() == {"removed": 1}
    assert client.get(f"/api/library/doc/{doc_id}/annotations").json()["highlights"] == []


def test_the_markdown_export_is_a_download(client, tmp_path, make_pdf):
    doc_id = _doc(client, tmp_path, make_pdf)
    client.post(f"/api/library/doc/{doc_id}/highlights", json={"page": 2, "quote": "un passage", "rects": []})

    res = client.get(f"/api/library/doc/{doc_id}/annotations.md")
    assert res.status_code == 200
    assert res.headers["content-type"] == "text/markdown; charset=utf-8"
    disposition = res.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert disposition == "attachment; filename=\"cours-notes.md\"; filename*=UTF-8''cours-notes.md"
    assert "> un passage" in res.text
    assert client.get("/api/library/doc/999/annotations.md").status_code == 404


def test_deleting_the_document_deletes_its_notes(client, tmp_path, make_pdf):
    doc_id = _doc(client, tmp_path, make_pdf)
    client.post(f"/api/library/doc/{doc_id}/notes", json={"kind": "signet", "page": 2})
    assert client.delete(f"/api/library/doc/{doc_id}").status_code == 200

    from db import get_connection

    assert get_connection().execute("SELECT COUNT(*) FROM reader_notes").fetchone()[0] == 0


def test_purge_reseeds_the_preset_labels(client):
    client.post("/api/annotations/labels", json={"name": "Perso", "color": "pink"})
    assert client.post("/api/data/purge", json={"confirm": "EFFACER"}).status_code == 200
    labels = client.get("/api/annotations/labels").json()["labels"]
    assert all(label["preset"] for label in labels) and len(labels) == 6
