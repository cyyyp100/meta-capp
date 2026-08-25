"""Politique de rangement de la bibliothèque (services/folders.py).

Trois règles y sont testées parce qu'elles ne sont exprimables NI en SQL NI dans
un routeur : l'acyclicité de l'arbre, la profondeur maximale, et le fait qu'un
document survive toujours à la suppression de son dossier.
"""
import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    import db
    from db import close_connection

    close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nwol.db"))
    from db.schema import initialize_schema

    initialize_schema()
    yield
    close_connection()


def _document(path: str, folder_id=None) -> int:
    from db.documents import upsert_document
    from db.folders import set_document_folder

    doc_id = upsert_document(path, path.rsplit("/", 1)[-1], 10, "pymupdf_scroll", False)
    if folder_id is not None:
        set_document_folder(doc_id, folder_id)
    return doc_id


def test_tree_nests_children_and_counts_the_subtree(fresh_db):
    from services.folders import create_folder, folder_tree

    maths = create_folder("Maths")
    algebre = create_folder("Algèbre", parent_id=maths["id"])
    _document("/tmp/a.pdf", maths["id"])
    _document("/tmp/b.pdf", algebre["id"])
    _document("/tmp/c.pdf", algebre["id"])

    tree = folder_tree()
    assert len(tree) == 1
    root = tree[0]
    assert root["name"] == "Maths"
    assert root["doc_count"] == 1      # directement dedans
    assert root["total_count"] == 3    # sous-arbre inclus
    assert [c["name"] for c in root["children"]] == ["Algèbre"]
    assert root["children"][0]["total_count"] == 2


def test_move_folder_into_its_own_descendant_is_refused(fresh_db):
    from services.folders import create_folder, move_folder

    maths = create_folder("Maths")
    algebre = create_folder("Algèbre", parent_id=maths["id"])

    # Déplacer le parent dans son enfant détacherait le sous-arbre de la racine :
    # invisible dans le rail, donc irrattrapable à la souris.
    with pytest.raises(ValueError):
        move_folder(maths["id"], algebre["id"])
    # Le dépôt sur soi-même est couvert par le même garde-fou.
    with pytest.raises(ValueError):
        move_folder(maths["id"], maths["id"])


def test_move_folder_to_a_sibling_and_back_to_root(fresh_db):
    from services.folders import create_folder, folder_tree, move_folder

    maths = create_folder("Maths")
    physique = create_folder("Physique")

    move_folder(physique["id"], maths["id"])
    assert [f["name"] for f in folder_tree()] == ["Maths"]

    move_folder(physique["id"], None)
    assert sorted(f["name"] for f in folder_tree()) == ["Maths", "Physique"]


def test_depth_limit_is_enforced(fresh_db):
    from config.settings import LIBRARY_MAX_FOLDER_DEPTH
    from services.folders import create_folder

    parent = None
    for level in range(LIBRARY_MAX_FOLDER_DEPTH):
        parent = create_folder(f"N{level}", parent_id=parent["id"] if parent else None)["id"]
        parent = {"id": parent}
    with pytest.raises(ValueError):
        create_folder("Trop profond", parent_id=parent["id"])


def test_deleting_a_folder_keeps_its_documents(fresh_db):
    from db.documents import get_document
    from services.folders import create_folder, delete_folder

    maths = create_folder("Maths")
    algebre = create_folder("Algèbre", parent_id=maths["id"])
    doc_a = _document("/tmp/a.pdf", maths["id"])
    doc_b = _document("/tmp/b.pdf", algebre["id"])

    result = delete_folder(maths["id"])

    assert result == {"deleted_folders": 2, "detached_documents": 2}
    # Les documents existent toujours et sont redevenus « non classés ».
    for doc_id in (doc_a, doc_b):
        doc = get_document(doc_id)
        assert doc is not None
        assert doc["folder_id"] is None


def test_move_document_between_folders_and_back_to_root(fresh_db):
    from db.documents import get_document
    from services.folders import create_folder, move_document

    maths = create_folder("Maths")
    doc_id = _document("/tmp/a.pdf")
    assert get_document(doc_id)["folder_id"] is None

    move_document(doc_id, maths["id"])
    assert get_document(doc_id)["folder_id"] == maths["id"]

    move_document(doc_id, None)
    assert get_document(doc_id)["folder_id"] is None


def test_unknown_ids_raise_rather_than_corrupt(fresh_db):
    from services.folders import create_folder, move_document, rename_folder

    with pytest.raises(ValueError):
        rename_folder(999, "Fantôme")
    with pytest.raises(ValueError):
        create_folder("Orphelin", parent_id=999)
    with pytest.raises(ValueError):
        move_document(999, None)


def test_blank_name_falls_back_to_a_default(fresh_db):
    from services.folders import create_folder

    assert create_folder("   ")["name"] == "Nouveau dossier"
