# Budget de contexte des prompts du feuilleton (plan G2, V12).
#
# Si `tokens du prompt + num_predict > num_ctx`, Ollama tronque silencieusement
# le DÉBUT du prompt — rôle et consignes (architecture/18-pipeline-lang.md
# § 3.6). Chaque prompt est construit ici sur son cas MAXIMAL (dernier palier,
# bible complète, trois résumés longs, refus précédent, écriture la plus
# coûteuse) et comparé au budget de sa tâche avec une estimation pessimiste.
#
# PAR MACHINE depuis la table des modèles (fixture `machine`) : un profil par
# couple (tokenizer, plafond de contexte) de config/settings.LLM_MODELS, en mode
# normal et en mode économe. Ce sont les options EFFECTIVES qui comptent
# (`settings.task_options` : plafond du modèle, contexte unique du mode
# économe) et le tokenizer de CE modèle qui compte les tokens — qwen3 paie
# l'arabe vocalisé un tiers plus cher que Gemma, dans une fenêtre de 4096 au
# lieu de 5120. Un budget vérifié pour le seul modèle de référence débordait
# en silence sur le palier minuscule. En mode économe, les tâches de fond ne
# partent pas (OLLAMA_BACKGROUND_TASKS) : elles ne sont pas vérifiées là.
from types import SimpleNamespace

import pytest

from config import settings
from config.settings import (
    LANG_EXPLANATION_MAX_CHARS,
    LANG_GLOSSARY_CHUNK,
    LANG_KNOWN_WORDS_PROMPT_TOKENS,
    LANG_MAX_UNITS_PER_LINE,
    LANG_NOTE_MAX_CHARS,
    LANG_SUMMARY_MAX_CHARS,
    LLM_MODELS,
    OLLAMA_BACKGROUND_TASKS,
    max_units_per_episode,
    task_options,
)
from llm import prompts
from llm.prompts import estimate_prompt_tokens

LANGS = ["fr", "en"]

# Un profil par (tokenizer, plafond de contexte) : deux modèles qui partagent
# les deux ont exactement les mêmes budgets.
_PROFILES: dict = {}
for _profile in LLM_MODELS.values():
    _PROFILES.setdefault((_profile.tokenizer, _profile.max_num_ctx), _profile)
_PROFILES = list(_PROFILES.values())


@pytest.fixture(params=[(p, eco) for p in _PROFILES for eco in (False, True)],
                ids=lambda param: f"{param[0].name}-{'econome' if param[1] else 'normal'}")
def machine(request, monkeypatch):
    profile, economy = request.param
    monkeypatch.setattr(settings, "_active_profile", lambda: profile)
    monkeypatch.setattr(settings, "_economy", lambda: economy)
    return SimpleNamespace(profile=profile, economy=economy, tokenizer=profile.tokenizer)


