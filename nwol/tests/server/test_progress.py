"""« Ma progression » : exposer ce que la base tenait déjà (§ B4).

`metacog_history`, `session_gauges`, `session_reflections` et `page_dwell`
étaient écrits depuis des mois et aucun routeur ne les exposait. Ces tests
vérifient que la timeline et le détail disent la vérité — en particulier sur les
jauges restées à leur amorce, qui ne sont PAS des mesures.
"""
from __future__ import annotations


def _import_doc(client, tmp_path, make_pdf):
    path = make_pdf(tmp_path / "progress.pdf", ["Contenu de test pour la progression."])
    return client.post("/api/library/import", json={"path": path}).json()["id"]


def test_timeline_is_empty_on_a_fresh_database(client):
    body = client.get("/api/progress/sessions").json()
    assert body["sessions"] == []
    assert "attention" in body["criteria"]


def test_a_finished_session_appears_with_its_reflections(client, tmp_path, make_pdf):
    doc_id = _import_doc(client, tmp_path, make_pdf)
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    client.post(f"/api/session/{sid}/end", json={"pages_read": 3, "duration_s": 420})
    client.post(f"/api/session/{sid}/finalize", json={
        "responses": ["J'ai compris le théorème central.", ""],
        "questions": ["Qu'as-tu compris ?", "Quel point reste flou ?"],
    })

    row = client.get("/api/progress/sessions").json()["sessions"][0]
    assert row["session_id"] == sid
    assert row["completed"] is True
    assert row["pages_read"] == 3
    assert row["has_reflections"] is True

    detail = client.get(f"/api/progress/session/{sid}").json()
    # Les mots de l'apprenant sont relus TELS QUELS : c'est le point de tout
    # l'écran, et une reformulation le viderait de son sens.
    answers = [r["answer"] for r in detail["reflections"]]
    assert "J'ai compris le théorème central." in answers
    assert detail["metrics"]["pages_read"] == 3


def test_gauges_left_at_their_seed_are_not_reported_as_measured(client, tmp_path, make_pdf):
    """Une session démarre à profil × 0,8. Une jauge que la séance n'a pas
    exercée finit exactement à son amorce — la présenter comme une mesure est
    l'erreur que `services/session._measured_gauges` évite déjà côté profil."""
    from db.session_gauges import record_gauges

    doc_id = _import_doc(client, tmp_path, make_pdf)
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    record_gauges(sid, {"attention": 40.0, "curiosity": 40.0}, t=0.0)
    record_gauges(sid, {"attention": 72.0, "curiosity": 40.0}, t=60.0)
    client.post(f"/api/session/{sid}/end", json={"pages_read": 1, "duration_s": 60})

    gauges = client.get(f"/api/progress/session/{sid}").json()["gauges"]
    assert gauges["measured"] == ["attention"]
    assert gauges["seed"]["attention"] == 40.0
    assert len(gauges["series"]["attention"]) == 2


def test_unknown_session_is_a_404(client):
    assert client.get("/api/progress/session/424242").status_code == 404


def test_weekly_recap_counts_only_finished_sessions(client, tmp_path, make_pdf):
    doc_id = _import_doc(client, tmp_path, make_pdf)
    # Session ouverte, jamais close : elle ne doit pas entrer dans le bilan.
    client.post("/api/session/start", json={"doc_id": doc_id})

    assert client.get("/api/progress/weekly").json()["sessions"] == 0

    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    client.post(f"/api/session/{sid}/end", json={"pages_read": 2, "duration_s": 300})
    client.post(f"/api/session/{sid}/finalize", json={"responses": ["r"], "questions": ["q ?"]})

    recap = client.get("/api/progress/weekly").json()
    assert recap["sessions"] == 1
    assert recap["pages_read"] == 2
    assert recap["duration_s"] == 300


def test_sessions_are_named_after_their_document_and_reading_number(client, tmp_path, make_pdf):
    """La frise nomme chaque session « <titre du document> · Lecture n » — n
    compté PARMI les lectures de ce document. Le titre vient de
    `documents.filename` (la ligne n'a pas de colonne `title`) : le lire sous
    un autre nom rendait une chaîne vide et le même libellé pour toutes."""
    doc_id = _import_doc(client, tmp_path, make_pdf)
    other = client.post("/api/library/import", json={
        "path": make_pdf(tmp_path / "autre.pdf", ["Autre document."]),
    }).json()["id"]

    first = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    client.post(f"/api/session/{first}/end", json={"pages_read": 1, "duration_s": 60})
    elsewhere = client.post("/api/session/start", json={"doc_id": other}).json()["session_id"]
    client.post(f"/api/session/{elsewhere}/end", json={"pages_read": 1, "duration_s": 60})
    second = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    client.post(f"/api/session/{second}/end", json={"pages_read": 1, "duration_s": 60})

    rows = {r["session_id"]: r for r in client.get("/api/progress/sessions").json()["sessions"]}
    assert rows[first]["document_title"] == "progress.pdf"
    assert rows[first]["reading_index"] == 1
    assert rows[second]["reading_index"] == 2
    # L'autre document a sa propre numérotation.
    assert rows[elsewhere]["document_title"] == "autre.pdf"
    assert rows[elsewhere]["reading_index"] == 1

    detail = client.get(f"/api/progress/session/{second}").json()
    assert detail["document"]["title"] == "progress.pdf"
    assert detail["reading_index"] == 2
