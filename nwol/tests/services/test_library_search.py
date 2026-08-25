"""Recherche dans la bibliothèque (services/library.search_documents).

L'enjeu de la fonctionnalité est de retrouver un PDF SANS en connaître le nom :
ces tests vérifient donc surtout que le résumé et les mots-clés générés par le
LLM sont bien des points d'entrée, et que les accents ne bloquent rien.
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


def _document(filename: str, summary: str = "", keywords=None, subject=None) -> int:
    from db.documents import update_document_digest, upsert_document

    doc_id = upsert_document(f"/tmp/{filename}", filename, 10, "pymupdf_scroll", False)
    update_document_digest(doc_id, subject, summary, keywords or [])
    return doc_id


def _titles(results) -> list[str]:
    return [r["title"] for r in results]


def test_finds_a_document_by_a_word_only_present_in_the_summary(fresh_db):
    from services.library import search_documents

    _document("cours-l1.pdf", summary="Introduction aux dérivées et aux limites de fonctions.")
    _document("autre.pdf", summary="Histoire de la Rome antique.")

    assert _titles(search_documents("dérivées")) == ["cours-l1.pdf"]


def test_finds_a_document_by_a_word_only_present_in_the_keywords(fresh_db):
    from services.library import search_documents

    _document("scan-042.pdf", keywords=["photosynthèse", "chlorophylle"])
    _document("autre.pdf", keywords=["rome", "empire"])

    assert _titles(search_documents("chlorophylle")) == ["scan-042.pdf"]


def test_search_ignores_accents_in_both_directions(fresh_db):
    from services.library import search_documents

    _document("algebre.pdf", summary="Notions d'algèbre linéaire et d'espaces vectoriels.")

    # Requête sans accent -> contenu accentué.
    assert _titles(search_documents("algebre")) == ["algebre.pdf"]
    # Requête accentuée -> contenu sans accent (le nom de fichier).
    assert _titles(search_documents("algèbre")) == ["algebre.pdf"]


def test_filename_outranks_a_mere_summary_mention(fresh_db):
    from services.library import search_documents

    _document("mentionne.pdf", summary="Un chapitre évoque la thermodynamique au passage.")
    _document("thermodynamique.pdf", summary="Sujet sans rapport.")

    assert _titles(search_documents("thermodynamique"))[0] == "thermodynamique.pdf"


def test_a_document_matching_more_terms_comes_first(fresh_db):
    from services.library import search_documents

    _document("partiel.pdf", keywords=["photosynthèse"])
    _document("complet.pdf", keywords=["photosynthèse", "chlorophylle"])

    assert _titles(search_documents("photosynthese chlorophylle"))[0] == "complet.pdf"


def test_subject_is_searchable(fresh_db):
    from services.library import search_documents

    _document("sans-nom-parlant.pdf", subject="physique")

    assert _titles(search_documents("physique")) == ["sans-nom-parlant.pdf"]


def test_short_but_legitimate_queries_still_work(fresh_db):
    from services.library import search_documents

    _document("notes.pdf", keywords=["ia", "reseaux"])

    # « ia » est trop court pour le découpage en mots significatifs : le repli
    # sur la requête brute doit quand même trouver le document.
    assert _titles(search_documents("ia")) == ["notes.pdf"]


def test_blank_or_single_character_queries_return_nothing(fresh_db):
    from services.library import search_documents

    _document("notes.pdf", keywords=["ia"])

    assert search_documents("") == []
    assert search_documents("   ") == []
    assert search_documents("a") == []


def test_no_match_returns_an_empty_list(fresh_db):
    from services.library import search_documents

    _document("cours.pdf", summary="Algèbre linéaire.")

    assert search_documents("gastronomie") == []


def test_summary_reaches_the_api_shape(fresh_db):
    """`_summary` est une liste blanche : un champ absent n'atteint jamais le
    frontend, même s'il est en base."""
    from services.library import list_all_documents

    _document("cours.pdf", summary="Un résumé.", keywords=["maths"], subject="mathématiques")

    doc = list_all_documents()[0]
    assert doc["summary"] == "Un résumé."
    assert doc["keywords"] == ["maths"]
    assert doc["subject"] == "mathématiques"
    assert doc["digest_status"] == "done"
    assert doc["folder_id"] is None
