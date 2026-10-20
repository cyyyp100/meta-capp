# test_annotations.py — La prise de notes du lecteur (services/annotations).
#
# Le service est le seul à valider : palette et styles fermés, longueurs,
# limite d'étiquettes, page du document, propriété des étiquettes et des
# éléments (un id d'un autre document est introuvable). Il sème les étiquettes
# prédéfinies à la demande, garde la note d'un passage surligné deux fois, et
# exporte le carnet en Markdown dans la langue de l'interface.
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


@pytest.fixture
def french():
    from i18n import current_lang, set_lang

    before = current_lang()
    set_lang("fr")
    yield
    set_lang(before)


def _doc(name="cours.pdf", pages=10, engine="pdfium_scroll") -> int:
    from db.documents import upsert_document

    return upsert_document(f"/tmp/{name}", name, pages, engine, False)


def _hl(doc_id, page=2, quote="un passage", **extra):
    from services.annotations import create_highlight

    return create_highlight(doc_id, {"page": page, "quote": quote, "rects": [[1, 2, 30, 12]], **extra})


def test_presets_are_seeded_on_demand_and_only_once(fresh_db):
    from config.settings import ANNOTATION_PRESETS
    from services.annotations import delete_label, labels_payload

    labels = labels_payload()
    assert [(label["preset"], label["color"]) for label in labels] == list(ANNOTATION_PRESETS)
    assert labels_payload() == labels

    # Une étiquette prédéfinie supprimée ne revient pas au prochain chargement.
    delete_label(labels[-1]["id"])
    assert len(labels_payload()) == len(ANNOTATION_PRESETS) - 1


def test_label_validation(fresh_db, monkeypatch):
    from services import annotations

    with pytest.raises(ValueError):
        annotations.create_label("Rose", "fuchsia")
    with pytest.raises(ValueError):
        annotations.create_label("   ", "pink")
    with pytest.raises(ValueError):
        annotations.create_label("x" * 41, "pink")
    label = annotations.create_label("  Formule   clé ", "pink")
    assert (label["name"], label["color"], label["preset"]) == ("Formule clé", "pink", None)

    monkeypatch.setattr(annotations, "ANNOTATION_MAX_LABELS", len(annotations.labels_payload()))
    with pytest.raises(ValueError):
        annotations.create_label("Une de trop", "gray")


def test_rename_recolor_reorder_and_delete_labels(fresh_db):
    from services import annotations

    labels = annotations.labels_payload()
    first = labels[0]
    renamed = annotations.update_label(first["id"], {"name": "Essentiel", "color": "cyan"})
    assert (renamed["name"], renamed["color"]) == ("Essentiel", "cyan")
    assert annotations.update_label(first["id"], {"name": None})["name"] is None, "nom traduit rendu"
    custom = annotations.create_label("Perso", "lime")
    with pytest.raises(ValueError):
        annotations.update_label(custom["id"], {"name": None})

    ids = [label["id"] for label in annotations.labels_payload()]
    reordered = annotations.reorder_labels(list(reversed(ids)))
    assert [label["id"] for label in reordered] == list(reversed(ids))
    with pytest.raises(ValueError):
        annotations.reorder_labels(ids[:-1])

    doc_id = _doc()
    _hl(doc_id, label_id=custom["id"])
    assert annotations.delete_label(custom["id"]) == {"removed": True, "released": 1}
    assert annotations.document_annotations(doc_id)["highlights"][0]["label_id"] is None, "le passage reste"

    for label in annotations.labels_payload()[:-1]:
        annotations.delete_label(label["id"])
    last = annotations.labels_payload()
    assert len(last) == 1
    with pytest.raises(ValueError):
        annotations.delete_label(last[0]["id"])
    with pytest.raises(annotations.AnnotationNotFound):
        annotations.delete_label(9999)


def test_highlight_validation(fresh_db):
    from services import annotations

    doc_id = _doc(pages=3)
    with pytest.raises(annotations.AnnotationNotFound):
        _hl(999)
    for bad in (
        {"page": 0},
        {"page": 4},
        {"quote": "   "},
        {"quote": "x" * 4001},
        {"style": "wavy"},
        {"label_id": 9999},
        {"note": "n" * 4001},
    ):
        with pytest.raises(ValueError):
            _hl(doc_id, **{"page": 2, "quote": "un passage", **bad})
    with pytest.raises(ValueError):
        annotations.create_highlight(doc_id, {"page": 1, "quote": "a", "rects": [[1, 2, 3]]})
    with pytest.raises(ValueError):
        annotations.create_highlight(doc_id, {"page": 1, "quote": "a", "rects": [[1, 2, 3, float("nan")]]})


