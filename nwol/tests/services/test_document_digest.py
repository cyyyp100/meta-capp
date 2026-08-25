"""Parsing de la fiche LLM d'un document (llm/schema_json.parse_document_digest).

Le parser ne doit JAMAIS renvoyer None : un import ne peut pas échouer parce que
le modèle a bavardé. Chaque champ dégrade indépendamment.
"""
from llm.schema_json import parse_document_digest


def test_nominal_output_is_passed_through():
    result = parse_document_digest(
        '{"subject": "biologie", "summary": "La photosynthèse chez les plantes vertes.",'
        ' "keywords": ["photosynthèse", "chlorophylle"]}'
    )
    assert result["subject"] == "biologie"
    assert result["summary"] == "La photosynthèse chez les plantes vertes."
    assert result["keywords"] == ["photosynthèse", "chlorophylle"]


def test_garbage_still_yields_a_usable_card():
    for raw in ("", "je ne sais pas", "{", None, []):
        result = parse_document_digest(raw)
        assert result is not None
        assert result["subject"] == "culture"   # repli, jamais None
        assert result["summary"] == ""
        assert result["keywords"] == []


def test_unknown_subject_falls_back_to_culture():
    result = parse_document_digest('{"subject": "sous-marinologie", "summary": "x", "keywords": []}')
    assert result["subject"] == "culture"


def test_french_key_aliases_are_accepted():
    result = parse_document_digest(
        '{"matiere": "physique", "resume": "Les lois de Newton et la dynamique.",'
        ' "mots_cles": ["mécanique", "newton"]}'
    )
    assert result["subject"] == "physique"
    assert result["summary"] == "Les lois de Newton et la dynamique."
    assert result["keywords"] == ["mécanique", "newton"]


def test_markdown_fences_and_summary_prefix_are_stripped():
    result = parse_document_digest(
        '```json\n{"subject": "histoire", "summary": "**Résumé : La Rome antique et ses institutions.**",'
        ' "keywords": ["rome"]}\n```'
    )
    assert result["summary"] == "La Rome antique et ses institutions."


def test_filler_opening_is_removed():
    """gemma remet « Ce document explique… » malgré la consigne du prompt : ces
    caractères sont pris sur les 220 affichables et n'apprennent rien."""
    result = parse_document_digest(
        '{"subject": "biologie", "summary": "Ce document explique le processus de '
        'photosynthèse et le cycle de Calvin.", "keywords": []}'
    )
    assert result["summary"] == "Le processus de photosynthèse et le cycle de Calvin."


def test_filler_removal_never_leaves_a_stump():
    result = parse_document_digest(
        '{"subject": "culture", "summary": "Ce document explique tout.", "keywords": []}'
    )
    # Retirer l'ouverture laisserait « Tout. » : on garde la phrase entière.
    assert result["summary"] == "Ce document explique tout."


def test_long_summary_is_truncated_on_a_word_boundary():
    from config.settings import DOCUMENT_SUMMARY_MAX_CHARS

    long_text = "La photosynthèse " * 40
    result = parse_document_digest(
        '{"subject": "biologie", "summary": "%s", "keywords": []}' % long_text.strip()
    )
    assert len(result["summary"]) <= DOCUMENT_SUMMARY_MAX_CHARS + 1  # + le caractère « … »
    assert result["summary"].endswith("…")
    assert "  " not in result["summary"]


def test_vague_keywords_are_dropped_and_the_list_is_capped():
    from config.settings import DOCUMENT_KEYWORDS_MAX

    result = parse_document_digest(
        '{"subject": "culture", "summary": "x", "keywords": ["Introduction", "cours",'
        ' "Chapitre", "algèbre", "algèbre", "topologie", "analyse", "géométrie",'
        ' "arithmétique", "probabilités", "statistiques"]}'
    )
    assert "introduction" not in result["keywords"]
    assert "cours" not in result["keywords"]
    assert result["keywords"].count("algèbre") == 1     # dédoublonné
    assert len(result["keywords"]) <= DOCUMENT_KEYWORDS_MAX


def test_keywords_keep_apostrophes_and_never_cut_mid_word():
    """Les mots-clés sont AFFICHÉS : « droits de lhomm » se lirait comme un bug."""
    result = parse_document_digest(
        '{"subject": "histoire", "summary": "x",'
        ' "keywords": ["Déclaration des droits de l\'homme et du citoyen"]}'
    )
    assert result["keywords"] == ["déclaration des droits de"]

    short = parse_document_digest(
        '{"subject": "histoire", "summary": "x", "keywords": ["l’Ancien Régime"]}'
    )
    # L'apostrophe typographique est ramenée à la droite, pas supprimée.
    assert short["keywords"] == ["l'ancien régime"]


def test_keywords_keep_their_accents_for_display():
    """Les accents sont conservés à l'affichage ; l'insensibilité aux accents est
    appliquée au moment de la recherche, en pliant les deux côtés."""
    result = parse_document_digest(
        '{"subject": "culture", "summary": "x", "keywords": ["Photosynthèse"]}'
    )
    assert result["keywords"] == ["photosynthèse"]
