# test_reading_pace.py — L'allure de lecture et le temps restant d'un document.
#
# La carte « Reprendre » annonçait la médiane des séances, quiz et langues
# compris : 7 min pour qui lit par tranches de 22, la même durée pour tous les
# documents. Ces tests figent l'allure qui la remplace : la médiane des pages
# LUES, du document d'abord, de sa nature ensuite, un défaut annoncé sinon.
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


def _doc(name: str, pages: int = 10, engine: str = "pdfium_scroll") -> dict:
    from db.documents import get_document, upsert_document

    doc_id = upsert_document(f"/tmp/{name}", name, pages, engine, False)
    return get_document(doc_id)


def _session(doc: dict, dwell: dict[int, float], pages_read: int | None = None) -> int:
    """Une séance close avec ces temps par page ; `pages_read` par défaut : les
    pages d'au moins 5 s, comme le compte du serveur."""
    from db.page_dwell import save_page_dwell
    from db.sessions import start_session, update_session_progress

    sid = start_session(doc["id"])
    save_page_dwell(sid, dwell, {page: 1 for page in dwell})
    read = sum(1 for s in dwell.values() if s >= 5.0) if pages_read is None else pages_read
    update_session_progress(sid, pages_read=read)
    return sid


def test_nothing_measured_gives_the_default_announced_as_such(fresh_db):
    from config.settings import READING_ESTIMATE_DEFAULT_PAGE_S
    from services.reading_pace import seconds_per_page

    pace = seconds_per_page(_doc("vide.pdf"))
    assert pace == {
        "seconds": READING_ESTIMATE_DEFAULT_PAGE_S, "measured": False, "samples": 0, "scope": "default",
    }


def test_the_document_median_wins_from_five_samples(fresh_db):
    from services.reading_pace import seconds_per_page

    doc, other = _doc("cours.pdf"), _doc("autre.pdf")
    _session(other, {p: 300.0 for p in range(1, 9)})
    _session(doc, {1: 40.0, 2: 60.0, 3: 80.0, 4: 100.0})
    # Quatre pages du document : pas encore assez, l'allure vient des PDF.
    pace = seconds_per_page(doc)
    assert pace["scope"] == "kind" and pace["measured"] is True
    assert pace["samples"] == 12
    assert pace["seconds"] == 300.0  # médiane de tous les PDF

    _session(doc, {5: 2000.0})  # une page restée ouverte pendant un repas
    pace = seconds_per_page(doc)
    assert pace["scope"] == "document"
    assert pace["samples"] == 5
    assert pace["seconds"] == 80.0  # la médiane ne s'en émeut pas


def test_a_code_file_does_not_borrow_the_pace_of_pdfs(fresh_db):
    from services.reading_pace import seconds_per_page

    _session(_doc("manuel.pdf"), {p: 150.0 for p in range(1, 10)})
    script = _doc("script.py", engine="code")
    assert seconds_per_page(script)["scope"] == "default"

    _session(_doc("module.py", engine="code"), {p: 30.0 for p in range(1, 7)})
    pace = seconds_per_page(script)
    assert pace["scope"] == "kind"
    assert pace["seconds"] == 30.0


def test_skimmed_pages_and_sessions_without_reading_are_ignored(fresh_db):
    from db.page_dwell import reading_dwell_samples
    from services.reading_pace import seconds_per_page

    doc = _doc("cours.pdf")
    # Pages traversées en défilant (sous 5 s) : pas une lecture.
    _session(doc, {p: 2.0 for p in range(1, 10)} | {10: 60.0})
    # Séance quittée depuis le sas avant la garde : du temps « sur la page 1 »
    # dans une séance qui n'a rien lu.
    _session(doc, {1: 900.0, 2: 900.0, 3: 900.0, 4: 900.0, 5: 900.0}, pages_read=0)
    assert reading_dwell_samples(min_dwell_s=5.0, limit=100, document_id=doc["id"]) == [60.0]
    assert seconds_per_page(doc)["scope"] == "default"


def test_remaining_counts_from_the_last_page_seen(fresh_db):
    from db.documents import get_document, update_last_page
    from services.reading_pace import remaining

    doc = _doc("cours.pdf", pages=40)
    _session(doc, {p: 90.0 for p in range(1, 7)})
    update_last_page(doc["id"], 31)
    left = remaining(get_document(doc["id"]))
    assert left["pages"] == 10  # la page 31 reste à lire, jusqu'à la 40
    assert left["seconds_per_page"] == 90.0
    assert left["minutes"] == 15
    assert left["measured"] is True and left["scope"] == "document"


def test_remaining_counts_from_the_bookmark_before_the_last_page_seen(fresh_db):
    """Le marque-page est posé par l'élève ; la dernière page vue bouge seule
    (une séance passée à feuilleter l'annexe). Le temps restant part du premier."""
    from db.documents import get_document, set_bookmark_page, update_last_page
    from services.reading_pace import remaining

    doc = _doc("cours.pdf", pages=40)
    update_last_page(doc["id"], 38)
    set_bookmark_page(doc["id"], 21)
    assert remaining(get_document(doc["id"]))["pages"] == 20

    set_bookmark_page(doc["id"], 99)  # hors du document : ignoré, pas une page fantôme
    assert remaining(get_document(doc["id"]))["pages"] == 3


def test_a_document_without_pages_has_no_remaining_time(fresh_db):
    from services.reading_pace import remaining

    assert remaining(_doc("vide.pdf", pages=0)) is None
    assert remaining(None) is None


def test_an_unreadable_database_falls_back_to_the_default(fresh_db, monkeypatch):
    from services import reading_pace

    def _boom(**_kw):
        raise RuntimeError("base illisible")

    monkeypatch.setattr(reading_pace, "reading_dwell_samples", _boom)
    left = reading_pace.remaining(_doc("cours.pdf", pages=3))
    assert left["measured"] is False
    assert left["minutes"] == 6
