# test_reader_find.py — Ctrl/Cmd+F du lecteur (services/reader_find).
#
# Ce qu'il faut tenir : un total par page qui est celui des occurrences
# surlignées, un PDF scanné qui le dit au lieu d'annoncer « aucun résultat »,
# des plages en UTF-16 pour le navigateur, un index qui suit le fichier, et un
# verrou PDFium relâché pendant l'indexation d'un gros document.
import os
import threading

import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    import db
    from db import close_connection
    from services import reader_find

    close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nwol.db"))
    monkeypatch.setattr(reader_find, "_INDEX", type(reader_find._INDEX)())
    from db.schema import initialize_schema

    initialize_schema()
    yield
    close_connection()


def _pdf(make_pdf, path, pages: list[str]) -> int:
    from db.documents import upsert_document

    return upsert_document(make_pdf(path, pages), path.name, len(pages), "pdfium_scroll", False)


def _code(path, text: str) -> int:
    from db.documents import upsert_document
    from services import code_reader

    path.write_text(text, encoding="utf-8")
    return upsert_document(str(path), path.name, code_reader.page_count(str(path)), "code", False)


def test_counts_occurrences_page_by_page(fresh_db, tmp_path, make_pdf):
    from services.reader_find import find_in_document

    doc_id = _pdf(make_pdf, tmp_path / "cours.pdf", [
        "Une Équation, deux equations.", "Rien ici.", "Équation différen-\ntielle : une équation.",
    ])
    result = find_in_document(doc_id, "  ÉQUATION ")
    assert result == {
        "query": "equation",
        "total": 4,
        "pages": [{"page": 1, "count": 2}, {"page": 3, "count": 2}],
        "searchable": True,
        "too_short": False,
    }
    assert find_in_document(doc_id, "différentielle")["pages"] == [{"page": 3, "count": 1}]
    assert find_in_document(999, "equation") is None


def test_a_query_too_short_searches_nothing(fresh_db, tmp_path, make_pdf):
    from services.reader_find import find_in_document, find_on_page

    doc_id = _pdf(make_pdf, tmp_path / "court.pdf", ["a b c d e"])
    result = find_in_document(doc_id, " é ")
    assert result["too_short"] is True and result["total"] == 0 and result["pages"] == []
    assert find_on_page(doc_id, 1, "e") == {"page": 1, "rects": [], "truncated": False}


def test_a_scanned_pdf_is_said_to_have_no_text(fresh_db, tmp_path, make_pdf):
    from services.reader_find import find_in_document

    doc_id = _pdf(make_pdf, tmp_path / "scan.pdf", ["", ""])
    result = find_in_document(doc_id, "equation")
    assert result["searchable"] is False and result["total"] == 0


def test_pdf_occurrences_are_one_list_of_rects_each(fresh_db, tmp_path, make_pdf):
    from services.reader_find import find_on_page

    doc_id = _pdf(make_pdf, tmp_path / "rects.pdf", ["Une Équation différen-\ntielle, une equation."])
    hits = find_on_page(doc_id, 1, "equation")
    assert hits["truncated"] is False and len(hits["rects"]) == 2
    assert all(len(rects) == 1 and len(rects[0]) == 4 for rects in hits["rects"])
    across = find_on_page(doc_id, 1, "differentielle")["rects"]
    assert len(across) == 1 and len(across[0]) == 2  # un rect par ligne


def test_code_ranges_are_utf16_offsets_of_the_displayed_text(fresh_db, tmp_path):
    from services.reader_find import find_in_document, find_on_page

    doc_id = _code(tmp_path / "demo.py", "x = '😀 Équation'\ny = 'equation'\n")
    assert find_in_document(doc_id, "equation")["pages"] == [{"page": 1, "count": 2}]
    hits = find_on_page(doc_id, 1, "equation")
    # « x = ' » (5) + l'emoji (DEUX unités UTF-16) + l'espace : la première
    # occurrence commence à 8 pour le navigateur, à 7 pour Python — et tout ce
    # qui suit l'emoji est décalé d'une unité (22 pour Python, 23 ici).
    assert hits == {"page": 1, "ranges": [[8, 16], [23, 31]], "truncated": False}


