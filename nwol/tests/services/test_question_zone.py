# Zone précise d'une question (services.assistant.resolve_question_zone).
#
# Le LLM recopie le passage visé ; le lecteur cadre une CITATION retrouvée sur la
# page. Entre les deux, la citation doit être une vraie sous-chaîne de la page —
# sinon PDFium ne la trouve pas et le lecteur cadre le haut de page, comme avant.
import pytest

from services import assistant, library

PAGE = (
    "Le théorème de Rolle affirme qu'entre deux zéros d'une fonction dérivable, "
    "la dérivée s'annule au moins une fois.\n"
    "On en déduit le théorème des accroissements finis : il existe un point c "
    "tel que f'(c) égale le taux d'accroissement moyen.\n"
    "Ce résultat est central pour l'étude des variations."
)


@pytest.fixture(autouse=True)
def _page(monkeypatch):
    monkeypatch.setattr(library, "page_text", lambda doc_id, page: PAGE)


def test_verbatim_excerpt_is_kept_as_the_page_spells_it():
    zone = assistant.resolve_question_zone(1, 1, {
        "source_excerpt": "le THÉORÈME de Rolle affirme qu'entre deux zéros d'une fonction dérivable, la dérivée s'annule",
    })
    assert zone == {"quote": "Le théorème de Rolle affirme qu'entre deux zéros d'une fonction dérivable, la dérivée s'annule"}


def test_excerpt_spanning_a_line_break_is_flattened():
    zone = assistant.resolve_question_zone(1, 1, {
        "source_excerpt": "la dérivée s'annule au moins une fois. On en déduit le théorème des accroissements finis",
    })
    assert zone is not None
    assert "\n" not in zone["quote"]
    assert zone["quote"].startswith("la dérivée s'annule")


def test_paraphrased_excerpt_snaps_to_the_closest_sentences():
    # Le modèle a « recopié » de mémoire : mots déplacés, un adjectif en moins.
    zone = assistant.resolve_question_zone(1, 1, {
        "source_excerpt": "théorème des accroissements finis : il existe un point c tel que f'(c) égale le taux moyen d'accroissement",
    })
    assert zone is not None
    assert zone["quote"].startswith("On en déduit le théorème des accroissements finis")
    assert zone["quote"] in " ".join(PAGE.split())


def test_unrelated_excerpt_gives_no_zone():
    assert assistant.resolve_question_zone(1, 1, {
        "source_excerpt": "La photosynthèse transforme la lumière en énergie chimique dans les chloroplastes",
    }) is None


def test_too_short_excerpt_falls_back_on_the_mask():
    zone = assistant.resolve_question_zone(1, 1, {
        "source_excerpt": "Rolle",
        "paragraph_mask": {"enabled": True, "start_char": 0, "end_char": 60, "placeholder": "…"},
    })
    assert zone is not None
    assert zone["quote"].startswith("Le théorème de Rolle")


def test_nothing_usable_gives_none():
    assert assistant.resolve_question_zone(1, 1, {}) is None
    assert assistant.resolve_question_zone(1, 1, None) is None


def test_overlong_excerpt_is_cut_on_a_word():
    long_page = " ".join(f"mot{i}" for i in range(400))
    zone = assistant.resolve_question_zone.__wrapped__ if hasattr(assistant.resolve_question_zone, "__wrapped__") else None
    assert zone is None  # pas de décorateur : appel direct ci-dessous
    quote = assistant._cut_at_word(long_page, assistant._MAX_ZONE_CHARS)
    assert len(quote) <= assistant._MAX_ZONE_CHARS
    assert not quote.endswith(" ") and long_page.startswith(quote)


def test_recall_mask_hides_the_copied_passage_not_the_indices():
    """Rappel libre : gemma4 donne des indices à côté du passage (mesuré sur
    trois questions) mais le recopie exactement. Le cache suit la recopie,
    sinon la réponse reste lisible, cadrée par la zone de la question."""
    mask = assistant.resolve_paragraph_mask(
        1, 1,
        {"enabled": True, "start_char": 150, "end_char": 230, "placeholder": "…"},
        "il existe un point c tel que f'(c) égale le taux d'accroissement moyen",
    )
    assert mask["quote"] == "il existe un point c tel que f'(c) égale le taux d'accroissement moyen"


def test_recall_mask_indices_are_widened_to_whole_words():
    """Sans recopie exploitable, les indices restent le repli, au mot entier."""
    mask = assistant.resolve_paragraph_mask(
        1, 1, {"enabled": True, "start_char": 1, "end_char": 60, "placeholder": "…"},
    )
    assert mask["quote"].startswith("Le théorème de Rolle")
    assert mask["quote"].endswith("d'une fonction")


def test_recall_zone_and_mask_cover_the_same_passage():
    """La zone cadrée et le cache désignent le même passage : plus de « fenêtre »
    transparente posée sur la réponse à côté d'un cache qui masque autre chose."""
    result = {
        "source_excerpt": "On en déduit le théorème des accroissements finis : il existe un point c",
        "paragraph_mask": {"enabled": True, "start_char": 0, "end_char": 50, "placeholder": "…"},
    }
    zone = assistant.resolve_question_zone(1, 1, result)
    mask = assistant.resolve_paragraph_mask(1, 1, result["paragraph_mask"], result["source_excerpt"])
    assert zone["quote"] == mask["quote"]
