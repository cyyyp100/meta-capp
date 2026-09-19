"""Tests du RAG plein-document (services/pdf_rag.py)."""
import os

import pytest

from config.settings import ASSISTANT_RAG_SEARCH_TOP_K, ASSISTANT_RAG_TOP_K
from services import pdf_rag, rag_lexicon


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


def _chunk(page, text, table=False, head=0):
    folded = pdf_rag._fold(text)
    chunk = {"page": page, "text": text, "folded": folded, "len": len(folded), "table": table}
    if table:
        chunk["head"] = head
    return chunk


# ── Classement ───────────────────────────────────────────────────────────────

def test_rank_chunks_scores_by_distinct_terms_then_frequency():
    chunks = [
        _chunk(1, "photosynthese et chlorophylle dans la cellule"),  # 2 termes distincts
        _chunk(2, "photosynthese photosynthese photosynthese"),       # 1 distinct, fréquent
        _chunk(3, "sujet sans rapport"),                              # 0 -> écarté
    ]
    terms = ["photosynthese", "chlorophylle"]
    ranked = pdf_rag.rank_chunks(chunks, terms, current_page=9, top_k=3)
    assert [c["page"] for c in ranked] == [1, 2]  # distinct prime sur fréquence


def test_rank_chunks_idf_favours_rare_terms():
    # « reptile » est partout, « implementation » dans un seul chunk : le chunk
    # qui porte le terme rare passe devant un chunk qui répète le terme banal.
    chunks = [
        _chunk(1, "reptile reptile reptile reptile"),
        _chunk(2, "reptile implementation details"),
        _chunk(3, "reptile again"),
        _chunk(4, "reptile once more"),
    ]
    ranked = pdf_rag.rank_chunks(chunks, ["reptile", "implementation"], current_page=9, top_k=2)
    assert ranked[0]["page"] == 2


def test_rank_chunks_accepts_weighted_terms():
    chunks = [_chunk(1, "alpha"), _chunk(2, "beta")]
    ranked = pdf_rag.rank_chunks(chunks, [("alpha", 0.2), ("beta", 1.0)], current_page=9, top_k=2)
    assert [c["page"] for c in ranked] == [2, 1]


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


def test_stem_joins_inflections_fr_en():
    assert pdf_rag._stem("configurations") in pdf_rag._fold("configuration")
    assert pdf_rag._stem(pdf_rag._fold("implémentation")) in "implementation"
    assert pdf_rag._stem("focal") == "focal"  # court : intact
    # 7-8 lettres : deux caractères seulement — « inter » matcherait « intermediate ».
    assert pdf_rag._stem("interne") == "intern"
    assert pdf_rag._stem("methode") in "methods"


def test_rank_chunks_boosts_captioned_tables_only():
    # Même contenu lexical : la table légendée passe devant la prose et devant
    # un bloc chiffré sans légende (bibliographie).
    prose = _chunk(1, "reptile configuration and reptile again")
    untitled = _chunk(2, "reptile configuration 1.2 3.4\n5.6 7.8", table=True, head=0)
    table = _chunk(3, "TABLE I\nREPTILE CONFIGURATION.\n0.335 7.75", table=True, head=32)
    ranked = pdf_rag.rank_chunks([prose, untitled, table], ["reptile", "configurat"], current_page=9, top_k=3)
    assert ranked[0]["page"] == 3
    assert {c["page"] for c in ranked[1:]} == {1, 2}


def test_rank_chunks_spreads_results_across_pages():
    # Quatre chunks de la page 1 dominent ; au plus _MAX_PER_PAGE d'entre eux
    # sont rendus avant la page 2, mais ils reviennent si rien d'autre ne remplit.
    chunks = [_chunk(1, "photosynthese " * 4) for _ in range(4)] + [_chunk(2, "photosynthese")]
    ranked = pdf_rag.rank_chunks(chunks, ["photosynthese"], current_page=9, top_k=4)
    assert [c["page"] for c in ranked] == [1] * pdf_rag._MAX_PER_PAGE + [2]
    ranked = pdf_rag.rank_chunks(chunks, ["photosynthese"], current_page=9, top_k=5)
    assert [c["page"] for c in ranked] == [1] * pdf_rag._MAX_PER_PAGE + [2, 1]