def test_page_texts_are_the_texts_of_the_displayed_blocks(tmp_path):
    from services import code_reader

    path = tmp_path / "long.py"
    path.write_text("\n".join(f"ligne_{n} = {n}" for n in range(1, 101)), encoding="utf-8")
    texts = code_reader.page_texts(str(path))
    assert len(texts) == code_reader.page_count(str(path)) == 3
    for page, text in enumerate(texts, start=1):
        assert text == code_reader.page_block(str(path), page)["text"]
    empty = tmp_path / "vide.py"
    empty.write_text("", encoding="utf-8")
    assert code_reader.page_texts(str(empty)) == [code_reader.page_block(str(empty), 1)["text"]] == [""]


def test_the_index_is_rebuilt_when_the_file_changes(fresh_db, tmp_path):
    from services import reader_find

    path = tmp_path / "evolue.py"
    doc_id = _code(path, "alpha = 1\n")
    assert reader_find.find_in_document(doc_id, "beta")["total"] == 0
    path.write_text("alpha = 1\nbeta = 2\n", encoding="utf-8")
    stat = os.stat(path)
    os.utime(path, (stat.st_atime, stat.st_mtime + 5))
    assert reader_find.find_in_document(doc_id, "beta")["total"] == 1


def test_forget_drops_the_index(fresh_db, tmp_path, make_pdf):
    from services import reader_find

    doc_id = _pdf(make_pdf, tmp_path / "oubli.pdf", ["Une equation."])
    reader_find.find_in_document(doc_id, "equation")
    assert doc_id in reader_find._INDEX
    reader_find.forget(doc_id)
    assert doc_id not in reader_find._INDEX


def test_the_index_is_bounded(fresh_db, tmp_path, make_pdf):
    from services import reader_find

    ids = [_pdf(make_pdf, tmp_path / f"doc{n}.pdf", [f"Document {n}"]) for n in range(5)]
    for doc_id in ids:
        reader_find.find_in_document(doc_id, "document")
    assert list(reader_find._INDEX) == ids[-reader_find._INDEX_MAX_DOCS:]


def test_the_pdfium_lock_is_released_between_batches(fresh_db, tmp_path, make_pdf, monkeypatch):
    """Lots de deux pages : entre deux lots, un autre thread (une page demandée
    par le lecteur) doit pouvoir prendre le verrou PDFium."""
    from pdf_viewer.engine import PDFIUM_LOCK
    from pdf_viewer.pdf_document import PdfDocument
    from services import reader_find

    doc_id = _pdf(make_pdf, tmp_path / "gros.pdf", [f"Page {n} equation" for n in range(1, 7)])
    monkeypatch.setattr(reader_find, "_INDEX_BATCH_PAGES", 2)
    between: list[bool] = []

    class Spy(PdfDocument):
        opened = 0

        def open(self):
            Spy.opened += 1
            if Spy.opened == 3:  # 1 : nombre de pages, 2 : premier lot, 3 : second lot
                def other_reader():
                    if PDFIUM_LOCK.acquire(timeout=2):
                        between.append(True)
                        PDFIUM_LOCK.release()

                thread = threading.Thread(target=other_reader)
                thread.start()
                thread.join(timeout=3)
            return super().open()

    monkeypatch.setattr(reader_find, "PdfDocument", Spy)
    assert reader_find.find_in_document(doc_id, "equation")["total"] == 6
    assert between == [True]
    assert Spy.opened == 4  # le nombre de pages, puis trois lots


def test_a_page_highlights_at_most_the_cap(fresh_db, tmp_path, make_pdf, monkeypatch):
    from services import reader_find

    monkeypatch.setattr(reader_find, "READER_FIND_MAX_PAGE_HITS", 3)
    doc_id = _pdf(make_pdf, tmp_path / "dense.pdf", ["le le le le le"])
    hits = reader_find.find_on_page(doc_id, 1, "le")
    assert len(hits["rects"]) == 3 and hits["truncated"] is True
    # Le résumé, lui, compte tout.
    assert reader_find.find_in_document(doc_id, "le")["total"] == 5
    code_id = _code(tmp_path / "dense.py", "le le le le le\n")
    code_hits = reader_find.find_on_page(code_id, 1, "le")
    assert len(code_hits["ranges"]) == 3 and code_hits["truncated"] is True
