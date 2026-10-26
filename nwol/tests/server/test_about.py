"""« À propos » : les mentions des licences tierces servies telles quelles."""

from services import about


def test_notices_served_as_plain_text(client, tmp_path, monkeypatch):
    path = tmp_path / "THIRD_PARTY_NOTICES.txt"
    path.write_text("Meta-Capp — mentions\nPDFium : BSD-3-Clause\n", encoding="utf-8")
    monkeypatch.setattr(about, "NOTICES_PATH", path)

    resp = client.get("/api/about/notices")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.text == "Meta-Capp — mentions\nPDFium : BSD-3-Clause\n"


def test_notices_missing_is_404(client, tmp_path, monkeypatch):
    # Checkout de développement sans `scripts/third_party_notices.py` lancé.
    monkeypatch.setattr(about, "NOTICES_PATH", tmp_path / "absent.txt")
    assert client.get("/api/about/notices").status_code == 404
