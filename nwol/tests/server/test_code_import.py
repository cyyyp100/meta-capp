"""Import + lecture d'un fichier de code via l'API (bout en bout, DB isolée)."""
from __future__ import annotations

SAMPLE = """def add(a, b):
    # additionne deux nombres
    return a + b


print(add(2, 3))
"""


def _import(client, tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return client.post("/api/library/import", json={"path": str(path)})


def test_import_code_creates_code_document(client, tmp_path):
    resp = _import(client, tmp_path, "sample.py", SAMPLE)
    assert resp.status_code == 200, resp.text
    doc = resp.json()
    assert doc["extraction_engine"] == "code"
    assert doc["page_count"] >= 1
    assert doc["title"] == "sample.py"


def test_code_document_serves_code_blocks(client, tmp_path):
    doc = _import(client, tmp_path, "sample.py", SAMPLE).json()
    doc_id = doc["id"]

    blocks = client.get(f"/api/library/doc/{doc_id}/page/1/blocks")
    assert blocks.status_code == 200
    payload = blocks.json()["blocks"]
    assert payload and payload[0]["type"] == "code"
    assert "def add" in payload[0]["text"]
    assert payload[0]["metadata"]["lang"] == "python"

    # Le document code n'a pas d'image de page.
    png = client.get(f"/api/library/doc/{doc_id}/page/1.png")
    assert png.status_code == 404


def test_reject_binary_disguised_as_code(client, tmp_path):
    path = tmp_path / "evil.py"
    path.write_bytes(b"\x00\x01\x02\x03not text")
    resp = client.post("/api/library/import", json={"path": str(path)})
    assert resp.status_code == 400


def test_reject_unsupported_extension(client, tmp_path):
    path = tmp_path / "archive.zip"
    path.write_bytes(b"PK\x03\x04")
    resp = client.post("/api/library/import", json={"path": str(path)})
    assert resp.status_code == 400
