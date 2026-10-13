"""« Entre dans non renseigné en cherchant le lien… » — le mot-bouchon qui fuyait.

Vu à l'écran par un utilisateur. La chaîne complète : un champ vide faisait
écrire « non renseigné » DANS le prompt (`prompts.py`), et le repli hors-ligne
réanalysait son propre prompt pour retrouver le titre du chapitre — il y
récupérait le bouchon et l'affichait à l'élève.

Deux verrous, donc : aucun bouchon n'entre dans un prompt (une ligne vide est
OMISE), et aucun repli ne rend une phrase qui en nomme un. Plus un troisième,
qui n'a rien à voir avec le symptôme mais tout avec l'élève : ces phrases-là
étaient en français en dur au milieu du client HTTP.
"""
from __future__ import annotations

import pytest

import i18n
from config.settings import OLLAMA_TASK_OPTIONS
from llm import ollama_client as oc
from llm.prompts import (
    build_chapter_summary_prompt,
    build_curiosity_hook_prompt,
    build_question_prompt,
)

PLACEHOLDERS = ("non renseigné", "not specified")


@pytest.fixture(params=["fr", "en"])
def lang(request):
    before = i18n.current_lang()
    i18n.set_lang(request.param)
    yield request.param
    i18n.set_lang(before)


def test_no_placeholder_ever_enters_a_prompt(lang):
    """Les trois constructeurs qui l'écrivaient. Un champ vide n'a pas de ligne
    — et le modèle n'apprend pas au passage qu'un champ peut porter ce texte,
    ce qu'un petit modèle recopie volontiers dans sa réponse."""
    prompts = [
        build_question_prompt("paragraphe", doc_title="", chapter_title=""),
        build_chapter_summary_prompt("", [], {}),
        build_curiosity_hook_prompt("", "", "", "", {}),
    ]
    for prompt in prompts:
        for placeholder in PLACEHOLDERS:
            assert placeholder not in prompt, (lang, placeholder)
    # Et la ligne entière disparaît, elle ne reste pas vide avec son étiquette.
    assert "Sous-chapitre" not in prompts[2] and "Sub-chapter" not in prompts[2]


def test_a_field_that_exists_is_still_in_the_prompt(lang):
    prompt = build_curiosity_hook_prompt("Analyse", "Dérivées", "Taux d'accroissement", "extrait", {})
    assert "Analyse" in prompt and "Dérivées" in prompt and "Taux d'accroissement" in prompt


def test_the_hook_fallback_reads_the_context_not_the_prompt():
    """Le repli ne devine plus en relisant le prompt : l'appelant lui passe ce
    qu'il sait (`fallback_context`)."""
    hook = oc._fallback_curiosity_hook({"chapter_title": "Dérivées"}, prompt="")
    assert "Dérivées" in hook["curiosity_hook"]
    assert hook["link_with_chapter"] == "Dérivées"
    # Le sous-chapitre, quand il existe, est la cible la plus précise.
    précis = oc._fallback_curiosity_hook(
        {"chapter_title": "Dérivées", "subchapter_title": "Taux d'accroissement"}, prompt="")
    assert "Taux d'accroissement" in précis["curiosity_hook"]


def test_the_hook_fallback_never_names_a_placeholder(lang):
    """Le garde-fou demandé : la phrase VUE PAR L'ÉLÈVE, sur un prompt construit
    depuis un contexte entièrement vide."""
    prompt = build_curiosity_hook_prompt("", "", "", "", {})
    hook = oc._fallback_curiosity_hook({}, prompt)
    for placeholder in PLACEHOLDERS:
        assert placeholder not in hook["curiosity_hook"], lang
    assert hook["curiosity_hook"].strip()  # et il dit quand même quelque chose


def test_the_fallbacks_speak_the_language_of_the_interface(lang):
    hook = oc._fallback_curiosity_hook({"chapter_title": "X"}, prompt="")["curiosity_hook"]
    summary = oc._fallback_chapter_summary({}, prompt="")["chapter_summary"]
    if lang == "en":
        assert hook.startswith("Step into") and summary["title"] == "Chapter"
    else:
        assert hook.startswith("Entre dans") and summary["title"] == "Chapitre"


def test_no_fallback_at_all_leaks_a_placeholder(lang):
    """Large et bon marché : les quinze replis qui n'ont pas été retouchés
    passent ici aussi. Un prompt vide, chaque tâche déclarée, et on cherche le
    bouchon dans TOUT ce qui est rendu."""
    for label in OLLAMA_TASK_OPTIONS:
        result = oc._fallback_json_result(label, "", lambda raw: None, "")
        if result is None:
            continue  # pas de repli pour cette tâche (quiz_analysis) : assumé
        rendered = repr(result)
        for placeholder in PLACEHOLDERS:
            assert placeholder not in rendered, (label, placeholder, lang)
