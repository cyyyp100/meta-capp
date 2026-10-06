"""« Localiser le fichier » : retrouver un document dont le fichier a été déplacé.

Un document n'est relié à son fichier que par `documents.path`. Déplacer le
fichier cassait les vignettes (500), le lecteur (WebSocket fermé à la première
reformulation) et le réimport (nouveau document vierge, l'historique restant
attaché à l'ancien). Ces tests figent la re-liaison EN PLACE (services/relink) :
même id, historique conservé, voisins suivis, refus lisibles.

Les fichiers sont DÉPLACÉS (`os.replace`), jamais régénérés : la sortie de
`make_pdf` n'est pas déterministe, deux PDF « identiques » n'y auraient pas la
même empreinte.
"""
from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_document_digest(monkeypatch):
    """La fiche LLM de chaque import partirait dans la file du worker UNIQUE.
    Hors sujet ici, et risquée : fermer le lecteur annule les générations en
    vol, l'orchestrateur remet la fiche en file 20 s plus tard — après le test,
    hors de ses gardes (`no_real_generation` défaite, vrai Ollama s'il tourne)."""
    from services import orchestrator

    monkeypatch.setattr(orchestrator, "generate_document_digest", lambda *_args, **_kwargs: None)


@pytest.fixture(autouse=True)
def page_cache(tmp_path, monkeypatch):
    """Les PNG rendus vont dans le dossier du test, pas dans `nwol/assets`."""
    import pdf_viewer.page_renderer as page_renderer

    assets = tmp_path / "assets"
    monkeypatch.setattr(page_renderer, "ASSETS_DIR", str(assets))
    return assets


@pytest.fixture
def allowed_root(tmp_path, monkeypatch):
    """Copie de tests/server/test_security.py : seule `autorise/` est importable."""
    root = tmp_path / "autorise"
    root.mkdir()
    monkeypatch.setenv("NWOL_IMPORT_ROOTS", str(root))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))          # POSIX
    monkeypatch.setenv("USERPROFILE", str(home))   # Windows
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    return root


