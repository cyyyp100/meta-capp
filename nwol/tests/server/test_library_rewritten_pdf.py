"""PDF réécrit sur place après l'import (typiquement un rapport LaTeX recompilé).

Le lecteur construit sa liste de pages à partir de `page_count` : resté à
l'ancienne valeur, il demandait des pages disparues et le serveur répondait
par une 500 à chacune.
"""


def test_detail_follows_a_pdf_rewritten_shorter(client, tmp_path, make_pdf):
    from pdf_viewer.page_renderer import page_cache_dir

    path = make_pdf(tmp_path / "rapport.pdf", ["Intro", "Méthode", "Résultats", "Annexe"])
    doc_id = client.post("/api/library/import", json={"path": path}).json()["id"]
    assert client.get(f"/api/library/doc/{doc_id}/page/1.png?zoom=0.5").status_code == 200

    make_pdf(tmp_path / "rapport.pdf", ["Intro", "Résultats"])
    detail = client.get(f"/api/library/doc/{doc_id}").json()

    assert detail["page_count"] == 2
    assert len(detail["page_sizes_pts"]) == 2
    assert all(ch["page_start"] <= 2 for ch in detail["chapters"])
    assert not any(page_cache_dir(path).glob("page_*.png")), "les PNG de l'ancienne version sont périmés"
    listed = next(d for d in client.get("/api/library/documents").json() if d["id"] == doc_id)
    assert listed["page_count"] == 2


def test_page_out_of_range_is_404(client, tmp_path, make_pdf):
    path = make_pdf(tmp_path / "court.pdf", ["Seule page"])
    doc_id = client.post("/api/library/import", json={"path": path}).json()["id"]

    assert client.get(f"/api/library/doc/{doc_id}/page/2.png").status_code == 404
