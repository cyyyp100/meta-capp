"""`config/question_types.py` est la SEULE déclaration de la grille des types.

La grille était recopiée à huit endroits (guides FR/EN, `QUESTION_TYPES`, alias,
jauges cibles, dimensions d'évaluation, énumérations des prompts, prompt de
réparation) et une divergence ne levait aucune erreur : `parse_question`
retombait silencieusement sur "qcm"/"open". Ces tests échouent dès qu'un
consommateur — backend ou frontend — se remet à tenir sa propre liste.
"""
from __future__ import annotations

import re
from pathlib import Path

from config import question_types as qt

FRONTEND_REGISTRY = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "features" / "questions" / "registry.ts"
)


def test_every_consumer_reads_the_registry():
    from llm import prompts, schema_json
    from metacog.gauges import QUESTION_TYPE_TARGET_GAUGES

    assert schema_json.QUESTION_TYPES == qt.KEYS
    assert tuple(QUESTION_TYPE_TARGET_GAUGES) == qt.KEYS
    assert tuple(row[0] for row in prompts.QUESTION_TYPE_GUIDE) == qt.KEYS
    assert tuple(row[0] for row in prompts.QUESTION_TYPE_GUIDE_EN) == qt.KEYS
    # Les types réflexifs sont pilotés par le verdict : pas d'indice de dimension.
    assert set(prompts._EVAL_TYPE_DIMENSIONS) <= set(qt.KEYS)


def test_specs_are_complete_and_coherent():
    from db.metacog import CRITERIA

    for spec in qt.QUESTION_TYPE_SPECS:
        for field in (spec.label, spec.purpose, spec.example, spec.prefer_rule):
            assert len(field) == 2 and all(text.strip() for text in field), spec.key
        assert spec.target_gauges, spec.key
        assert set(spec.target_gauges) <= set(CRITERIA), spec.key
        assert spec.widget in (qt.WIDGET_CHOICES, qt.WIDGET_TEXT, qt.WIDGET_ORDERING), spec.key
        assert spec.base_weight > 0, spec.key
    assert len(set(qt.KEYS)) == len(qt.KEYS)
    # Un alias ne doit jamais recouvrir une clé (il l'ombragerait au parsing).
    assert not set(qt.alias_map()) & set(qt.KEYS)


def test_prompt_lists_every_type_in_both_languages():
    import i18n
    from llm.prompts import build_question_prompt

    for lang in ("fr", "en"):
        i18n.set_lang(lang)
        try:
            prompt = build_question_prompt("Un paragraphe de test.", doc_title="Doc")
            for key in qt.KEYS:
                assert f'"{key}"' in prompt, (lang, key)
            assert qt.json_enum(lang) in prompt
        finally:
            i18n.set_lang("fr")


def test_frontend_registry_mirrors_the_backend():
    """Le miroir UI doit couvrir exactement les mêmes clés, avec un widget cohérent."""
    source = FRONTEND_REGISTRY.read_text(encoding="utf-8")
    listed = re.search(r"export const QUESTION_TYPES = \[(.*?)\] as const;", source, re.S)
    assert listed, "QUESTION_TYPES introuvable dans registry.ts"
    assert tuple(re.findall(r'"([a-z_]+)"', listed.group(1))) == qt.KEYS

    meta_block = re.search(
        r"QUESTION_TYPE_META: Record<QuestionType, QuestionTypeMeta> = \{(.*?)\n\};", source, re.S
    )
    assert meta_block, "QUESTION_TYPE_META introuvable dans registry.ts"
    widgets = dict(re.findall(r"\n  ([a-z_]+): \{.*?widget: \"(\w+)\"", meta_block.group(1)))
    assert tuple(widgets) == qt.KEYS
    # Seul « ordering » impose son widget côté UI (les autres suivent la présence
    # de choix) : c'est le seul dont l'accord doit être strict.
    assert widgets["ordering"] == qt.WIDGET_ORDERING
    assert qt.widget("ordering") == qt.WIDGET_ORDERING


def test_frontend_declares_a_label_for_every_type():
    """Un type sans libellé afficherait sa clé brute dans le badge."""
    i18n_file = FRONTEND_REGISTRY.parents[2] / "i18n" / "index.ts"
    source = i18n_file.read_text(encoding="utf-8")
    for key in qt.KEYS:
        assert source.count(f'"qtype.{key}":') == 2, key       # FR + EN
        assert source.count(f'"qtype.{key}.hint":') == 2, key
