# La fiche d'un document (résumé, mots-clés) part en fond pendant que le lecteur
# s'ouvre. Fermer ce lecteur coupe toute génération en vol, la sienne comprise :
# elle doit se remettre en file, pas se déclarer en échec.
from db.documents import get_document, upsert_document
from llm.ollama_client import CANCELLED_MESSAGE
from services import library, orchestrator


def _doc(tmp_path, monkeypatch):
    import db

    from db import close_connection
    from db.schema import initialize_schema

    close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nwol.db"))
    initialize_schema()
    monkeypatch.setattr(library, "page_text", lambda doc_id, page: "Un texte assez long pour une fiche.")
    # Remise en file synchrone : on teste la logique, pas le délai.
    monkeypatch.setattr(orchestrator, "_DIGEST_REQUEUE_DELAY_S", 0.0)
    return upsert_document(str(tmp_path / "a.pdf"), "a.pdf", 3, "pdfium_scroll", False)


def test_cancelled_digest_is_requeued_then_completes(tmp_path, monkeypatch):
    doc_id = _doc(tmp_path, monkeypatch)
    calls = []

    def fake_async(doc_title, excerpt, on_success, on_error, **_kw):
        calls.append(1)
        if len(calls) == 1:
            on_error(CANCELLED_MESSAGE)  # coupée par la fermeture d'un lecteur
        else:
            on_success({"subject": "maths", "summary": "Résumé.", "keywords": ["rolle"]})

    monkeypatch.setattr(orchestrator, "generate_document_digest_async", fake_async)
    orchestrator.generate_document_digest(doc_id, "a.pdf")

    assert len(calls) == 2
    doc = get_document(doc_id)
    assert doc["digest_status"] == "done"
    assert doc["auto_summary"] == "Résumé."


def test_digest_gives_up_after_bounded_requeues(tmp_path, monkeypatch):
    doc_id = _doc(tmp_path, monkeypatch)
    calls = []

    def always_cancelled(doc_title, excerpt, on_success, on_error, **_kw):
        calls.append(1)
        on_error(CANCELLED_MESSAGE)

    monkeypatch.setattr(orchestrator, "generate_document_digest_async", always_cancelled)
    orchestrator.generate_document_digest(doc_id, "a.pdf")

    assert len(calls) == orchestrator._DIGEST_REQUEUE_MAX
    assert get_document(doc_id)["digest_status"] == "failed"


def test_real_failure_is_not_requeued(tmp_path, monkeypatch):
    doc_id = _doc(tmp_path, monkeypatch)
    calls = []

    def broken(doc_title, excerpt, on_success, on_error, **_kw):
        calls.append(1)
        on_error("Ollama indisponible")

    monkeypatch.setattr(orchestrator, "generate_document_digest_async", broken)
    orchestrator.generate_document_digest(doc_id, "a.pdf")

    assert len(calls) == 1
    assert get_document(doc_id)["digest_status"] == "failed"


def test_requeue_is_deferred_so_the_next_document_goes_first(tmp_path, monkeypatch):
    """La fiche coupée ne reprend pas le worker tout de suite : elle repasse
    APRÈS un délai, pour laisser passer l'accroche du document suivant."""
    import threading

    doc_id = _doc(tmp_path, monkeypatch)
    monkeypatch.setattr(orchestrator, "_DIGEST_REQUEUE_DELAY_S", 0.05)
    second_call = threading.Event()
    calls = []

    def fake_async(doc_title, excerpt, on_success, on_error, **_kw):
        calls.append(1)
        if len(calls) == 1:
            on_error(CANCELLED_MESSAGE)
        else:
            on_success({"subject": "maths", "summary": "Résumé.", "keywords": ["rolle"]})
            second_call.set()  # après l'écriture : le test relit depuis un autre thread

    monkeypatch.setattr(orchestrator, "generate_document_digest_async", fake_async)
    orchestrator.generate_document_digest(doc_id, "a.pdf")

    assert len(calls) == 1, "la remise en file doit être différée, pas immédiate"
    assert second_call.wait(2)
    assert get_document(doc_id)["digest_status"] == "done"