# ── Résolution des termes ────────────────────────────────────────────────────

_EN_CHUNKS = [
    _chunk(1, "The learning rate of the inner loop is 0.001 for every organ."),
    _chunk(2, "Hyperparameters were tuned on the liver fold; parameters are listed in Table I."),
    _chunk(3, "TABLE I\nMETA-TRAINING CONFIGURATIONS.\nInner lr 0.001", table=True, head=38),
]


def test_resolve_terms_keeps_present_stems():
    resolved = pdf_rag.resolve_terms([("configuration", 1.0), ("organes", 1.0)], _EN_CHUNKS)
    assert resolved == [("configurat", 1.0), ("organ", 1.0)]  # « organes » → lexique → « organ »


def test_resolve_terms_translates_absent_words():
    # « taux d'apprentissage » n'a aucun radical commun avec « learning rate ».
    resolved = dict(pdf_rag.resolve_terms([("taux", 1.0), ("apprentissage", 0.5)], _EN_CHUNKS))
    assert resolved == {"rate": 1.0, "learni": 0.5}


def test_resolve_terms_fixes_typos_against_document_vocabulary():
    # « apramétrage » (faute + FR) → « paramete(rs) », présent dans le document.
    resolved = pdf_rag.resolve_terms([("aprametrage", 1.0)], _EN_CHUNKS)
    assert resolved == [("paramete", 1.0)]
    # Trop court pour un rapprochement fiable : gardé tel quel (poids nul de fait).
    assert pdf_rag.resolve_terms([("coute", 1.0)], _EN_CHUNKS) == [("coute", 1.0)]
    # Hors de portée : son radical, gardé tel quel.
    assert pdf_rag.resolve_terms([("photosynthese", 1.0)], _EN_CHUNKS) == [("photosynth", 1.0)]


def test_expand_terms_adds_synonyms_at_reduced_weight_without_nesting():
    terms = [("hyperparametres", 1.0)]
    resolved = pdf_rag.resolve_terms(terms, _EN_CHUNKS)
    assert resolved == [("hyperparamet", 1.0)]
    expanded = pdf_rag.expand_terms(terms, resolved, _EN_CHUNKS)
    stems = dict(expanded)
    assert stems["hyperparamet"] == 1.0
    assert stems["configurat"] < 1.0                # synonyme présent : ajouté, poids réduit
    assert "parame" not in stems                    # emboîté dans « hyperparamet » : pas deux fois
    assert "setti" not in stems                     # absent du document : pas ajouté


def test_lexicon_is_bidirectional_and_tolerates_plurals():
    assert rag_lexicon.translations("taux") == ("rate",)
    assert "taux" in rag_lexicon.translations("rate")
    assert rag_lexicon.translations("reseaux") == ("network",)
    assert rag_lexicon.translations("photosynthese") == ()
    assert "configuration" in rag_lexicon.synonyms("hyperparametres")
    assert rag_lexicon.synonyms("reptile") == ()


def test_page_coverage_counts_only_terms_present_in_document():
    chunks = _EN_CHUNKS + [_chunk(7, "This page discusses the learning rate only.")]
    terms = [("learni", 1.0), ("rate", 1.0), ("organ", 1.0), ("photosynthese", 1.0)]
    # « photosynthese » n'est nulle part : hors du compte. La page 7 couvre 2 des 3 autres.
    assert pdf_rag.page_coverage(chunks, terms, current_page=7) == 2 / 3
    assert pdf_rag.page_coverage(chunks, terms, current_page=1) == 1.0
    assert pdf_rag.page_coverage(chunks, [("photosynthese", 1.0)], current_page=1) == 0.0