def _pdf(make_pdf, path: Path, pages: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return Path(make_pdf(path, pages))


def _code(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _move(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    return dst


def _import(client, path: Path) -> dict:
    response = client.post("/api/library/import", json={"path": str(path)})
    assert response.status_code == 200, response.text
    return response.json()


def _relink(client, doc_id: int, path: Path | str, force: bool = False):
    return client.post(f"/api/library/doc/{doc_id}/relink", json={"path": str(path), "force": force})


def _listed(client) -> dict[int, dict]:
    return {d["id"]: d for d in client.get("/api/library/documents").json()}


def _forget_hash(doc_id: int) -> None:
    """Un document importé avant que l'empreinte soit calculée."""
    from db import get_connection

    conn = get_connection()
    with conn:
        conn.execute("UPDATE documents SET content_hash=NULL WHERE id=?", (doc_id,))


# ── Fichier absent : un état connu, pas une panne ───────────────────────────


def test_a_moved_file_is_reported_missing_instead_of_a_server_error(client, tmp_path, make_pdf):
    from pdf_viewer.page_renderer import page_cache_dir

    src = _pdf(make_pdf, tmp_path / "cours" / "chimie.pdf", ["Liaisons covalentes"])
    doc = _import(client, src)
    assert doc["file_missing"] is False
    assert doc["content_hash"] and doc["last_known_folder"] is None
    # Vignette rendue AVANT le déplacement : elle est en cache disque.
    assert client.get(f"/api/library/doc/{doc['id']}/page/1.png?zoom=0.5").status_code == 200

    _move(src, tmp_path / "ailleurs" / "chimie.pdf")

    listed = _listed(client)[doc["id"]]
    assert listed["file_missing"] is True
    assert listed["last_known_folder"] == str((tmp_path / "cours").resolve())
    detail = client.get(f"/api/library/doc/{doc['id']}").json()
    assert detail["file_missing"] is True and detail["page_sizes_pts"] == []

    for url in (
        f"/api/library/doc/{doc['id']}/page/1.png?zoom=0.5",  # même en cache : le lecteur n'ouvrirait rien
        f"/api/library/doc/{doc['id']}/page/2.png?zoom=2",  # jamais rendue
        f"/api/library/doc/{doc['id']}/page/1/words",
        f"/api/library/doc/{doc['id']}/page/1/search?q=covalentes",
    ):
        response = client.get(url)
        assert response.status_code == 410, url
        assert response.json()["code"] == "file_missing"
        assert response.headers["cache-control"] == "no-store"

    # Le rendu d'un fichier absent ne crée plus de dossier de cache vide.
    never_opened = _pdf(make_pdf, tmp_path / "cours" / "jamais-ouvert.pdf", ["Rien"])
    other = _import(client, never_opened)
    cache = page_cache_dir(str(never_opened))
    _move(never_opened, tmp_path / "ailleurs" / "jamais-ouvert.pdf")
    assert client.get(f"/api/library/doc/{other['id']}/page/1.png").status_code == 410
    assert not cache.exists()


def test_the_last_known_folder_is_shown_relative_to_home(client, tmp_path, make_pdf, monkeypatch):
    home = (tmp_path / "home").resolve()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    nested = _pdf(make_pdf, home / "Documents" / "Cours" / "optique.pdf", ["Lentilles"])
    loose = _pdf(make_pdf, home / "notes.pdf", ["Notes"])
    ids = [_import(client, nested)["id"], _import(client, loose)["id"]]
    nested.unlink()
    loose.unlink()

    listed = _listed(client)
    assert listed[ids[0]]["last_known_folder"] == os.path.join("~", "Documents", "Cours")
    assert listed[ids[1]]["last_known_folder"] == "~"


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="droits POSIX (root les ignore)",
)
def test_an_unreadable_location_is_not_a_moved_file(tmp_path):
    """Protection de la vie privée de macOS, partage qui ne répond plus : le
    fichier est peut-être en place. Proposer de le « localiser » serait faux."""
    from services.library import file_missing

    folder = tmp_path / "protege"
    folder.mkdir()
    pdf = folder / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    folder.chmod(0)
    try:
        assert file_missing(str(pdf)) is False
    finally:
        folder.chmod(0o755)
    assert file_missing(str(tmp_path / "absent.pdf")) is True
    assert file_missing(str(pdf / "sous-fichier.pdf")) is True  # NotADirectoryError
    assert file_missing(str(folder)) is True  # un dossier n'est pas le fichier
    assert file_missing("") is True


def _receive_within(ws, seconds: float = 10.0) -> dict:
    """`receive_json` borné dans le temps. Un lecteur dont la boucle meurt rend
    la main sans fermer la socket, et le TestClient attend alors indéfiniment :
    une régression doit faire échouer ce test, pas bloquer la suite."""
    box: dict = {}

    def receive() -> None:
        try:
            box["message"] = ws.receive_json()
        except BaseException as exc:  # relayée au test
            box["error"] = exc

    thread = threading.Thread(target=receive, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        pytest.fail(f"aucun message du lecteur en {seconds:g} s : sa boucle s'est arrêtée")
    if "error" in box:
        raise box["error"]
    return box["message"]


def test_the_reader_socket_survives_a_missing_file(client, tmp_path, make_pdf, monkeypatch):
    """Reformuler une page dont le fichier a disparu levait une exception dans
    la boucle du WebSocket, qui se fermait. Le texte de page manquant vaut ""."""
    from services import assistant

    src = _pdf(make_pdf, tmp_path / "cours.pdf", ["Thermodynamique"])
    doc = _import(client, src)
    src.unlink()

    real_rephrase = assistant.rephrase_page
    seen: dict = {}

    def generator(context, on_success, _on_error):
        seen.update(context)
        on_success({"rephrased_paragraph": "Rien à reformuler."})

    monkeypatch.setattr(
        assistant, "rephrase_page",
        lambda d, p, ok, err: real_rephrase(d, p, ok, err, generator=generator),
    )
    with client.websocket_connect(f"/api/reader/{doc['id']}/stream") as ws:
        ws.send_json({"type": "rephrase", "page": 1})
        assert _receive_within(ws)["type"] == "loading"
        assert _receive_within(ws)["type"] == "answer"
        ws.send_json({"type": "mode", "mode": "coach"})
        assert _receive_within(ws)["type"] == "system", "la socket doit être restée ouverte"
    assert seen["paragraph"] == "" and seen["image_paths"] == []


# ── Relier : le même document, son historique compris ──────────────────────


def test_locating_the_moved_file_keeps_the_document_and_its_history(client, tmp_path, make_pdf):
    from db.sessions import get_session
    from pdf_viewer.page_renderer import page_cache_dir

    src = _pdf(make_pdf, tmp_path / "cours" / "chimie.pdf", ["Liaisons", "Covalence"])
    doc_id = _import(client, src)["id"]
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    assert client.post(
        f"/api/library/doc/{doc_id}/highlights",
        json={"page": 1, "quote": "Liaisons", "rects": [[72.0, 60.0, 140.0, 75.0]]},
    ).status_code == 200
    folder = client.post("/api/library/folders", json={"name": "Chimie"}).json()
    client.post(f"/api/library/doc/{doc_id}/folder", json={"folder_id": folder["id"]})
    client.post(f"/api/library/doc/{doc_id}/rename", json={"title": "Chimie — chapitre 1"})
    assert client.get(f"/api/library/doc/{doc_id}/page/1.png?zoom=0.5").status_code == 200
    old_cache = page_cache_dir(str(src))
    assert old_cache.is_dir()

    moved = _move(src, tmp_path / "archives" / "chimie-v1.pdf")
    response = _relink(client, doc_id, moved)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True and body["relinked"] == []
    document = body["document"]
    assert document["id"] == doc_id
    assert document["file_missing"] is False
    assert document["title"] == "Chimie — chapitre 1", "le titre est celui de l'utilisateur, pas du fichier"
    assert document["folder_id"] == folder["id"]
    assert len(document["page_sizes_pts"]) == 2
    assert len(client.get(f"/api/library/doc/{doc_id}/highlights").json()) == 1
    assert get_session(sid) is not None
    assert list(_listed(client)) == [doc_id], "aucun doublon"
    assert client.get(f"/api/library/doc/{doc_id}/page/1.png?zoom=0.5").status_code == 200
    assert not old_cache.exists(), "le cache de l'ancien chemin ne sert plus à personne"


def test_a_different_file_needs_confirmation_then_becomes_the_new_version(client, tmp_path, make_pdf):
    from db.documents import update_last_page

    src = _pdf(make_pdf, tmp_path / "v1" / "rapport.pdf", ["Intro", "Méthode", "Résultats"])
    doc = _import(client, src)
    update_last_page(doc["id"], 3)
    src.unlink()
    rewritten = _pdf(make_pdf, tmp_path / "v2" / "rapport.pdf", ["Intro", "Conclusion"])

    refused = _relink(client, doc["id"], rewritten)
    assert refused.status_code == 409
    assert refused.json()["code"] == "different_file"
    assert refused.json()["detail"]
    assert _listed(client)[doc["id"]]["file_missing"] is True, "un refus ne change rien"

    accepted = _relink(client, doc["id"], rewritten, force=True)
    assert accepted.status_code == 200, accepted.text
    document = accepted.json()["document"]
    assert document["id"] == doc["id"]
    assert document["page_count"] == 2
    assert document["last_page"] == 2, "le marque-page ne peut pas pointer au-delà de la fin"
    assert all(chapter["page_start"] <= 2 for chapter in document["chapters"])
    assert document["content_hash"] and document["content_hash"] != doc["content_hash"]


def test_a_file_already_in_the_library_is_refused_with_its_name(client, tmp_path, make_pdf):
    a = _pdf(make_pdf, tmp_path / "a.pdf", ["Premier"])
    b = _pdf(make_pdf, tmp_path / "b.pdf", ["Second"])
    doc_a = _import(client, a)
    _import(client, b)
    a.unlink()

    response = _relink(client, doc_a["id"], b)

    assert response.status_code == 409
    assert response.json()["code"] == "already_imported"
    assert "b.pdf" in response.json()["detail"], "le message nomme le doublon à retirer"


def test_a_file_of_the_wrong_kind_is_refused(client, tmp_path, make_pdf):
    src = _pdf(make_pdf, tmp_path / "cours.pdf", ["Optique"])
    doc = _import(client, src)
    src.unlink()
    script = _code(tmp_path / "cours.py", "print('pas un PDF')\n")

    response = _relink(client, doc["id"], script)

    assert response.status_code == 400
    assert response.json()["code"] == "wrong_kind"


def test_an_unreadable_pdf_is_refused(client, tmp_path, make_pdf):
    src = _pdf(make_pdf, tmp_path / "cours.pdf", ["Optique"])
    doc = _import(client, src)
    src.unlink()
    broken = tmp_path / "casse.pdf"
    broken.write_bytes(b"%PDF-1.4 ceci n'est pas un PDF")

    response = _relink(client, doc["id"], broken)

    assert response.status_code == 400
    assert response.json()["code"] == "unreadable"


def test_an_unknown_document_is_404(client, tmp_path, make_pdf):
    pdf = _pdf(make_pdf, tmp_path / "cours.pdf", ["Optique"])
    assert _relink(client, 9999, pdf).status_code == 404


def test_relink_obeys_the_same_guard_as_import(client, tmp_path, make_pdf, allowed_root):
    """S2 : relier un document à un fichier, c'est l'importer à nouveau."""
    src = _pdf(make_pdf, allowed_root / "cours.pdf", ["Optique"])
    doc = _import(client, src)
    outside = _move(src, tmp_path / "ailleurs" / "cours.pdf")

    assert _relink(client, doc["id"], outside).status_code == 400
    assert _relink(client, doc["id"], allowed_root / ".." / "ailleurs" / "cours.pdf").status_code == 400
    link = allowed_root / "lien.pdf"
    os.symlink(outside, link)
    assert _relink(client, doc["id"], link).status_code == 400
    assert _listed(client)[doc["id"]]["file_missing"] is True


# ── Les voisins déplacés avec lui ───────────────────────────────────────────


def test_documents_moved_together_are_found_together(client, tmp_path, make_pdf):
    base = tmp_path / "Documents"
    rapport = _pdf(make_pdf, base / "Recherche" / "Rapports" / "rapport.pdf", ["R1", "R2"])
    papier = _pdf(make_pdf, base / "Recherche" / "Papiers" / "chen.pdf", ["P1"])
    script = _code(base / "Recherche" / "Code" / "analyse.py", "def moyenne(xs):\n    return sum(xs) / len(xs)\n")
    brouillon = _pdf(make_pdf, base / "Recherche" / "Papiers" / "brouillon.pdf", ["B1"])
    ids = {name: _import(client, path)["id"] for name, path in (
        ("rapport", rapport), ("papier", papier), ("script", script), ("brouillon", brouillon),
    )}

    archives = base / "Archives"
    archives.mkdir()
    os.replace(base / "Recherche", archives / "Recherche")
    # Le brouillon a été réécrit depuis : même nom, même place, autre contenu.
    (archives / "Recherche" / "Papiers" / "brouillon.pdf").unlink()
    _pdf(make_pdf, archives / "Recherche" / "Papiers" / "brouillon.pdf", ["B1 revu et corrigé"])

    response = _relink(client, ids["rapport"], archives / "Recherche" / "Rapports" / "rapport.pdf")

    assert response.status_code == 200, response.text
    assert sorted(response.json()["relinked"]) == sorted([ids["papier"], ids["script"]])
    listed = _listed(client)
    assert not listed[ids["papier"]]["file_missing"]
    assert not listed[ids["script"]]["file_missing"]
    assert listed[ids["brouillon"]]["file_missing"], "un contenu différent n'est jamais relié en silence"


def test_neighbours_outside_the_allowed_roots_are_left_alone(client, tmp_path, make_pdf, allowed_root):
    """Chaque voisin passe la garde S2, comme un import : à l'emplacement
    attendu, un lien vers un fichier HORS des racines n'est pas suivi."""
    src = _pdf(make_pdf, allowed_root / "Cours" / "a.pdf", ["A"])
    voisin = _pdf(make_pdf, allowed_root / "Cours" / "b.pdf", ["B"])
    doc_a, doc_b = _import(client, src), _import(client, voisin)
    outside = _move(voisin, tmp_path / "ailleurs" / "b.pdf")
    rangement = allowed_root / "Rangement"
    rangement.mkdir()
    os.replace(allowed_root / "Cours", rangement / "Cours")
    os.symlink(outside, rangement / "Cours" / "b.pdf")

    response = _relink(client, doc_a["id"], rangement / "Cours" / "a.pdf")

    assert response.status_code == 200, response.text
    assert response.json()["relinked"] == []
    assert _listed(client)[doc_b["id"]]["file_missing"] is True


@pytest.mark.skipif(os.name == "nt", reason="chemins POSIX ; la logique est la même sous Windows")
@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (
            "/u/Documents/Recherche/Papiers/x.pdf",
            "/u/Documents/Archives/Recherche/Papiers/x.pdf",
            ("/u/Documents", "/u/Documents/Archives"),
        ),
        ("/u/a/b/x.pdf", "/v/c/x.pdf", ("/u/a/b", "/v/c")),
        ("/u/x/a/b/f.pdf", "/v/a/b/f.pdf", ("/u/x", "/v")),
        ("/a/b/f.pdf", "/Volumes/Cle/a/b/f.pdf", ("/", "/Volumes/Cle")),
        ("/u/a/x.pdf", "/u/a/y.pdf", None),  # simple renommage : pas de voisins
        ("C:\\Users\\u\\x.pdf", "/u/x.pdf", None),  # base restaurée depuis Windows
    ],
)
def test_sibling_roots(old, new, expected):
    from services.relink import sibling_roots

    roots = sibling_roots(old, new)
    assert (tuple(str(r) for r in roots) if roots else None) == expected


# ── Réimporter : le même document, pas un doublon ──────────────────────────


def test_reimporting_a_moved_file_reopens_its_document(client, tmp_path, make_pdf):
    src = _pdf(make_pdf, tmp_path / "cours" / "optique.pdf", ["Lentilles"])
    doc = _import(client, src)
    client.post(f"/api/library/doc/{doc['id']}/rename", json={"title": "Optique (mon titre)"})
    moved = _move(src, tmp_path / "rangé" / "optique.pdf")

    again = _import(client, moved)

    assert again["id"] == doc["id"]
    assert again["file_missing"] is False
    assert again["title"] == "Optique (mon titre)"
    assert list(_listed(client)) == [doc["id"]]
    # Une COPIE, l'original toujours en place, reste un document à part.
    copy = shutil.copy(moved, tmp_path / "copie.pdf")
    assert _import(client, Path(copy))["id"] != doc["id"]


def test_a_document_without_hash_is_recognised_by_its_page_count(client, tmp_path, make_pdf):
    """Importé avant que l'empreinte existe, et déplacé avant qu'elle soit
    calculée : son nombre de pages est le seul témoin qui reste."""
    src = _pdf(make_pdf, tmp_path / "ancien" / "manuel.pdf", ["A", "B", "C"])
    doc = _import(client, src)
    _forget_hash(doc["id"])
    moved = _move(src, tmp_path / "nouveau" / "manuel.pdf")
    shorter = _pdf(make_pdf, tmp_path / "autre.pdf", ["A"])

    assert _relink(client, doc["id"], shorter).json()["code"] == "different_file"
    response = _relink(client, doc["id"], moved)

    assert response.status_code == 200, response.text
    assert response.json()["document"]["content_hash"], "l'empreinte est connue désormais"


def test_startup_backfill_hashes_the_documents_still_in_place(client, tmp_path, make_pdf, no_startup_backfill):
    from db.documents import get_document

    present = _pdf(make_pdf, tmp_path / "present.pdf", ["Là"])
    gone = _pdf(make_pdf, tmp_path / "parti.pdf", ["Parti"])
    a, b = _import(client, present), _import(client, gone)
    _forget_hash(a["id"])
    _forget_hash(b["id"])
    gone.unlink()

    assert no_startup_backfill() == 1
    assert get_document(a["id"])["content_hash"] == a["content_hash"]
    assert get_document(b["id"])["content_hash"] is None
    assert no_startup_backfill() == 0, "rien à refaire"


# ── Mode navigateur et fichiers de code ─────────────────────────────────────


def _relink_upload(client, doc_id: int, content: bytes, filename: str, force: bool = False):
    return client.post(
        f"/api/library/doc/{doc_id}/relink/upload",
        params={"filename": filename, "force": str(force).lower()},
        content=content,
        headers={"Content-Type": "application/octet-stream"},
    )


def _uploaded_files() -> list[Path]:
    from services import uploads

    root = uploads.uploads_dir()
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


def test_locating_by_upload_leaves_no_orphan_copy(client, tmp_path, make_pdf):
    from db.documents import get_document

    src = _pdf(make_pdf, tmp_path / "cours.pdf", ["Optique"])
    doc = _import(client, src)
    original = src.read_bytes()
    src.unlink()
    other = _pdf(make_pdf, tmp_path / "autre" / "cours.pdf", ["Autre chose"]).read_bytes()

    refused = _relink_upload(client, doc["id"], other, "cours.pdf")
    assert refused.status_code == 409 and refused.json()["code"] == "different_file"
    assert _uploaded_files() == [], "la copie faite pour cet essai part avec lui"

    accepted = _relink_upload(client, doc["id"], original, "cours.pdf")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["document"]["id"] == doc["id"]
    assert accepted.json()["relinked"] == []
    stored = Path(get_document(doc["id"])["path"])
    assert _uploaded_files() == [stored]


def test_an_uploaded_copy_is_dropped_once_relinked_to_a_real_file(client, tmp_path, make_pdf):
    content = _pdf(make_pdf, tmp_path / "source.pdf", ["Chimie"]).read_bytes()
    doc = client.post(
        "/api/library/upload", params={"filename": "chimie.pdf"}, content=content,
        headers={"Content-Type": "application/octet-stream"},
    ).json()
    copy = _uploaded_files()
    assert len(copy) == 1
    user_file = tmp_path / "Mes cours" / "chimie.pdf"
    user_file.parent.mkdir()
    user_file.write_bytes(content)

    response = _relink(client, doc["id"], user_file)

    assert response.status_code == 200, response.text
    assert _uploaded_files() == [], "la copie nous appartenait et ne sert plus"
    assert user_file.exists()


def test_a_code_document_is_located_like_a_pdf(client, tmp_path, make_pdf):
    src = _code(tmp_path / "src" / "tri.py", "def tri(xs):\n    return sorted(xs)\n")
    doc = _import(client, src)
    moved = _move(src, tmp_path / "projet" / "tri.py")

    assert client.get(f"/api/library/doc/{doc['id']}/page/1/blocks").status_code == 410
    # Un fichier de code n'a jamais d'image de page, déplacé ou non.
    assert client.get(f"/api/library/doc/{doc['id']}/page/1.png").status_code == 404
    pdf = _pdf(make_pdf, tmp_path / "tri.pdf", ["def tri"])
    assert _relink(client, doc["id"], pdf).json()["code"] == "wrong_kind"

    response = _relink(client, doc["id"], moved)

    assert response.status_code == 200, response.text
    blocks = client.get(f"/api/library/doc/{doc['id']}/page/1/blocks").json()["blocks"]
    assert "def tri" in blocks[0]["text"]
