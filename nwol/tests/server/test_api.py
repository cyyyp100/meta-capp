def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_stats_overview(client):
    resp = client.get("/api/stats/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["criteria"]) == 6
    assert body["global_score"] == 50.0
    assert body["trend"]["category"] == "stable"


def test_flashcards_empty_then_created(client):
    assert client.get("/api/flashcards").json() == []

    # Création via le service (chemin d'écriture), puis lecture via l'API.
    from services.flashcards import create_flashcard

    create_flashcard(front="Q", back="R", tags=["t"], difficulty=2)

    cards = client.get("/api/flashcards").json()
    assert len(cards) == 1
    assert cards[0]["front"] == "Q"

    # Filtre par difficulté.
    assert len(client.get("/api/flashcards", params={"difficulty": 2}).json()) == 1
    assert len(client.get("/api/flashcards", params={"difficulty": 3}).json()) == 0


def test_library_recent_empty(client):
    resp = client.get("/api/library/recent")
    assert resp.status_code == 200
    assert resp.json() == []


def test_library_doc_404(client):
    assert client.get("/api/library/doc/999").status_code == 404


def test_flashcard_create_review_delete(client):
    # Création via l'API.
    resp = client.post("/api/flashcards", json={"front": "Q", "back": "R", "tags": ["t"], "difficulty": 2})
    assert resp.status_code == 200
    card_id = resp.json()["id"]
    assert isinstance(card_id, int)

    cards = client.get("/api/flashcards").json()
    assert len(cards) == 1

    # Révision via l'API.
    resp = client.post(f"/api/flashcards/{card_id}/review", json={"verdict": "correct"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # Suppression via l'API.
    resp = client.request("DELETE", f"/api/flashcards/{card_id}")
    assert resp.status_code == 200
    assert resp.json()["removed"] == 1
    assert client.get("/api/flashcards").json() == []


def test_spa_deep_links_serve_index(client):
    """Une route client (/reader/12, /stats) doit renvoyer index.html.

    Sans ce repli, tout rechargement de page ou deep-link renvoie 404 dans
    l'application packagée (le bundle est servi par StaticFiles)."""
    from server.config import FRONTEND_DIST

    if not FRONTEND_DIST.is_dir():
        import pytest

        pytest.skip("frontend non compilé")

    for path in ("/reader/12", "/stats", "/flashcards"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert res.headers["content-type"].startswith("text/html"), path

    # Les routes API gardent la priorité sur le repli SPA.
    assert client.get("/api/health").headers["content-type"].startswith("application/json")