# ── Découpage ────────────────────────────────────────────────────────────────

_TABLE_PAGE = """5
TABLE I
META-TRAINING CONFIGURATIONS. THE MAML FAMILY USES ADAMW
FOR THE OUTER LOOP AND 100 EPISODES PER EPOCH.
Reptile FOMAML MAML
Outer step (ε, β) 0.335 7.75×10−6 7.75×10−6
Inner lr, training 5.75×10−4 3.05×10−3 3.05×10−3
Inner steps (train / val.) 5 / 20 8 / 19 8 / 19
Focal α 0.25 0.25 0.25
Meta-gradient clipping none 5 5
drawn uniformly from the seen organs. Table I summarizes
the three configurations. Reptile and FOMAML were trained
on NVIDIA L40S GPUs and second-order MAML on A100
GPUs.
"""


def test_chunk_keeps_titled_table_whole():
    chunks = pdf_rag._chunk_page_text(_TABLE_PAGE)
    tables = [text for (text, is_table) in chunks if is_table]
    assert len(tables) == 1
    table = tables[0]
    assert table.startswith("TABLE I\n")  # le numéro de page orphelin n'est pas collé devant
    assert "META-TRAINING CONFIGURATIONS" in table
    # La légende (titre + description) est l'en-tête de la table, ses rangées non.
    assert pdf_rag._caption_chars(table) == len("TABLE I\nMETA-TRAINING CONFIGURATIONS. THE MAML FAMILY USES ADAMW\nFOR THE OUTER LOOP AND 100 EPISODES PER EPOCH.\nReptile FOMAML MAML\n")
    assert pdf_rag._caption_chars("1.0 2.0\n3.0 4.0") == 0
    assert "Outer step (ε, β) 0.335" in table
    assert "Meta-gradient clipping none 5 5" in table  # rangée peu chiffrée, gardée
    prose = [text for (text, is_table) in chunks if not is_table]
    assert any("drawn uniformly" in p for p in prose)
    assert not any("0.335" in p for p in prose)


def test_render_table_names_columns_when_header_is_identifiable():
    table = next(text for (text, is_table) in pdf_rag._chunk_page_text(_TABLE_PAGE) if is_table)
    rendered = pdf_rag._render_table(table)
    assert "Outer step (ε, β): Reptile=0.335 · FOMAML=7.75×10−6 · MAML=7.75×10−6" in rendered
    assert "Inner steps (train / val.): Reptile=5 / 20 · FOMAML=8 / 19 · MAML=8 / 19" in rendered
    assert "Meta-gradient clipping none 5 5" in rendered  # 2 valeurs pour 3 colonnes : brute
    assert rendered.startswith("TABLE I\nMETA-TRAINING CONFIGURATIONS.")  # légende et en-tête conservés
    # « ± » recollé en une cellule ; en-tête à mots multiples : rien n'est réaligné.
    assert "Liver: Reptile=75.9 ± 26.0 · FOMAML=30.5 ± 17.7" in pdf_rag._render_table(
        "TABLE II\nReptile FOMAML\nLiver 75.9 ± 26.0 30.5 ± 17.7"
    )
    raw = "TABLE III\nTarget organ Size Test Dice (%)\nLiver large 52.9 ± 15.0"
    assert pdf_rag._render_table(raw) == raw


def test_chunk_does_not_cut_words_and_overlaps_sentences(monkeypatch):
    monkeypatch.setattr(pdf_rag, "ASSISTANT_RAG_CHUNK_CHARS", 80)
    sentences = [f"Phrase {i} sur la photosynthese." for i in range(8)]  # ~30 car. : deux tiennent, pas trois
    chunks = [t for (t, _table) in pdf_rag._chunk_page_text("\n".join(sentences))]
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.endswith(".")  # phrases entières
        assert len(chunk) <= 80
    # Recouvrement : la dernière phrase d'un chunk ouvre le suivant.
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.startswith(prev.split(". ")[-1][:20])