LONG_FR = "Une phrase française assez longue pour occuper la place maximale autorisée, " * 4
CHARACTERS = [
    {"name": f"Personnage{i}", "role": LONG_FR[:80], "trait": LONG_FR[:120]} for i in range(4)
]
MAX_LINES = 24
# Épisode le plus long admis par le validateur (`max_units_per_episode`, par
# écriture ET par tokenizer), réparti sur le nombre de répliques maximal, avec
# des longueurs de mots réalistes : 5 lettres en espagnol, 9 caractères pour un
# mot arabe vocalisé ; la traduction française compte un peu plus de mots que
# l'original (1,5 par caractère chinois).
def _line(family: str, tokenizer: str) -> tuple[str, str]:
    units = min(LANG_MAX_UNITS_PER_LINE, max_units_per_episode(family, tokenizer) // MAX_LINES)
    fr_words = int(units * (1.2 if family != "hanzi" else 0.7))
    translation = " ".join(["mots"] * fr_words).replace("mots", "texte")
    if family == "hanzi":
        return "我" * units, translation
    if family == "arabe":
        return " ".join(["كِتَابُهُ"] * units), translation
    return " ".join(["palab"] * units), translation


def _known(family: str) -> list[str]:
    """Mots connus de l'apprenant au plafond de leur budget, dans chaque
    écriture — comptés par le tokenizer du modèle actif, comme en production."""
    word = {"latin": "palabra", "hanzi": "我", "arabe": "كِتَابُهُ"}[family]
    return prompts.fit_word_list([word] * 5000, LANG_KNOWN_WORDS_PROMPT_TOKENS)


REJECTED = "; ".join(["réplique 12 : vocalisation incomplète : chaque consonne doit porter sa voyelle"] * 5)


def _check(task: str, prompt: str, lang: str, machine) -> None:
    if machine.economy and task in OLLAMA_BACKGROUND_TASKS:
        return  # suspendue en mode économe : ce prompt ne part jamais
    options = task_options(task)
    system = estimate_prompt_tokens(prompts.build_system_prompt(lang), machine.tokenizer)
    used = system + estimate_prompt_tokens(prompt, machine.tokenizer) + options["num_predict"]
    assert used <= options["num_ctx"], (
        f"{task} ({lang}, {machine.profile.name}{', économe' if machine.economy else ''}) : "
        f"{used} tokens estimés > num_ctx {options['num_ctx']}"
    )


def _longest_point_fields():
    """Champ le plus COÛTEUX en tokens, pas le plus long : une consigne
    mandarin courte mais dense en hanzi pèse plus qu'une longue consigne
    française."""
    import json
    from pathlib import Path

    base = Path(__file__).resolve().parents[2] / "data" / "lang" / "program"
    longest = {"title": "", "notice": "", "dialogue_constraint": "", "explanation_seed": ""}
    for path in base.glob("*.json"):
        for p in json.loads(path.read_text(encoding="utf-8"))["points"]:
            for key in longest:
                # La version anglaise (`title_en`) part dans les prompts anglais.
                for value in (p[key], p.get(f"{key}_en") or ""):
                    if estimate_prompt_tokens(value) > estimate_prompt_tokens(longest[key]):
                        longest[key] = value
    return longest


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("family", ["latin", "hanzi", "arabe"])
def test_episode_text_prompt_fits(family, lang, machine):
    point = _longest_point_fields()
    rules = prompts.LANG_FORMAT_RULES_EN if lang == "en" else prompts.LANG_FORMAT_RULES
    prompt = prompts.build_lang_episode_text_prompt({
        "explain_lang": lang,
        "language_label": "arabe littéraire", "episode_n": 270, "characters": CHARACTERS,
        "setting": LONG_FR[:200], "recent": [LONG_FR[:LANG_SUMMARY_MAX_CHARS]] * 3, "beat": LONG_FR[:200],
        "format_rule": max(rules.values(), key=len),
        "point_title": point["title"], "point_constraint": point["dialogue_constraint"],
        "constraints": "entre 18 et 24 répliques ; longueur des répliques libre, phrases naturelles ; "
                       "au plus 16 mots nouveaux pour l'apprenant ; le reste doit être très courant.",
        "recycle": ["palabra"] * 10, "script_rules": LONG_FR[:400], "lines_target": 24,
        "known_words": _known(family), "known_chars": family == "hanzi",
        "line_schema": '{"speaker": "prénom", "text": "réplique", "tokens": ["mot"], "translation": "traduction"}',
        "rejected": REJECTED,
    })
    assert _known(family)[0] in prompt
    _check("lang_episode_text_hanzi" if family == "hanzi" else "lang_episode_text", prompt, lang, machine)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("family", ["latin", "hanzi", "arabe"])
def test_glossary_prompt_fits(family, lang, machine):
    text, tr = _line(family, machine.tokenizer)
    word = text.split(" ")[0] if " " in text else text[:2]
    # Au plus LANG_GLOSSARY_CHUNK mots par appel (`_glossary_in_chunks`) : c'est
    # le vrai maximum d'un prompt de glossaire, refus compris.
    prompt = prompts.build_lang_episode_glossary_prompt({
        "language_label": "arabe littéraire", "words": [word] * LANG_GLOSSARY_CHUNK,
        "lines": [(text, tr)] * MAX_LINES, "form_rule": LONG_FR[:300], "rejected": REJECTED,
        "explain_lang": lang, "pron": family == "latin", "register": LONG_FR[:120],
    })
    _check("lang_episode_glossary_pron" if family == "latin" else "lang_episode_glossary", prompt, lang, machine)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("family", ["latin", "hanzi", "arabe"])
def test_notes_point_prompt_fits(family, lang, machine):
    text, tr = _line(family, machine.tokenizer)
    point = _longest_point_fields()
    prompt = prompts.build_lang_episode_notes_point_prompt({
        "explain_lang": lang,
        "language_label": "arabe littéraire", "lines": [(text, tr)] * MAX_LINES,
        "point_title": point["title"], "point_notice": point["notice"], "point_seed": point["explanation_seed"],
        "notes_min": 3, "notes_max": 5, "examples_min": 2, "examples_max": 4,
        "note_max": LANG_NOTE_MAX_CHARS, "explanation_max": LANG_EXPLANATION_MAX_CHARS, "rejected": REJECTED,
    })
    _check("lang_episode_notes_point", prompt, lang, machine)


@pytest.mark.parametrize("lang", LANGS)
def test_bible_arc_and_weekly_prompts_fit(lang, machine):
    _check("lang_story_bible", prompts.build_lang_story_bible_prompt({
        "language_label": "arabe littéraire", "interests": ["un centre d'intérêt assez long"] * 8,
        "register": LONG_FR[:400], "characters_min": 3, "characters_max": 4, "explain_lang": lang,
    }), lang, machine)
    point = _longest_point_fields()
    _check("lang_story_arc", prompts.build_lang_story_arc_prompt({
        "language_label": "arabe littéraire", "characters": CHARACTERS, "setting": LONG_FR[:200],
        "comic_springs": LONG_FR[:300], "recent": [LONG_FR[:LANG_SUMMARY_MAX_CHARS]] * 6,
        "points": [{"title": point["title"], "notice": point["notice"]}] * 6, "explain_lang": lang,
    }), lang, machine)
    evolution = [{"week": "2026-09-07", "study_days": 7, "reveal_rate": 12.5, "understood": 0.5, "games": 0.75}] * 5
    _check("lang_weekly_analysis", prompts.build_lang_weekly_analysis_prompt({
        "language_label": "arabe littéraire", "explain_lang": lang,
        "aggregates": {"study_days_7": 7, "study_days_28": 28, "gaps": [1, 2, 3, 4, 5], "longest_streak": 12,
                       "usual_hour": 20, "mean_minutes": 14.5, "modes_7": {"episode": 5, "bilan": 1, "relecture": 1},
                       "evolution": evolution, "reveal_rate_regular_weeks": 8.2,
                       "reveal_rate_irregular_weeks": 14.1},
    }), lang, machine)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("family", ["latin", "hanzi", "arabe"])
def test_episode_hook_prompt_fits(family, lang, machine):
    from config.settings import LANG_HOOK_MAX_CHARS, LANG_HOOK_OPENING_LINES, LANG_TITLE_MAX_CHARS

    _text, tr = _line(family, machine.tokenizer)
    prompt = prompts.build_lang_episode_hook_prompt({
        "language_label": "arabe littéraire", "episode_n": 270, "title": LONG_FR[:LANG_TITLE_MAX_CHARS],
        "summary": LONG_FR[:LANG_SUMMARY_MAX_CHARS], "previous": LONG_FR[:LANG_SUMMARY_MAX_CHARS],
        "opening": [("Personnage0", tr)] * LANG_HOOK_OPENING_LINES, "characters": CHARACTERS,
        "max_chars": LANG_HOOK_MAX_CHARS, "explain_lang": lang,
    })
    _check("lang_episode_hook", prompt, lang, machine)


def test_episode_hook_prompt_carries_no_target_word():
    """Ni phrase d'exemple ni mot de la langue cible dans la consigne : seules
    les données de l'épisode (titre, résumé, début traduit) en apportent."""
    for lang in LANGS:
        text = prompts.build_lang_episode_hook_prompt({
            "language_label": "espagnol", "episode_n": 1, "title": "T", "summary": "S", "previous": "",
            "opening": [], "characters": [], "max_chars": 200, "explain_lang": lang,
        })
        assert not any(word in text.split() for word in ("estar", "ser", "soy", "estoy", "hola"))


def test_estimator_is_pessimistic_on_known_counts():
    # Repère mesuré par le banc (gemma4:e4b) : le français tourne autour de
    # quatre caractères par token ; l'estimateur doit rester au-dessus.
    text = "Le chat de la voisine dort sur le canapé depuis ce matin. " * 20
    assert estimate_prompt_tokens(text) >= len(text) / 4


@pytest.mark.parametrize("lang", LANGS)
def test_point_lesson_prompt_fits(lang, machine):
    from config.settings import (
        LANG_LESSON_EXAMPLES,
        LANG_LESSON_FORMS_MAX,
        LANG_LESSON_PITFALLS,
        LANG_LESSON_REMEMBER_MAX_CHARS,
        LANG_LESSON_RULE_MAX_CHARS,
        LANG_LESSON_USES,
    )

    point = _longest_point_fields()
    prompt = prompts.build_lang_point_lesson_prompt({
        "language_label": "arabe littéraire", "cefr": "B2", "point_title": point["title"],
        "learner_goal": LONG_FR[:200], "point_notice": point["notice"], "point_seed": point["explanation_seed"],
        "register": LONG_FR[:400], "writing_rules": LONG_FR[:300],
        "rule_max": LANG_LESSON_RULE_MAX_CHARS, "remember_max": LANG_LESSON_REMEMBER_MAX_CHARS,
        "forms_rows": LANG_LESSON_FORMS_MAX[0], "forms_cols": LANG_LESSON_FORMS_MAX[1],
        "uses_min": LANG_LESSON_USES[0], "uses_max": LANG_LESSON_USES[1], "pitfalls_max": LANG_LESSON_PITFALLS[1],
        "examples_min": LANG_LESSON_EXAMPLES[0], "examples_max": LANG_LESSON_EXAMPLES[1],
        "rejected": REJECTED, "explain_lang": lang,
    })
    _check("lang_point_lesson", prompt, lang, machine)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("family", ["latin", "hanzi", "arabe"])
def test_writing_feedback_prompt_fits(family, lang, machine):
    from config.settings import LANG_WRITING_ERROR_TYPES, LANG_WRITING_MAX_CHARS

    # Le texte le plus long qu'accepte l'envoi, dans l'écriture la plus coûteuse.
    text = {"latin": "palabra ", "hanzi": "我", "arabe": "كِتَابُهُ "}[family] * LANG_WRITING_MAX_CHARS
    prompt = prompts.build_lang_writing_feedback_prompt({
        "language_label": "arabe littéraire", "cefr": "B2", "task": LONG_FR[:240] + " " + LONG_FR[:120],
        "text": text[:LANG_WRITING_MAX_CHARS], "writing_rules": LONG_FR[:300], "errors_max": 3,
        "error_types": list(LANG_WRITING_ERROR_TYPES), "rejected": REJECTED, "explain_lang": lang,
    })
    _check("lang_writing_feedback", prompt, lang, machine)


def test_lesson_and_feedback_prompts_carry_no_target_word():
    """Squelettes sans aucun mot de la langue cible : un petit modèle recopie les
    exemples d'une consigne (mesuré au banc). Seules les données du point en ont."""
    from config.settings import LANG_WRITING_ERROR_TYPES

    common = {"language_label": "espagnol", "cefr": "A1", "point_title": "T", "learner_goal": "G",
              "point_notice": "N", "point_seed": "S", "rule_max": 600, "remember_max": 180, "forms_rows": 8,
              "forms_cols": 4, "uses_min": 1, "uses_max": 4, "pitfalls_max": 3, "examples_min": 2,
              "examples_max": 4, "task": "T", "text": "X", "errors_max": 3,
              "error_types": list(LANG_WRITING_ERROR_TYPES)}
    for lang in LANGS:
        for build in (prompts.build_lang_point_lesson_prompt, prompts.build_lang_writing_feedback_prompt):
            text = build({**common, "explain_lang": lang})
            assert not any(word in text.split() for word in ("estar", "ser", "soy", "estoy", "hola"))


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("family", ["latin", "hanzi", "arabe"])
def test_manual_card_lang_prompt_fits(family, lang, machine):
    """Règles de langue d'une carte manuelle : deux faces au plafond de
    MANUAL_CARD_LANG_MAX_CHARS (au-delà, aucun appel), dans l'écriture la plus
    coûteuse, et la liste fermée de toutes les langues."""
    from config.settings import LANGUAGE_SCRIPTS, MANUAL_CARD_LANG_MAX_CHARS

    side = {"latin": LONG_FR, "hanzi": "我" * 500, "arabe": "كِتَابُهُ " * 100}[family][:MANUAL_CARD_LANG_MAX_CHARS]
    prompt = prompts.build_manual_card_lang_prompt({
        "front": side, "back": side, "languages": tuple(LANGUAGE_SCRIPTS), "explain_lang": lang,
    })
    _check("flashcard_lang_rules", prompt, lang, machine)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("family", ["latin", "hanzi", "arabe"])
def test_lang_correction_prompt_fits(family, lang, machine):
    """Correction d'une production : phrase attendue et tentative au plafond de
    LANG_CORRECTION_MAX_CHARS (le service coupe au-delà), dans l'écriture la
    plus coûteuse, et un nom de langue au plafond de LANG_NAME_MAX_CHARS."""
    from config.settings import LANG_CORRECTION_MAX_CHARS, LANG_NAME_MAX_CHARS

    text = {"latin": LONG_FR * 2, "hanzi": "我" * 500, "arabe": "كِتَابُهُ " * 100}[family][:LANG_CORRECTION_MAX_CHARS]
    assert len(text) == LANG_CORRECTION_MAX_CHARS
    prompt = prompts.build_lang_correction_prompt("x" * LANG_NAME_MAX_CHARS, text, text)
    _check("lang_correction", prompt, lang, machine)