def test_a_new_highlight_gets_the_label_of_its_color(fresh_db):
    from services.annotations import labels_payload

    by_preset = {label["preset"]: label["id"] for label in labels_payload()}
    doc_id = _doc()
    assert _hl(doc_id, quote="sans rien")["label_id"] == by_preset["important"]
    assert _hl(doc_id, quote="ancienne couleur", color="explain")["label_id"] == by_preset["definition"]
    chosen = _hl(doc_id, quote="choisie", label_id=by_preset["idea"], style="underline")
    assert (chosen["label_id"], chosen["style"]) == (by_preset["idea"], "underline")


def test_highlighting_again_keeps_the_note_and_the_label(fresh_db):
    from services.annotations import labels_payload, update_highlight

    by_preset = {label["preset"]: label["id"] for label in labels_payload()}
    doc_id = _doc()
    first = _hl(doc_id, label_id=by_preset["review"], style="outline", note="À retenir")
    again = _hl(doc_id)
    assert again["id"] == first["id"]
    assert (again["label_id"], again["style"], again["note"]) == (by_preset["review"], "outline", "À retenir")

    # Édition partielle : seules les clés données changent ; None efface.
    edited = update_highlight(doc_id, first["id"], {"style": "strike"})
    assert (edited["style"], edited["note"], edited["label_id"]) == ("strike", "À retenir", by_preset["review"])
    cleared = update_highlight(doc_id, first["id"], {"note": None, "label_id": None})
    assert (cleared["note"], cleared["label_id"]) == (None, None)
    assert update_highlight(doc_id, first["id"], {"note": "  "})["note"] is None


def test_an_item_of_another_document_is_not_found(fresh_db):
    from services import annotations

    mine, other = _doc("a.pdf"), _doc("b.pdf")
    highlight = _hl(mine)
    note = annotations.create_note(mine, {"kind": "sticky", "page": 1, "x": 10, "y": 20, "body": "ici"})
    with pytest.raises(annotations.AnnotationNotFound):
        annotations.update_highlight(other, highlight["id"], {"note": "x"})
    with pytest.raises(annotations.AnnotationNotFound):
        annotations.update_note(other, note["id"], {"body": "x"})
    assert annotations.delete_highlight(other, highlight["id"]) == 0
    assert annotations.delete_note(other, note["id"]) == 0
    assert len(annotations.document_annotations(mine)["highlights"]) == 1
    assert annotations.delete_highlight(mine, highlight["id"]) == 1


def test_sticky_notes_and_signets(fresh_db):
    from services import annotations

    doc_id = _doc()
    sticky = annotations.create_note(doc_id, {"kind": "sticky", "page": 2, "x": 40.5, "y": 120, "body": " Idée "})
    assert (sticky["x"], sticky["y"], sticky["body"]) == (40.5, 120.0, "Idée")
    for bad in ({"x": -1, "y": 3}, {"x": None, "y": 3}, {"x": float("inf"), "y": 1}):
        with pytest.raises(ValueError):
            annotations.create_note(doc_id, {"kind": "sticky", "page": 2, **bad})
    with pytest.raises(ValueError):
        annotations.create_note(doc_id, {"kind": "memo", "page": 2})
    moved = annotations.update_note(doc_id, sticky["id"], {"x": 5, "y": 6, "body": "Déplacé"})
    assert (moved["x"], moved["y"], moved["body"]) == (5.0, 6.0, "Déplacé")

    # Un signet par page : en poser un second le remplace.
    first = annotations.create_note(doc_id, {"kind": "signet", "page": 4, "body": "Chapitre 2", "x": 3, "y": 3})
    assert (first["x"], first["y"]) == (None, None)
    second = annotations.create_note(doc_id, {"kind": "signet", "page": 4, "body": "Chapitre 2 bis"})
    assert second["id"] == first["id"] and second["body"] == "Chapitre 2 bis"
    kinds = [note["kind"] for note in annotations.document_annotations(doc_id)["notes"]]
    assert sorted(kinds) == ["signet", "sticky"]