def test_chunk_two_numeric_lines_are_not_a_table():
    text = "Equation (2) gives 3.5 ± 0.2\nand (3) gives 4.1 ± 0.3\nwhich concludes the proof."
    chunks = pdf_rag._chunk_page_text(text)
    assert all(not is_table for (_t, is_table) in chunks)
    assert len(chunks) == 1


# ── Requête ──────────────────────────────────────────────────────────────────

def test_is_search_request_fr_en():
    assert pdf_rag.is_search_request("cherche dans tout l'article")
    assert pdf_rag.is_search_request("can you search the whole paper?")
    assert not pdf_rag.is_search_request("c'est quoi la focal loss ?")
    assert not pdf_rag.is_search_request("que montre la recherche sur ce point ?")
    assert not pdf_rag.is_search_request("what do the researchers conclude?")


def test_query_terms_borrow_history_on_follow_up():
    previous = "quelle est la meilleure configuration (implémentation) de reptile ?"
    terms, search = pdf_rag._query_terms("cherche dans tout l'article", [previous])
    assert search
    words = {t for (t, _w) in terms}
    assert "configuration" in words and "reptile" in words
    assert all(w < 1.0 for (_t, w) in terms)  # termes empruntés : poids réduit


def test_query_terms_ignore_history_on_rich_question():
    terms, search = pdf_rag._query_terms("comment marche la photosynthese des plantes", ["reptile"])
    assert not search
    assert "reptile" not in {t for (t, _w) in terms}


def test_retrieve_returns_empty_without_meaningful_terms():
    # Que des mots vides -> aucun terme -> aucune recherche (index non sollicité).
    assert pdf_rag.retrieve(doc_id=123, question="le la les de et", current_page=1) == []


# ── Index ────────────────────────────────────────────────────────────────────

def test_retrieve_end_to_end(tmp_path, monkeypatch, make_pdf):
    pdf = make_pdf(tmp_path / "doc.pdf", [
        "La photosynthese convertit la lumiere en energie chimique.",  # page 1
        "Les mitochondries produisent l'ATP par la respiration.",      # page 2
        "Introduction generale au chapitre.",                          # page 3 (page courante)
    ])

    monkeypatch.setattr(pdf_rag, "get_document", lambda doc_id: {"path": pdf})
    pdf_rag.clear_index(777)

    results = pdf_rag.retrieve(777, "Comment fonctionne la photosynthese ?", current_page=3)
    assert len(results) == 1
    assert results[0]["page"] == 1
    assert results[0]["table"] is False
    assert "photosynth" in results[0]["text"].lower()

    # Une question dont la réponse est sur la page courante ne renvoie rien
    # (la page visible est déjà fournie au LLM par ailleurs).
    on_page = pdf_rag.retrieve(777, "photosynthese ?", current_page=1)
    assert on_page == []

    pdf_rag.clear_index(777)


def test_retrieve_follow_up_reuses_previous_question(tmp_path, monkeypatch, make_pdf):
    pdf = make_pdf(tmp_path / "doc.pdf", [
        "La photosynthese convertit la lumiere en energie chimique.",
        "Les mitochondries produisent l'ATP par la respiration.",
        "Introduction generale au chapitre.",
    ])
    monkeypatch.setattr(pdf_rag, "get_document", lambda doc_id: {"path": pdf})
    pdf_rag.clear_index(778)

    assert pdf_rag.retrieve(778, "cherche dans tout l'article", current_page=3) == []
    results = pdf_rag.retrieve(
        778, "cherche dans tout l'article", current_page=3,
        recent_questions=["Comment fonctionne la photosynthese ?"],
    )
    assert [r["page"] for r in results] == [1]
    pdf_rag.clear_index(778)


