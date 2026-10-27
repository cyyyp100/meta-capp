# Relecture hebdomadaire des flashcards (services/flashcard_check).
#
# Clikoda relit les cartes une fois par semaine et PROPOSE une correction ;
# rien n'est réécrit sans l'élève. Le modèle est remplacé par un relecteur
# écrit à la main : on teste la politique (quand, quelles cartes, ce qu'on
# garde), pas le modèle.
from datetime import datetime, timedelta

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
def run(no_startup_flashcard_check, monkeypatch):
    """La vraie passe (le démarrage, lui, reste coupé), mode économe levé."""
    from services import flashcard_check

    monkeypatch.setattr(flashcard_check, "background_suspended", lambda task: False)
    return no_startup_flashcard_check


def _reviewer(fixes: dict[str, dict]):
    """Relecteur factice : corrige les cartes dont le recto est dans `fixes`."""
    seen: list[str] = []

    def checker(context, ok, err):
        seen.append(context["front"])
        fix = fixes.get(context["front"])
        ok({"verdict": "fix", **fix} if fix else {"verdict": "ok", "front": context["front"], "back": context["back"], "reason": ""})

    checker.seen = seen
    return checker


def test_a_wrong_card_gets_a_suggestion_and_stays_as_written(fresh_db, run):
    from services import flashcard_check
    from services.flashcards import create_flashcard, list_flashcards

    create_flashcard(front="Que vaut 2 + 2 ?", back="5")
    create_flashcard(front="Capitale de l'Italie ?", back="Rome")
    checker = _reviewer({"Que vaut 2 + 2 ?": {"front": "Que vaut 2 + 2 ?", "back": "4", "reason": "Le verso était faux."}})

    assert run(checker=checker) == 2
    [suggestion] = flashcard_check.suggestions()
    assert suggestion["back"] == "5" and suggestion["suggested_back"] == "4"
    assert suggestion["reason"] == "Le verso était faux."
    # Rien n'est réécrit sans l'élève.
    assert {c["back"] for c in list_flashcards()} == {"5", "Rome"}


def test_accepting_rewrites_the_card_and_it_is_not_reread(fresh_db, run, monkeypatch):
    from services import flashcard_check
    from services.flashcards import create_flashcard, list_flashcards

    card = create_flashcard(front="Que vaut 2 + 2 ?", back="5")
    run(checker=_reviewer({"Que vaut 2 + 2 ?": {"front": "Que vaut 2 + 2 ?", "back": "4", "reason": "Faux."}}))

    flashcard_check.accept(card)
    assert [c["back"] for c in list_flashcards()] == ["4"]
    assert flashcard_check.suggestions() == []
    with pytest.raises(LookupError):
        flashcard_check.accept(card)

    # La semaine suivante, la carte corrigée n'est pas relue.
    monkeypatch.setattr(flashcard_check, "is_due", lambda now=None: True)
    again = _reviewer({})
    run(checker=again)
    assert again.seen == []


def test_dismissing_keeps_the_card_until_the_student_edits_it(fresh_db, run, monkeypatch):
    from db.flashcards import update_flashcard
    from services import flashcard_check
    from services.flashcards import create_flashcard

    card = create_flashcard(front="Que vaut 2 + 2 ?", back="5")
    run(checker=_reviewer({"Que vaut 2 + 2 ?": {"front": "Que vaut 2 + 2 ?", "back": "4", "reason": "Faux."}}))
    flashcard_check.dismiss(card)
    assert flashcard_check.suggestions() == []

    monkeypatch.setattr(flashcard_check, "is_due", lambda now=None: True)
    untouched = _reviewer({})
    run(checker=untouched)
    assert untouched.seen == []

    update_flashcard(card, back="quatre")
    edited = _reviewer({})
    run(checker=edited)
    assert edited.seen == ["Que vaut 2 + 2 ?"]


def test_once_a_week_and_not_when_nothing_could_be_read(fresh_db, run):
    from db.app_settings import get_setting
    from services import flashcard_check
    from services.flashcards import create_flashcard

    create_flashcard(front="Que vaut 2 + 2 ?", back="4")

    def ollama_off(context, ok, err):
        err("Ollama injoignable")

    # Aucune carte relue : la passe n'est pas comptée, elle repartira.
    assert run(checker=ollama_off) == 0
    assert get_setting("flashcard_check_last") is None

    assert run(checker=_reviewer({})) == 1
    assert not flashcard_check.is_due()
    assert flashcard_check.is_due(datetime.now() + timedelta(days=7))
    assert run(checker=_reviewer({})) == 0


