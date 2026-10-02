"""Le document emprunté par la visite guidée.

Ce que ces tests verrouillent tient en une phrase : **le document de
démonstration ne doit rien laisser derrière lui**. C'est la seule suppression de
document du dépôt, et elle s'appuie sur les `ON DELETE CASCADE` du schéma — un
schéma qui évolue. Si quelqu'un ajoute demain une table référençant `documents`
sans cascade, `test_discard_leaves_nothing_behind` doit tomber.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def demo_resources(tmp_path, monkeypatch, make_pdf):
    """Remplace les ressources embarquées par un PDF fabriqué à la volée.

    Le vrai `nwol/resources/demo_fr.pdf` n'est pas utilisé ici : un test ne doit
    pas dépendre du contenu d'une ressource qu'on peut vouloir remplacer, et il
    doit passer même dans un checkout où elle manque.
    """
    from services import onboarding

    resources = tmp_path / "resources"
    resources.mkdir()
    make_pdf(resources / "demo_fr.pdf", ["Page une du document de démonstration.", "Page deux."])
    monkeypatch.setattr(onboarding, "RESOURCES_DIR", resources)
    return resources


def test_borrowing_puts_a_complete_card_in_the_library(client, demo_resources):
    document = client.post("/api/onboarding/demo").json()["document"]
    assert document is not None

    library = client.get("/api/library/documents").json()
    assert [d["id"] for d in library] == [document["id"]]
    # La fiche est écrite à la main par le service : elle doit être COMPLÈTE tout
    # de suite. Un `digest_status` à "pending" ferait tourner l'indicateur de
    # génération LLM sur la carte pendant qu'on l'explique.
    assert library[0]["digest_status"] == "done"
    assert library[0]["summary"]
    assert library[0]["keywords"]


def test_missing_resource_is_not_an_error(client, tmp_path, monkeypatch):
    """Une visite doit se dérouler sans son chapitre lecture, pas échouer."""
    from services import onboarding

    monkeypatch.setattr(onboarding, "RESOURCES_DIR", tmp_path / "vide")
    response = client.post("/api/onboarding/demo")
    assert response.status_code == 200
    assert response.json()["document"] is None


def test_discard_leaves_nothing_behind(client, demo_resources):
    from db import get_connection
    from db.app_settings import get_setting

    doc_id = client.post("/api/onboarding/demo").json()["document"]["id"]
    # On fabrique des données liées comme le ferait une vraie lecture, pour que
    # la cascade ait quelque chose à emporter.
    client.get(f"/api/library/documents/{doc_id}")
    session_id = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    assert session_id

    assert client.delete("/api/onboarding/demo").json()["ok"] is True

    conn = get_connection()
    assert conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM chapters").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM reading_sessions").fetchone()["c"] == 0
    assert client.get("/api/library/documents").json() == []
    # Le marqueur doit partir avec : sinon le garde-fou de démarrage essaierait
    # indéfiniment de nettoyer un document qui n'existe plus.
    assert get_setting("onboarding_doc_id") is None


def test_discarding_twice_is_harmless(client, demo_resources):
    client.post("/api/onboarding/demo")
    assert client.delete("/api/onboarding/demo").status_code == 200
    assert client.delete("/api/onboarding/demo").status_code == 200


def test_the_file_itself_is_removed(client, demo_resources):
    from pathlib import Path

    from db.documents import get_document

    doc_id = client.post("/api/onboarding/demo").json()["document"]["id"]
    path = Path(get_document(doc_id)["path"])
    assert path.is_file()

    client.delete("/api/onboarding/demo")
    assert not path.exists()


def test_startup_reconciliation_returns_a_stranded_document(client, demo_resources):
    """L'application fermée en pleine visite ne doit pas laisser le document."""
    from services.onboarding import reconcile_demo_document

    client.post("/api/onboarding/demo")
    assert client.get("/api/library/documents").json() != []

    reconcile_demo_document()  # ce que fait le lifespan au démarrage suivant
    assert client.get("/api/library/documents").json() == []


def test_reconciliation_without_a_borrowed_document_does_nothing(client):
    from services.onboarding import reconcile_demo_document

    reconcile_demo_document()
    assert client.get("/api/library/documents").json() == []


def test_the_dead_tour_step_preference_is_gone(client):
    """`tour_step` mémorisait une reprise en cours de visite qui n'existe plus.

    La visite emprunte un document rendu au redémarrage : elle ne peut pas
    reprendre en son milieu. Le réglage ne doit donc plus être servi, ni accepté.
    """
    body = client.get("/api/preferences").json()
    assert "tour_step" not in body["preferences"]
    assert body["preferences"]["tour_done"] == "false"
    assert client.post("/api/preferences", json={"tour_step": "clikoda"}).status_code == 400