def _index(chunks, vectors=None):
    return {"chunks": chunks, "vocab": pdf_rag._vocabulary(chunks), "mtime": 1.0, "vectors": vectors}


def test_search_depth_follows_page_coverage_and_explicit_request():
    index = _index([
        _chunk(9, "La page visible parle de photosynthese et de chlorophylle."),
        _chunk(1, "Ailleurs : photosynthese, chlorophylle, mitochondries."),
    ])

    def depth(question):
        return pdf_rag._ranked_candidates(1, index, question, 9, None)[1]

    # La page visible couvre la question : les passages ne sont qu'un complément.
    assert depth("photosynthese chlorophylle") == ASSISTANT_RAG_TOP_K
    # Elle ne la couvre pas : la réponse est ailleurs, la recherche s'élargit.
    assert depth("mitochondries chlorophylle") == ASSISTANT_RAG_SEARCH_TOP_K
    # Demande explicite : élargie même si la page couvre.
    assert depth("cherche photosynthese chlorophylle partout") == ASSISTANT_RAG_SEARCH_TOP_K


# ── Couche sémantique ────────────────────────────────────────────────────────

def _fake_embedder(table: dict[str, list[float]]):
    """Embedder déterministe : vecteur par mot-clé trouvé dans le texte
    (préfixes EmbeddingGemma compris), sinon un vecteur neutre."""
    from array import array

    def _embed(texts):
        out = []
        for text in texts:
            hit = next((v for key, v in table.items() if key in text), [0.0, 0.0, 1.0])
            out.append(pdf_rag._normalize(array("f", hit)))
        return out

    return _embed


def test_fuse_rankings_is_reciprocal_rank_fusion():
    a, b, c, d = _chunk(1, "a"), _chunk(2, "b"), _chunk(3, "c"), _chunk(4, "d")
    # b est 2e partout, c 3e partout : ils passent devant a et d, chacun 1er
    # d'une seule liste — la fusion récompense l'accord des deux classements.
    fused = pdf_rag.fuse_rankings([a, b, c], [d, b, c])
    assert fused[0] is b and fused[1] is c
    assert set(map(id, fused)) == {id(a), id(b), id(c), id(d)}
    # Une seule liste : ordre conservé ; listes vides : rien.
    assert pdf_rag.fuse_rankings([c, a]) == [c, a]
    assert pdf_rag.fuse_rankings([], []) == []


def test_semantic_order_uses_cosine_floor_and_table_prior(monkeypatch):
    chunks = [
        _chunk(1, "prose proche"),
        _chunk(2, "TABLE I\nUNE TABLE.\n1 2", table=True, head=17),
        _chunk(3, "hors sujet"),
    ]
    monkeypatch.setattr(pdf_rag, "_embed", _fake_embedder({"query": [1.0, 0.0, 0.0]}))
    vectors = [
        pdf_rag._normalize([1.0, 0.0, 0.0]),    # cos 1.0
        pdf_rag._normalize([0.97, 0.24, 0.0]),  # cos 0.97 (+0.05 de prior table → passe devant)
        pdf_rag._normalize([0.0, 1.0, 0.0]),    # cos 0.0 : sous le plancher, écarté
    ]
    ordered = pdf_rag._semantic_order(_index(chunks, vectors), "question", current_page=9)
    assert [c["page"] for c in ordered] == [2, 1]
    # La page visible est exclue.
    assert [c["page"] for c in pdf_rag._semantic_order(_index(chunks, vectors), "question", current_page=2)] == [1]
    # Sans vecteurs (couche indisponible) : rien, sans erreur.
    assert pdf_rag._semantic_order(_index(chunks, None), "question", current_page=9) == []


