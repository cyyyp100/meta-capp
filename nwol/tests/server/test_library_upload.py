"""Import par ENVOI de fichier (POST /api/library/upload).

Quand Meta-Capp tourne dans un navigateur (Linux sans GTK ni Qt, Windows sans
WebView2, `--browser`), aucun chemin n'est disponible : le fichier arrive en
corps brut, est copié dans le dossier de données (services/uploads) puis
importé par le chemin habituel. Ces tests figent ce qui le rend sûr : le nom
reçu ne peut pas sortir du dossier, deux fichiers homonymes ne s'écrasent pas,
et la copie (la nôtre, contrairement aux fichiers ouverts par chemin) part avec
le document.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def _upload(client, filename: str, content: bytes):
    return client.post(
        "/api/library/upload",
        params={"filename": filename},
        content=content,
        headers={"Content-Type": "application/octet-stream"},
    )


def _pdf_bytes(tmp_path, make_pdf, text: str, name: str = "source.pdf") -> bytes:
    return Path(make_pdf(tmp_path / name, [text])).read_bytes()


def _stored(doc: dict) -> Path:
    """Chemin de la copie : jamais exposé par l'API (le frontend n'en a que faire)."""
    from db.documents import get_document

    return Path(get_document(doc["id"])["path"])


def _uploads_dir() -> Path:
    from services import uploads

    return uploads.uploads_dir()


def test_uploaded_pdf_is_imported_and_readable(client, tmp_path, make_pdf):
    response = _upload(client, "Cours de chimie.pdf", _pdf_bytes(tmp_path, make_pdf, "Les liaisons covalentes"))

    assert response.status_code == 200
    doc = response.json()
    assert doc["filename"] == "Cours de chimie.pdf"
    assert doc["page_count"] == 1
    stored = _stored(doc)
    assert stored.is_file() and stored.is_relative_to(_uploads_dir())
    from services import library

    assert "covalentes" in library.page_text(doc["id"], 1)


def test_same_file_twice_is_the_same_document(client, tmp_path, make_pdf):
    content = _pdf_bytes(tmp_path, make_pdf, "Thermodynamique")
    first = _upload(client, "thermo.pdf", content).json()
    second = _upload(client, "thermo.pdf", content).json()
    assert first["id"] == second["id"]


def test_two_files_with_the_same_name_never_overwrite_each_other(client, tmp_path, make_pdf):
    a = _upload(client, "cours.pdf", _pdf_bytes(tmp_path, make_pdf, "Premier cours", "a.pdf")).json()
    b = _upload(client, "cours.pdf", _pdf_bytes(tmp_path, make_pdf, "Second cours", "b.pdf")).json()
    assert a["id"] != b["id"]
    assert _stored(a) != _stored(b)
    assert _stored(a).is_file() and _stored(b).is_file()


@pytest.mark.parametrize("hostile", ["../../evil.pdf", "..\\..\\evil.pdf", "/etc/evil.pdf", "C:\\Windows\\evil.pdf"])
def test_the_received_name_cannot_leave_the_uploads_folder(client, tmp_path, make_pdf, hostile):
    response = _upload(client, hostile, _pdf_bytes(tmp_path, make_pdf, "Contenu"))
    assert response.status_code == 200
    stored = _stored(response.json())
    assert stored.is_relative_to(_uploads_dir())
    assert stored.name == "evil.pdf"


def test_unsupported_format_is_refused_before_anything_is_written(client):
    response = _upload(client, "photo.jpg", b"\xff\xd8\xff\xe0 pas un document")
    assert response.status_code == 400
    assert not _uploads_dir().exists() or not any(_uploads_dir().rglob("*.jpg"))


def test_a_broken_pdf_is_refused_and_leaves_nothing_behind(client):
    response = _upload(client, "casse.pdf", b"%PDF-1.4 ceci n'est pas un PDF")
    assert response.status_code == 400
    leftovers = [p for p in _uploads_dir().rglob("*") if p.is_file()] if _uploads_dir().exists() else []
    assert leftovers == []


def test_empty_upload_is_refused(client):
    assert _upload(client, "vide.pdf", b"").status_code == 400


def test_uploaded_code_file_is_imported(client):
    response = _upload(client, "tri.py", b"def tri(xs):\n    return sorted(xs)\n")
    assert response.status_code == 200
    assert response.json()["page_count"] >= 1


def test_deleting_the_document_removes_our_copy_only(client, tmp_path, make_pdf):
    doc = _upload(client, "a-effacer.pdf", _pdf_bytes(tmp_path, make_pdf, "Temporaire")).json()
    stored = _stored(doc)

    assert client.delete(f"/api/library/doc/{doc['id']}").status_code == 200
    assert not stored.exists()
    assert not stored.parent.exists()


def test_discard_never_touches_a_file_outside_the_uploads_folder(client, tmp_path, make_pdf):
    from services import uploads

    user_file = make_pdf(tmp_path / "a-moi.pdf", ["Mon fichier"])
    uploads.discard(user_file)
    assert os.path.exists(user_file)


def test_purge_erases_the_uploaded_copies(client, tmp_path, make_pdf):
    _upload(client, "perso.pdf", _pdf_bytes(tmp_path, make_pdf, "Données perso"))
    assert _uploads_dir().exists()
    assert client.post("/api/data/purge", json={"confirm": "EFFACER"}).status_code == 200
    assert not _uploads_dir().exists()


def test_purge_only_erases_what_it_wrote(client, tmp_path, make_pdf):
    """Le dossier dérive de l'emplacement de la base, que NWOL_DB_PATH déplace :
    base posée dans le dossier personnel, l'ancien nom `documents` y était
    `~/Documents` (macOS et Windows ignorent la casse). Seul le rangement des
    envois part, jamais ce qui l'entoure."""
    _upload(client, "perso.pdf", _pdf_bytes(tmp_path, make_pdf, "Données perso"))
    root = _uploads_dir()
    foreign = root / "mes-cours" / "chapitre1.pdf"
    foreign.parent.mkdir()
    foreign.write_bytes(b"%PDF-1.4 a moi")
    (root / "notes.txt").write_text("à moi aussi", encoding="utf-8")

    assert client.post("/api/data/purge", json={"confirm": "EFFACER"}).status_code == 200
    assert foreign.exists() and (root / "notes.txt").exists()
    assert sorted(p.name for p in root.iterdir()) == ["mes-cours", "notes.txt"]


