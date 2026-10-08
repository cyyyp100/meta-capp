# Tests des ajouts lot 2 : warm-up de début de session + analyse de session/profil.
from __future__ import annotations


def test_session_start_cards_endpoint(client):
    """L'endpoint warm-up renvoie une liste (vide si aucune carte)."""
    resp = client.get("/api/flashcards/session-start", params={"doc_id": 1, "limit": 5})
    assert resp.status_code == 200
    cards = resp.json()
    assert isinstance(cards, list)
    assert len(cards) <= 5


def _import_mini_pdf(client, tmp_path, make_pdf) -> int:
    pdf_path = make_pdf(tmp_path / "mini.pdf", ["Bonjour Meta-Capp"])
    return client.post("/api/library/import", json={"path": pdf_path}).json()["id"]


def test_session_analysis_endpoint(client, tmp_path, make_pdf):
    """L'endpoint d'analyse renvoie toujours {"analysis": str} (repli "" sans LLM)."""
    doc_id = _import_mini_pdf(client, tmp_path, make_pdf)
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    client.post(f"/api/session/{sid}/end", json={"duration_s": 5})

    resp = client.get(f"/api/session/{sid}/analysis")
    assert resp.status_code == 200
    body = resp.json()
    assert "analysis" in body
    assert isinstance(body["analysis"], str)


def test_overview_exposes_general_analysis(client):
    """La vue profil expose toujours le champ general_analysis (item 11)."""
    overview = client.get("/api/stats/overview").json()
    assert "general_analysis" in overview
    assert isinstance(overview["general_analysis"], str)