def test_hybrid_reaches_passages_without_shared_root(monkeypatch):
    # « carte graphique » n'a aucun radical commun avec « GPU » : seul le
    # sémantique y mène ; le lexical, lui, garde la main sur le sigle exact.
    chunks = [
        _chunk(1, "Reptile and FOMAML were trained on NVIDIA L40S GPUs."),
        _chunk(2, "FOMAML stopped on a non-finite loss in 7 of 12 runs."),
        _chunk(3, "Prototypical networks learn an embedding space."),
    ]
    monkeypatch.setattr(pdf_rag, "_embed", _fake_embedder({"carte graphique": [1.0, 0.0, 0.0]}))
    vectors = [pdf_rag._normalize(v) for v in ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])]
    index = _index(chunks, vectors)
    monkeypatch.setattr(pdf_rag, "_ensure_vectors", lambda *a, **k: None)

    ranked, depth = pdf_rag._ranked_candidates(1, index, "quelle carte graphique a été utilisée ?", 9, None)
    assert ranked[0]["page"] == 1
    assert depth == ASSISTANT_RAG_SEARCH_TOP_K  # la page 9 ne couvre rien
    ranked, _depth = pdf_rag._ranked_candidates(1, index, "combien de runs FOMAML ont divergé ?", 9, None)
    assert ranked[0]["page"] == 2


def test_ensure_vectors_persists_and_reloads(monkeypatch, fresh_db):
    from db import embeddings as embeddings_db

    chunks = [_chunk(1, "alpha"), _chunk(2, "beta")]
    calls = []

    def _embed(texts):
        calls.append(list(texts))
        return _fake_embedder({"alpha": [1.0, 0.0, 0.0], "beta": [0.0, 1.0, 0.0]})(texts)

    monkeypatch.setattr(pdf_rag, "_embed", _embed)
    from db.documents import upsert_document

    doc_id = upsert_document("/tmp/rag-a.pdf", "a.pdf", 2, "pdfium_scroll", False)
    other_id = upsert_document("/tmp/rag-b.pdf", "b.pdf", 5, "pdfium_scroll", False)
    index = _index(chunks)
    pdf_rag._ensure_vectors(doc_id, index)
    assert len(index["vectors"]) == 2 and calls and calls[0][0].startswith(pdf_rag._EMBED_DOC_PREFIX)

    # Même fichier, même découpage, même modèle : rechargés depuis la base, pas recalculés.
    again = _index(chunks)
    pdf_rag._ensure_vectors(doc_id, again)
    assert len(calls) == 1
    assert [list(v) for v in again["vectors"]] == [list(v) for v in index["vectors"]]

    # Découpage différent : la ligne ne vaut plus rien, on recalcule.
    other = _index([_chunk(1, "alpha"), _chunk(2, "gamma")])
    pdf_rag._ensure_vectors(doc_id, other)
    assert len(calls) == 2
    # Trop de chunks pour une question (sync_max) : on laisse la tâche de fond.
    big = _index([_chunk(i, f"chunk {i}") for i in range(5)])
    pdf_rag._ensure_vectors(other_id, big, sync_max=3)
    assert big["vectors"] is None and len(calls) == 2
    # Le document supprimé emporte ses vecteurs (cascade).
    from db.documents import delete_document

    delete_document(doc_id)
    assert embeddings_db.load_vectors(doc_id, 1.0, pdf_rag.OLLAMA_EMBED_MODEL, pdf_rag._chunk_hash(other["chunks"])) is None


def test_semantic_failure_is_remembered_then_retried(monkeypatch):
    import services.pdf_rag as module

    monkeypatch.undo()  # reprend le vrai `_embed` (le conftest le neutralise)
    monkeypatch.setattr(module, "_EMBED_STATE", {"retry_at": 0.0, "failure": ""})
    monkeypatch.setattr(module, "ASSISTANT_RAG_EMBED_RETRY_S", 100.0)
    attempts = []

    def _embed_texts(texts, model="m"):
        attempts.append(1)
        raise RuntimeError("model not found")

    monkeypatch.setattr(module, "embed_texts", _embed_texts)
    assert module._embed(["x"]) is None
    assert not module.semantic_available()
    assert module._embed(["x"]) is None  # pas de nouvel appel pendant le délai
    assert len(attempts) == 1
    module._EMBED_STATE["retry_at"] = 0.0
    assert module._embed(["x"]) is None
    assert len(attempts) == 2