def test_a_code_file_sticky_note_has_no_position(fresh_db):
    from services.annotations import create_note, update_note

    doc_id = _doc("script.py", engine="code")
    note = create_note(doc_id, {"kind": "sticky", "page": 1, "x": 10, "y": 20, "body": "Boucle"})
    assert (note["x"], note["y"]) == (None, None)
    assert update_note(doc_id, note["id"], {"x": 4, "y": 4})["x"] is None


def test_markdown_export_in_french(fresh_db, french):
    from db.documents import set_bookmark_page
    from services.annotations import create_note, export_markdown, labels_payload

    by_preset = {label["preset"]: label["id"] for label in labels_payload()}
    doc_id = _doc("Été — cours.pdf")
    set_bookmark_page(doc_id, 5)
    create_note(doc_id, {"kind": "signet", "page": 7, "body": "Exercices", "label_id": by_preset["review"]})
    _hl(doc_id, page=3, quote="# pas un titre\nsuite", label_id=by_preset["definition"], style="underline",
        note="- pas une liste\n1. ni ça\ntexte *gardé*")
    create_note(doc_id, {"kind": "sticky", "page": 3, "x": 1, "y": 1, "body": "> pas une citation"})

    filename, text = export_markdown(doc_id)
    assert filename == "ete-cours-notes.md"
    lines = text.splitlines()
    assert lines[0] == "# Notes — Été — cours.pdf"
    assert "**Marque-page** : page 5" in lines
    assert "- Page 7 — *À revoir* — Exercices" in lines
    assert lines.index("**Marque-page** : page 5") < lines.index("## Page 3")
    assert "> \\# pas un titre" in lines and "> suite" in lines
    assert "*Définition* · souligné" in lines
    assert "\\- pas une liste" in lines and "\\1. ni ça" in lines
    assert "texte *gardé*" in lines, "seules les lignes de structure sont échappées"
    assert "**Post-it** (*Sans étiquette*)" in lines
    assert "\\> pas une citation" in lines
    # La citation, puis l'étiquette et la note, puis les post-it de la page.
    assert lines.index("> suite") < lines.index("*Définition* · souligné") < lines.index("**Post-it** (*Sans étiquette*)")


def test_markdown_export_in_english(fresh_db):
    from i18n import current_lang, set_lang
    from services.annotations import export_markdown

    before = current_lang()
    set_lang("en")
    try:
        doc_id = _doc()
        _hl(doc_id, page=2, quote="a passage", style="strike")
        _, text = export_markdown(doc_id)
        assert "## Page 2" in text
        assert "*Important* · struck through" in text
        _, empty = export_markdown(_doc("vide.pdf"))
        assert "No notes on this document." in empty
        from db.documents import set_bookmark_page

        set_bookmark_page(doc_id, 4)
        assert "**Bookmark**: page 4" in export_markdown(doc_id)[1]
    finally:
        set_lang(before)


def test_the_notebook_order_is_the_reading_order(fresh_db):
    """Le carnet et l'export lisent la page de haut en bas, quel que soit
    l'ordre dans lequel les passages ont été surlignés."""
    from services.annotations import document_annotations, export_markdown

    doc_id = _doc()
    from services.annotations import create_highlight

    create_highlight(doc_id, {"page": 2, "quote": "en bas", "rects": [[10, 500, 80, 512]]})
    create_highlight(doc_id, {"page": 2, "quote": "en haut", "rects": [[10, 100, 80, 112]]})
    create_highlight(doc_id, {"page": 1, "quote": "page un", "rects": [[10, 700, 80, 712]]})
    assert [h["quote"] for h in document_annotations(doc_id)["highlights"]] == ["page un", "en haut", "en bas"]
    text = export_markdown(doc_id)[1]
    assert text.index("> page un") < text.index("> en haut") < text.index("> en bas")


def test_the_label_limits_come_from_the_settings(fresh_db):
    from config.settings import ANNOTATION_DEFAULT_COLOR, ANNOTATION_LABEL_NAME_MAX, ANNOTATION_MAX_LABELS
    from services.annotations import label_limits

    assert label_limits() == {
        "name_max": ANNOTATION_LABEL_NAME_MAX,
        "max_labels": ANNOTATION_MAX_LABELS,
        "default_color": ANNOTATION_DEFAULT_COLOR,
    }
