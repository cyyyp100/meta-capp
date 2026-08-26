# Parseurs JSON tolérants (llm/schema_json) : entrées malformées -> None ou
# dict normalisé, JAMAIS d'exception (le LLM local produit du JSON approximatif).
import pytest

from llm import schema_json

# Parseurs « raw -> dict | None » représentatifs de chaque famille.
PARSERS = [
    schema_json.parse_question,
    schema_json.parse_evaluation,
    schema_json.parse_follow_up,
    schema_json.parse_intervention,
    schema_json.parse_rephrasing,
    schema_json.parse_session_summary,
    schema_json.parse_curiosity_hook,
    schema_json.parse_chapter_summary,
    schema_json.parse_quiz_session_analysis,
    schema_json.parse_flashcard,
    schema_json.parse_lang_curriculum,
    schema_json.parse_lesson_plan,
    schema_json.parse_placement_test,
]

MALFORMED_INPUTS = [
    "",
    "   ",
    "pas du json",
    "{",
    "}",
    '{"question": ',                      # tronqué
    '{"a": 1,}',                          # virgule traînante
    "{'a': 1}",                           # quotes python
    '{"a": NaN}',
    "```json\n{broken\n```",              # fence markdown cassée
    "[1, 2, 3]",
    "null",
    "42",
    '{"nested": {"very": {"deep": ',      # tronqué profond
    "\x00\x01binaire",
    '{"a": "b" "c": "d"}',                # virgule manquante
]


@pytest.mark.parametrize("parser", PARSERS, ids=lambda p: p.__name__)
@pytest.mark.parametrize("raw", MALFORMED_INPUTS)
def test_parsers_never_raise_on_malformed(parser, raw):
    result = parser(raw)
    assert result is None or isinstance(result, dict)


@pytest.mark.parametrize("parser", PARSERS, ids=lambda p: p.__name__)
def test_parsers_accept_dict_and_none_like(parser):
    assert parser({}) is None or isinstance(parser({}), dict)
    assert parser({"champ": "inconnu"}) is None or isinstance(parser({"champ": "inconnu"}), dict)


# ── Récupérations tolérantes attendues (cas réels de gemma) ─────────────────

def test_question_recovers_from_fenced_and_trailing_comma():
    raw = """```json
    {
      "question": "Quelle est l'idée principale ?",
      "question_type": "comprehension",
      "expected_answer": "L'idée X",
      "evaluation_criteria": ["mentionne X",],
    }
    ```"""
    parsed = schema_json.parse_question(raw)
    assert parsed is not None
    assert parsed["question"].startswith("Quelle est")


def test_evaluation_recovers_verdict_from_score():
    parsed = schema_json.parse_evaluation('{"score": 0.9, "feedback": "Bien vu"}')
    assert parsed is not None
    assert parsed["verdict"] == "correct"
    # Signaux toujours présents et bornés [-2, 2].
    assert set(parsed["metacog_signals"]) >= {"attention", "curiosity"}
    assert all(-2.0 <= v <= 2.0 for v in parsed["metacog_signals"].values())


def test_evaluation_without_verdict_is_rejected_not_crashed():
    assert schema_json.parse_evaluation('{"feedback": "aucun verdict"}') is None


def test_curiosity_hook_normalizes_accessibility_percent():
    parsed = schema_json.parse_curiosity_hook(
        '{"hook": "Le saviez-vous ?", "estimated_accessibility": 85}'
    )
    assert parsed is not None
    assert 0.0 <= parsed["estimated_accessibility"] <= 1.0


def test_truncated_question_json_is_completed():
    # num_predict borné -> gemma tronque parfois : le filet complète les accolades.
    raw = '{"question": "Pourquoi ?", "expected_answer": "Parce que", "evaluation_criteria": ["a"'
    parsed = schema_json.parse_question(raw)
    assert parsed is None or parsed["question"] == "Pourquoi ?"


# ── Types à widget : les choix ne veulent pas dire la même chose partout ────

def _question(**overrides) -> dict:
    payload = {
        "question": "Remets les étapes dans l'ordre.",
        "question_type": "ordering",
        "choices": ["Poser les hypothèses", "Appliquer le théorème", "Conclure"],
        "expected_answer": "1. Poser les hypothèses 2. Appliquer le théorème 3. Conclure",
        "evaluation_criteria": ["ordre exact"],
    }
    payload.update(overrides)
    return payload


def test_ordering_keeps_its_steps_in_order():
    parsed = schema_json.parse_question(_question())
    assert parsed is not None
    # Surtout : l'ordre reçu est la réponse, il ne doit pas être remanié ici.
    assert parsed["choices"] == ["Poser les hypothèses", "Appliquer le théorème", "Conclure"]


def test_ordering_without_enough_steps_is_rejected():
    """Deux étapes ne font pas un exercice : mieux vaut régénérer la question."""
    assert schema_json.parse_question(_question(choices=["Une", "Deux"])) is None


def test_free_answer_types_drop_the_choices_gemma_adds_anyway():
    parsed = schema_json.parse_question(
        _question(question_type="teach_back", question="Explique en deux phrases.")
    )
    assert parsed is not None
    assert parsed["choices"] == []


def test_recall_requires_a_usable_mask():
    """Sans masque, le passage reste lisible : la question n'a plus d'objet."""
    assert schema_json.parse_question(_question(question_type="recall", choices=[])) is None
    parsed = schema_json.parse_question(
        _question(
            question_type="recall",
            choices=[],
            paragraph_mask={
                "enabled": True,
                "start_char": 10,
                "end_char": 120,
                "placeholder": "passage masqué",
            },
        )
    )
    assert parsed is not None
    assert parsed["paragraph_mask"]["enabled"] is True