def test_warm_index_batches_pages_and_invalidates_on_mtime(tmp_path, monkeypatch, make_pdf):
    pdf = make_pdf(tmp_path / "doc.pdf", [f"Page {i} parle de photosynthese." for i in range(1, 6)])
    monkeypatch.setattr(pdf_rag, "get_document", lambda doc_id: {"path": pdf})
    monkeypatch.setattr(pdf_rag, "_INDEX_BATCH_PAGES", 2)
    pdf_rag.clear_index(779)

    pdf_rag.warm_index(779)
    index = pdf_rag._INDEX_CACHE[779]
    assert sorted({c["page"] for c in index["chunks"]}) == [1, 2, 3, 4, 5]
    first = index["mtime"]

    # Même fichier, même mtime : l'index est réutilisé tel quel.
    assert pdf_rag._build_index(779) is index

    # Fichier remplacé (mtime différent) : réindexation.
    make_pdf(tmp_path / "doc.pdf", ["Nouveau contenu sur les mitochondries."])
    os.utime(pdf, (first + 10, first + 10))
    pdf_rag.warm_index(779)
    rebuilt = pdf_rag._INDEX_CACHE[779]
    assert rebuilt is not index
    assert {c["page"] for c in rebuilt["chunks"]} == {1}
    assert "mitochondries" in rebuilt["chunks"][0]["folded"]
    pdf_rag.clear_index(779)


# ── Prompt ───────────────────────────────────────────────────────────────────

def test_answer_prompt_keeps_tables_whole_and_flags_search():
    from llm.prompts import build_assistant_answer_prompt

    table = "TABLE I META-TRAINING CONFIGURATIONS. " + " ".join(f"Row {i} 0.{i}" for i in range(120))
    assert len(table) > 700  # au-delà du plafond d'un passage de prose
    passages = [{"page": 5, "table": True, "text": table}]

    prompt = build_assistant_answer_prompt(
        page_text="page visible", user_question="config de reptile ?",
        retrieved_passages=passages, whole_document_search=False,
    )
    assert "(p.5) [table]" in prompt
    assert "Row 119 0.119" in prompt  # non retronqué
    assert "TOUT le document" not in prompt and "WHOLE document" not in prompt

    prompt = build_assistant_answer_prompt(
        page_text="page visible", user_question="cherche dans tout l'article",
        retrieved_passages=passages, whole_document_search=True,
    )
    assert "TOUT le document" in prompt or "WHOLE document" in prompt


def test_answer_prompt_asks_to_read_the_figure_only_for_figure_questions():
    from llm.prompts import build_assistant_answer_prompt, is_figure_question

    assert is_figure_question("explique moi le schéma")
    assert is_figure_question("what does Fig. 3 show?")
    assert is_figure_question("à quoi sert la courbe rouge ?")
    # Bornes de mot : un graphe (structure) ou l'imagerie médicale ne sont pas des figures.
    assert not is_figure_question("c'est quoi un graphe biparti ?")
    assert not is_figure_question("l'imagerie IRM est-elle mentionnée ?")
    assert not is_figure_question("où est mentionné le gradnorm dans l'article ?")

    prompt = build_assistant_answer_prompt(page_text="Figure 1. légende", user_question="explique moi le schéma")
    assert "RÉELLEMENT VISIBLE" in prompt or "ACTUALLY VISIBLE" in prompt
    prompt = build_assistant_answer_prompt(page_text="Figure 1. légende", user_question="où est mentionné le gradnorm ?")
    assert "RÉELLEMENT VISIBLE" not in prompt and "ACTUALLY VISIBLE" not in prompt