def test_discard_only_removes_a_file_laid_out_by_store(client):
    from services import uploads

    root = uploads.uploads_dir()
    root.mkdir(parents=True, exist_ok=True)
    loose = root / "a-moi.pdf"
    loose.write_bytes(b"%PDF-1.4")
    uploads.discard(str(loose))
    assert loose.exists()


@pytest.mark.parametrize(
    "received, expected",
    [("aux.c", "_aux.c"), ("CON.pdf", "_CON.pdf"), ("com1.tar.py", "_com1.tar.py"), ("auxiliaire.c", "auxiliaire.c")],
)
def test_windows_device_names_are_neutralised(received, expected):
    """`aux.c` désigne un port sous Windows, pas un fichier : l'écriture échouait."""
    from services.uploads import safe_filename

    assert safe_filename(received) == expected


@pytest.mark.parametrize("stem", ["数学" * 60, "😀" * 70, "x" * 300])
def test_long_names_fit_every_filesystem_and_keep_their_extension(stem):
    """ext4 et btrfs bornent un nom à 255 OCTETS : 120 caractères chinois en font 360."""
    from services.uploads import safe_filename

    name = safe_filename(stem + ".pdf")
    assert name.endswith(".pdf") and len(name) > len(".pdf")
    assert len(name.encode("utf-8")) <= 200 and len(name) <= 120


def test_a_long_non_latin_name_is_uploaded(client, tmp_path, make_pdf):
    response = _upload(client, "数学" * 60 + ".pdf", _pdf_bytes(tmp_path, make_pdf, "Analyse"))
    assert response.status_code == 200
    assert _stored(response.json()).is_file()


def test_upload_is_guarded_like_every_api_route(client, tmp_path, make_pdf):
    """CSRF : un formulaire d'un autre site porte son Origin — refusé avant toute écriture."""
    response = client.post(
        "/api/library/upload",
        params={"filename": "x.pdf"},
        content=_pdf_bytes(tmp_path, make_pdf, "x"),
        headers={"Content-Type": "application/octet-stream", "Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert not _uploads_dir().exists()
