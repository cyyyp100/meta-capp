# Données statiques du module langues (plan S2, D23, V11).
#
# Chaque fichier de nwol/data/lang/ passe les validateurs de
# services/lang_static.py — les mêmes que `python tools/validate_lang_data.py`.
# Un programme invalide ne serait jamais injecté en base : ce test l'attrape
# avant qu'une langue perde silencieusement son programme au démarrage.
import copy

import pytest

from config.settings import LANG_PILOT_LANGUAGES


def _program(language):
    from services.lang_static import load_json

    return load_json("program", f"{language}.json")


@pytest.mark.parametrize("language", LANG_PILOT_LANGUAGES)
def test_every_pilot_language_has_a_valid_program(language):
    from services.lang_static import validate_program

    data = _program(language)
    assert data is not None, f"program/{language}.json manquant"
    assert validate_program(data, language) == []
    assert len(data["points"]) >= 200


@pytest.mark.parametrize("language", LANG_PILOT_LANGUAGES)
def test_placement_onboarding_and_helpers_are_valid(language):
    from services.lang_static import (
        load_json,
        validate_faux_amis,
        validate_onboarding,
        validate_placement,
    )

    ids = {p["id"] for p in _program(language)["points"]}
    placement = load_json("placement", f"{language}.json")
    assert validate_placement(placement, language, ids) == []
    assert 15 <= len(placement["items"]) <= 20
    assert validate_onboarding(load_json("onboarding", f"{language}.json"), language) == []
    if language in ("espagnol", "anglais", "allemand"):
        assert validate_faux_amis(load_json("helpers", f"faux_amis_{language}.json"), language) == []


def test_validate_data_tool_reports_no_error():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
    from validate_lang_data import check_all

    report = check_all()
    assert {k: v for k, v in report.items() if v} == {}


def test_program_validator_catches_each_invariant():
    from services.lang_static import validate_program

    good = _program("espagnol")
    assert validate_program(good, "espagnol") == []
    cases = {
        "order": lambda d: d["points"][3].update(order=99),
        "double": lambda d: d["points"][4].update(id=d["points"][3]["id"]),
        "prérequis": lambda d: d["points"][2].update(prerequisites=[d["points"][10]["id"]]),
        "bilan_group": lambda d: d["points"][7].update(bilan_group=1),
        "recule": lambda d: d["points"][60].update(cefr="A1"),
        "Peut": lambda d: d["points"][1].update(learner_goal="Sait saluer."),
        "400": lambda d: d["points"][1].update(explanation_seed="x" * 401),
        "formats": lambda d: d["points"][1].update(formats_allowed=["poème"]),
    }
    for needle, mutate in cases.items():
        data = copy.deepcopy(good)
        mutate(data)
        errors = validate_program(data, "espagnol")
        assert any(needle in e for e in errors), (needle, errors[:3])


# ── Langue d'explication anglaise (§ 14, n° 14) ───────────────────────────────

@pytest.mark.parametrize("language", LANG_PILOT_LANGUAGES)
def test_english_explanations_are_offered_where_the_data_allows(language):
    """Chaque langue du pilote s'explique en anglais, sauf l'anglais lui-même
    (on n'explique pas une langue dans elle-même) — et, pour les autres, tout
    ce qu'un profil anglais voit existe en anglais : phrases de survie, aperçu
    de l'écriture, bible de secours, paramètres de prompt, items du test rédigés
    en français."""
    from services.lang_static import explain_languages, load_json, localized, onboarding_prompt_params

    allowed = explain_languages(language)
    if language == "anglais":
        assert allowed == ("fr",)
        return
    assert allowed == ("fr", "en")
    params = onboarding_prompt_params(language, "en")
    assert "English translation" in params["line_schema"] and "français" not in params["line_schema"]
    data = load_json("onboarding", f"{language}.json")
    assert all(localized(ph, "translation", "en") != ph["translation"] for ph in data["phrases"])
    for item in load_json("placement", f"{language}.json")["items"]:
        if item["kind"] == "lecture":
            assert item.get("prompt_en") and item.get("choices_en"), item["id"]
    untranslated = [p["id"] for p in _program(language)["points"] if not p.get("title_en") or not p.get("learner_goal_en")]
    assert untranslated == []


def test_english_overlays_are_validated():
    from services.lang_static import load_json, validate_onboarding, validate_placement

    onboarding = copy.deepcopy(load_json("onboarding", "espagnol.json"))
    del onboarding["phrases"][3]["translation_en"]
    del onboarding["default_bible_en"]
    errors = validate_onboarding(onboarding, "espagnol")
    assert any("translation_en" in e for e in errors) and any("default_bible_en" in e for e in errors)
    placement = copy.deepcopy(load_json("placement", "espagnol.json"))
    ids = {p["id"] for p in _program("espagnol")["points"]}
    item = next(it for it in placement["items"] if "choices_en" in it)
    item["choices_en"] = item["choices_en"][:-1]  # l'ordre des choix porte la clé : un par un
    assert any("choices_en" in e for e in validate_placement(placement, "espagnol", ids))