def test_economy_mode_suspends_the_pass(fresh_db, no_startup_flashcard_check, monkeypatch):
    from services import flashcard_check
    from services.flashcards import create_flashcard

    create_flashcard(front="Que vaut 2 + 2 ?", back="5")
    monkeypatch.setattr(flashcard_check, "background_suspended", lambda task: task == "flashcard_check")
    checker = _reviewer({})
    assert no_startup_flashcard_check(checker=checker) == 0
    assert checker.seen == []
    assert flashcard_check.is_due()


def test_language_cards_are_left_to_their_own_rules(fresh_db, run):
    from db.flashcards import save_flashcard

    save_flashcard(1, None, "der Hund", "le chien", source="lang_vocab", language="allemand")
    checker = _reviewer({})
    run(checker=checker)
    assert checker.seen == []


def test_a_fix_identical_to_the_card_is_not_a_suggestion(fresh_db, run):
    from services import flashcard_check
    from services.flashcards import create_flashcard

    create_flashcard(front="Capitale de l'Italie ?", back="Rome")
    run(checker=_reviewer({"Capitale de l'Italie ?": {"front": "Capitale de l'Italie ?", "back": " Rome ", "reason": "?"}}))
    assert flashcard_check.suggestions() == []


def test_a_card_that_needs_the_document_can_be_removed(fresh_db, run):
    """Une question de lecture trop collée au PDF : la carte renvoie à « la
    figure », que rien sur la carte ne rétablit. Clikoda propose de la
    supprimer ; elle ne part qu'avec l'accord de l'élève."""
    from services import flashcard_check
    from services.flashcards import create_flashcard, list_flashcards

    card = create_flashcard(front="Que montre la figure 3 ?", back="La courbe du haut.")
    create_flashcard(front="Capitale de l'Italie ?", back="Rome")
    run(checker=_reviewer({"Que montre la figure 3 ?": {
        "verdict": "remove", "front": "Que montre la figure 3 ?", "back": "La courbe du haut.",
        "reason": "La carte renvoie à une figure qui n'est pas sur la carte.",
    }}))

    [suggestion] = flashcard_check.suggestions()
    assert suggestion["kind"] == "remove" and suggestion["card_id"] == card
    assert len(list_flashcards()) == 2  # rien n'est supprimé sans l'élève

    assert flashcard_check.accept(card) == {"id": card, "removed": True}
    assert [c["front"] for c in list_flashcards()] == ["Capitale de l'Italie ?"]
    assert flashcard_check.suggestions() == []


def test_the_reviewer_output_is_validated():
    from llm.schema_json import parse_flashcard_check

    assert parse_flashcard_check('{"verdict": "remove", "reason": "Renvoie au document."}')["verdict"] == "remove"
    assert parse_flashcard_check('{"verdict": "remove", "reason": ""}') is None  # sans raison, pas de suppression
    assert parse_flashcard_check('{"verdict": "fix", "front": "", "back": "4"}') is None
    assert parse_flashcard_check('{"verdict": "peut-être"}') is None


def test_a_valid_formula_is_not_rewritten_for_style(fresh_db, run):
    """Mesuré sur gemma4 : une formule juste revenait en \\frac « pour la
    lisibilité ». Seule une formule cassée mérite une proposition."""
    from services import flashcard_check
    from services.flashcards import create_flashcard

    create_flashcard(front="Théorème de Bayes ?", back="$P(A|B) = P(B|A) \\cdot P(A) / P(B)$")
    create_flashcard(front="Dérivée de $x^2$ ?", back="$2x^{1$")
    run(checker=_reviewer({
        "Théorème de Bayes ?": {"front": "Théorème de Bayes ?", "back": "$P(A|B) = \\frac{P(B|A) P(A)}{P(B)}$", "reason": "Plus lisible."},
        "Dérivée de $x^2$ ?": {"front": "Dérivée de $x^2$ ?", "back": "$2x$", "reason": "Formule cassée."},
    }))
    assert [s["front"] for s in flashcard_check.suggestions()] == ["Dérivée de $x^2$ ?"]
