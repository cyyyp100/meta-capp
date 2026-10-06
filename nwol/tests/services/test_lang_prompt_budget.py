# Budget de contexte des prompts du feuilleton (plan G2, V12).
#
# Si `tokens du prompt + num_predict > num_ctx`, Ollama tronque silencieusement
# le DÉBUT du prompt — rôle et consignes (architecture/18-pipeline-lang.md
# § 3.6). Chaque prompt est construit ici sur son cas MAXIMAL (dernier palier,
# bible complète, trois résumés longs, refus précédent, écriture la plus
# coûteuse) et comparé au budget de sa tâche avec une estimation pessimiste.
import pytest

from config.settings import (
    LANG_EXPLANATION_MAX_CHARS,
    LANG_GLOSSARY_MAX_ENTRIES,
    LANG_MAX_UNITS_PER_EPISODE,
    LANG_MAX_UNITS_PER_LINE,
    LANG_NOTE_MAX_CHARS,
    LANG_SUMMARY_MAX_CHARS,
    OLLAMA_TASK_OPTIONS,
)
from llm import prompts
from llm.prompts import estimate_prompt_tokens

# Le prompt système (build_system_prompt) voyage avec chaque génération, dans
# la langue d'explication du profil (§ 14, n° 14) : les deux sont vérifiées.
SYSTEM = {lang: estimate_prompt_tokens(prompts.build_system_prompt(lang)) for lang in ("fr", "en")}
LANGS = ["fr", "en"]

LONG_FR = "Une phrase française assez longue pour occuper la place maximale autorisée, " * 4
CHARACTERS = [
    {"name": f"Personnage{i}", "role": LONG_FR[:80], "trait": LONG_FR[:120]} for i in range(4)
]
MAX_LINES = 24
# Épisode le plus long admis par le validateur (LANG_MAX_UNITS_PER_EPISODE, par
# écriture), réparti sur le nombre de répliques maximal, avec des longueurs de
# mots réalistes : 5 lettres en espagnol, 9 caractères pour un mot arabe
# vocalisé ; la traduction française compte un peu plus de mots que l'original
# (1,5 par caractère chinois).
def _line(family: str) -> tuple[str, str]:
    units = min(LANG_MAX_UNITS_PER_LINE, LANG_MAX_UNITS_PER_EPISODE[family] // MAX_LINES)
    fr_words = int(units * (1.2 if family != "hanzi" else 0.7))
    translation = " ".join(["mots"] * fr_words).replace("mots", "texte")
    if family == "hanzi":
        return "我" * units, translation
    if family == "arabe":
        return " ".join(["كِتَابُهُ"] * units), translation
    return " ".join(["palab"] * units), translation


LINE = {family: _line(family) for family in ("latin", "hanzi", "arabe")}
REJECTED = "; ".join(["réplique 12 : vocalisation incomplète : chaque consonne doit porter sa voyelle"] * 5)


def _check(task: str, prompt: str, lang: str = "fr") -> None:
    options = OLLAMA_TASK_OPTIONS[task]
    used = SYSTEM[lang] + estimate_prompt_tokens(prompt) + options["num_predict"]
    assert used <= options["num_ctx"], f"{task} ({lang}) : {used} tokens estimés > num_ctx {options['num_ctx']}"


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
def test_episode_text_prompt_fits(family, lang):
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
        "line_schema": '{"speaker": "prénom", "text": "réplique", "tokens": ["mot"], "translation": "traduction"}',
        "rejected": REJECTED,
    })
    _check("lang_episode_text_hanzi" if family == "hanzi" else "lang_episode_text", prompt, lang)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("family", ["latin", "hanzi", "arabe"])
def test_glossary_prompt_fits(family, lang):
    text, tr = LINE[family]
    word = text.split(" ")[0] if " " in text else text[:2]
    prompt = prompts.build_lang_episode_glossary_prompt({
        "language_label": "arabe littéraire", "words": [word] * max(LANG_GLOSSARY_MAX_ENTRIES),
        "lines": [(text, tr)] * MAX_LINES, "form_rule": LONG_FR[:300], "rejected": REJECTED,
        "explain_lang": lang, "pron": family == "latin", "register": LONG_FR[:120],
    })
    _check("lang_episode_glossary_pron" if family == "latin" else "lang_episode_glossary", prompt, lang)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("family", ["latin", "hanzi", "arabe"])
def test_notes_point_prompt_fits(family, lang):
    text, tr = LINE[family]
    point = _longest_point_fields()
    prompt = prompts.build_lang_episode_notes_point_prompt({
        "explain_lang": lang,
        "language_label": "arabe littéraire", "lines": [(text, tr)] * MAX_LINES,
        "point_title": point["title"], "point_notice": point["notice"], "point_seed": point["explanation_seed"],
        "notes_min": 3, "notes_max": 5, "examples_min": 2, "examples_max": 4,
        "note_max": LANG_NOTE_MAX_CHARS, "explanation_max": LANG_EXPLANATION_MAX_CHARS, "rejected": REJECTED,
    })
    _check("lang_episode_notes_point", prompt, lang)


@pytest.mark.parametrize("lang", LANGS)
def test_bible_arc_and_weekly_prompts_fit(lang):
    _check("lang_story_bible", prompts.build_lang_story_bible_prompt({
        "language_label": "arabe littéraire", "interests": ["un centre d'intérêt assez long"] * 8,
        "register": LONG_FR[:400], "characters_min": 3, "characters_max": 4, "explain_lang": lang,
    }), lang)
    point = _longest_point_fields()
    _check("lang_story_arc", prompts.build_lang_story_arc_prompt({
        "language_label": "arabe littéraire", "characters": CHARACTERS, "setting": LONG_FR[:200],
        "comic_springs": LONG_FR[:300], "recent": [LONG_FR[:LANG_SUMMARY_MAX_CHARS]] * 6,
        "points": [{"title": point["title"], "notice": point["notice"]}] * 6, "explain_lang": lang,
    }), lang)
    evolution = [{"week": "2026-09-07", "study_days": 7, "reveal_rate": 12.5, "understood": 0.5, "games": 0.75}] * 5
    _check("lang_weekly_analysis", prompts.build_lang_weekly_analysis_prompt({
        "language_label": "arabe littéraire", "explain_lang": lang,
        "aggregates": {"study_days_7": 7, "study_days_28": 28, "gaps": [1, 2, 3, 4, 5], "longest_streak": 12,
                       "usual_hour": 20, "mean_minutes": 14.5, "modes_7": {"episode": 5, "bilan": 1, "relecture": 1},
                       "evolution": evolution, "reveal_rate_regular_weeks": 8.2,
                       "reveal_rate_irregular_weeks": 14.1},
    }), lang)


def test_estimator_is_pessimistic_on_known_counts():
    # Repère mesuré par le banc (gemma4:e4b) : le français tourne autour de
    # quatre caractères par token ; l'estimateur doit rester au-dessus.
    text = "Le chat de la voisine dort sur le canapé depuis ce matin. " * 20
    assert estimate_prompt_tokens(text) >= len(text) / 4
