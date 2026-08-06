"""Tests du RAG plein-document (services/pdf_rag.py)."""
from services import pdf_rag


def _chunk(page, text):
    return {"page": page, "text": text, "folded": pdf_rag._fold(text)}


def test_rank_chunks_scores_by_distinct_terms_then_frequency():
    chunks = [
        _chunk(1, "photosynthese et chlorophylle dans la cellule"),  # 2 termes distincts
        _chunk(2, "photosynthese photosynthese photosynthese"),       # 1 distinct, fréquent
        _chunk(3, "sujet sans rapport"),                              # 0 -> écarté
    ]
    terms = ["photosynthese", "chlorophylle"]
    ranked = pdf_rag.rank_chunks(chunks, terms, current_page=9, top_k=3)
    assert [c["page"] for c in ranked] == [1, 2]  # distinct prime sur fréquence


def test_rank_chunks_folds_accents_and_case():
    # Le chunk est déjà plié ; les termes le sont aussi (comme extract_terms).
    chunks = [_chunk(4, "La PHOTOSYNTHÈSE est essentielle")]
    ranked = pdf_rag.rank_chunks(chunks, ["photosynthese"], current_page=1, top_k=3)
    assert len(ranked) == 1 and ranked[0]["page"] == 4


def test_rank_chunks_excludes_current_page():
    chunks = [_chunk(5, "photosynthese ici")]
    assert pdf_rag.rank_chunks(chunks, ["photosynthese"], current_page=5, top_k=3) == []


def test_rank_chunks_respects_top_k():
    chunks = [_chunk(i, "photosynthese") for i in range(1, 6)]
    ranked = pdf_rag.rank_chunks(chunks, ["photosynthese"], current_page=99, top_k=2)
    assert len(ranked) == 2


def test_retrieve_returns_empty_without_meaningful_terms():
    # Que des mots vides -> aucun terme -> aucune recherche (index non sollicité).
    assert pdf_rag.retrieve(doc_id=123, question="le la les de et", current_page=1) == []


def test_retrieve_end_to_end(tmp_path, monkeypatch):
    import fitz

    pdf = tmp_path / "doc.pdf"
    doc = fitz.open()
    pages = [
        "La photosynthese convertit la lumiere en energie chimique.",  # page 1
        "Les mitochondries produisent l'ATP par la respiration.",      # page 2
        "Introduction generale au chapitre.",                          # page 3 (page courante)
    ]
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12)
    doc.save(str(pdf))
    doc.close()

    monkeypatch.setattr(pdf_rag, "get_document", lambda doc_id: {"path": str(pdf)})
    pdf_rag.clear_index(777)

    results = pdf_rag.retrieve(777, "Comment fonctionne la photosynthese ?", current_page=3)
    assert len(results) == 1
    assert results[0]["page"] == 1
    assert "photosynth" in results[0]["text"].lower()

    # Une question dont la réponse est sur la page courante ne renvoie rien
    # (la page visible est déjà fournie au LLM par ailleurs).
    on_page = pdf_rag.retrieve(777, "photosynthese ?", current_page=1)
    assert on_page == []

    pdf_rag.clear_index(777)
