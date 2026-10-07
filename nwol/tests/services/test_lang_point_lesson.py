# La leçon d'un point (étape « leçon ») : validation, sources, écriture, items.
#
# Clikoda est remplacé par tests/lang_fakes.py ; les validateurs, la lecture du
# fichier de leçons, la base et les items tournent pour de vrai.
import copy

import pytest

import lang_fakes
from services import lang_games as games
from services import lang_point_lesson as lessons

LANG = "espagnol"
POINT = "es.a1.saludos"


def _fake_lesson(en=False):
    out = {}
    lang_fakes.fake_lesson({"explain_lang": "en" if en else "fr", "language_label": "espagnol"},
                           out.update, lambda e: None)
    return out


@pytest.fixture
def lang_db(tmp_path, monkeypatch):
    import db

    db.close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "lesson.db"))
    from db.schema import initialize_schema
    from services.lang_runs import on_startup

    initialize_schema()
    on_startup()
    lang_fakes.install(monkeypatch)
    yield
    db.close_connection()


# ── Validation ────────────────────────────────────────────────────────────────

def test_a_good_lesson_passes_in_both_explanation_languages():
    for en in (False, True):
        cleaned, errors = lessons.validate_lesson(LANG, _fake_lesson(en), "en" if en else "fr")
        assert errors == [] and cleaned["rule"] and len(cleaned["examples"]) == 2
        assert cleaned["forms"]["columns"] == ["", "ser", "estar"]


@pytest.mark.parametrize("mutation,needle", [
    (lambda le: le.update(rule=""), '"rule" manquant'),
    (lambda le: le.update(rule="x" * 700), "trop long"),
    (lambda le: le.update(remember=""), '"remember" manquant'),
    (lambda le: le["examples"].__delitem__(slice(1, None)), "exemple(s) au lieu de"),
    (lambda le: le.update(uses=[]), "emploi(s) au lieu de"),
    (lambda le: le["examples"][0].update(text="Je suis très content et nous sommes là."), "du français"),
    (lambda le: le["examples"][0].update(translation=""), "traduction manquante"),
    (lambda le: le.update(rule="The rule is that you use estar with the state."), "écris-le en français"),
    (lambda le: le["forms"]["rows"][0].__setitem__(1, "une phrase entière qui n'a rien à faire dans une case"), "une case"),
    (lambda le: le.update(remember="*Estar* pour un état."), "mise en forme interdite"),
])
def test_each_lesson_rule(mutation, needle):
    lesson = _fake_lesson()
    mutation(lesson)
    _, errors = lessons.validate_lesson(LANG, lesson, "fr")
    assert any(needle in e for e in errors), errors


def test_a_too_big_table_is_cut_not_refused():
    from config.settings import LANG_LESSON_FORMS_MAX

    lesson = _fake_lesson()
    lesson["forms"]["columns"] += ["a", "b", "c"]
    lesson["forms"]["rows"] = [["yo", "soy", "estoy", "x", "y", "z"]] * 12
    cleaned, errors = lessons.validate_lesson(LANG, lesson, "fr")
    assert errors == []
    assert len(cleaned["forms"]["columns"]) == LANG_LESSON_FORMS_MAX[1]
    assert len(cleaned["forms"]["rows"]) == LANG_LESSON_FORMS_MAX[0] - 1


def test_arabic_lessons_are_vocalized_and_pausal_is_computed():
    lesson = {
        "rule": "La phrase nominale n'a pas de verbe au présent.",
        "uses": [{"use": "Présenter quelqu'un", "example": "هٰذَا كِتَابٌ جَمِيلٌ", "translation": "C'est un beau livre."}],
        "pitfalls": [],
        "examples": [{"text": "أَنَا طَالِبٌ", "translation": "Je suis étudiant."},
                     {"text": "هِيَ طَالِبَةٌ", "translation": "Elle est étudiante."}],
        "remember": "Pas de verbe être au présent.",
    }
    cleaned, errors = lessons.validate_lesson("arabe", lesson, "fr", pausal=True)
    assert errors == [], errors
    assert cleaned["examples"][0]["text"] == "أَنَا طَالِبْ"  # forme pausale calculée
    bare = copy.deepcopy(lesson)
    bare["examples"][0]["text"] = "انا طالب"
    assert any("vocalisation" in e for e in lessons.validate_lesson("arabe", bare, "fr")[1])
    latin = copy.deepcopy(lesson)
    latin["examples"][1]["text"] = "hiya taliba"
    assert any("lettres arabes" in e for e in lessons.validate_lesson("arabe", latin, "fr")[1])


def test_mandarin_lessons_refuse_pinyin_and_traditional_characters():
    lesson = {"rule": "On emploie 是 pour identifier.", "remember": "是 relie deux noms.",
              "uses": [{"use": "Identifier", "example": "我是学生。", "translation": "Je suis étudiant."}],
              "pitfalls": [], "examples": [{"text": "他是老师。", "translation": "Il est professeur."},
                                           {"text": "她是医生。", "translation": "Elle est médecin."}]}
    assert lessons.validate_lesson("mandarin", lesson, "fr")[1] == []
    lesson["examples"][0]["text"] = "Tā shì lǎoshī."
    lesson["uses"][0]["example"] = "我們是學生。"
    errors = lessons.validate_lesson("mandarin", lesson, "fr")[1]
    assert any("sans caractères chinois" in e for e in errors) and any("traditionnels" in e for e in errors)


def test_the_arabic_lesson_keeps_its_endings_once_irab_is_in_the_programme(lang_db):
    assert lessons.lesson_pausal("arabe", "ar.a1.voyelles_longues") is True
    assert lessons.lesson_pausal("arabe", "ar.a2.i3rab_cas") is False
    assert lessons.lesson_pausal("espagnol", POINT) is False


# ── Sources : fichier, base, repli ────────────────────────────────────────────

def test_a_written_lesson_is_kept_and_shared_until_its_point_changes(lang_db):
    from db import lang_episode_db as store

    assert lessons.ensure_point_lesson(LANG, POINT, "fr") == "ready"
    assert lessons.lesson_for(LANG, POINT, "fr")["source"] == "db"
    assert lessons.ensure_point_lesson(LANG, POINT, "fr") == "db"  # déjà là : aucun appel de plus
    assert lang_fakes.CALLS.count("lesson") == 1
    assert lessons.lesson_for(LANG, POINT, "en") is None  # une leçon par langue d'explication
    row = store.get_point_lesson(LANG, POINT, "fr")
    store.save_point_lesson(LANG, POINT, "fr", status="ready", lesson=row["lesson"], point_hash="ancien",
                            model="m", attempts=1, generation={})
    assert lessons.lesson_for(LANG, POINT, "fr") is None  # le point a changé : la leçon est à réécrire


def test_a_hand_written_lesson_file_comes_first(lang_db, monkeypatch):
    lesson = _fake_lesson()
    lesson["rule"] = "Règle écrite à la main."
    monkeypatch.setattr(lessons, "lessons_file", lambda language: {"language": LANG, "lessons": {POINT: {"lesson": lesson}}})
    lang_fakes.CALLS.clear()
    found = lessons.lesson_for(LANG, POINT, "fr")
    assert found["source"] == "file" and found["lesson"]["rule"] == "Règle écrite à la main."
    assert lessons.ensure_point_lesson(LANG, POINT, "fr") == "file" and "lesson" not in lang_fakes.CALLS
    # Sans version anglaise dans le fichier, la française n'est jamais servie à
    # un profil anglais : sa leçon est écrite par Clikoda, en anglais.
    assert lessons.lesson_for(LANG, POINT, "en") is None
    assert lessons.ensure_point_lesson(LANG, POINT, "en") == "ready"
    assert lessons.lesson_for(LANG, POINT, "en")["lesson"]["rule"].startswith("Estar describes")


def test_a_failed_lesson_never_raises_and_gives_up_after_two_generations(lang_db, monkeypatch):
    from config.settings import LANG_LESSON_MAX_ATTEMPTS
    from llm import ollama_client

    monkeypatch.setattr(ollama_client, "generate_lang_point_lesson_async",
                        lambda params, ok, err, on_metrics=None, model=None: ok({"rule": "", "examples": []}))
    assert lessons.ensure_point_lesson(LANG, POINT, "fr") == "failed"
    assert lessons.ensure_point_lesson(LANG, POINT, "fr") == "failed"
    from db import lang_episode_db as store

    assert store.get_point_lesson(LANG, POINT, "fr")["attempts"] >= LANG_LESSON_MAX_ATTEMPTS
    assert lessons.ensure_point_lesson(LANG, POINT, "fr") == "gave_up"
    monkeypatch.setattr(ollama_client, "generate_lang_point_lesson_async",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("panne")))
    assert lessons.ensure_point_lesson(LANG, "es.a1.hay", "fr") == "failed"  # jamais d'exception


def test_the_fallback_never_shows_french_material_to_an_english_learner(lang_db):
    episode = {"point": {"explanation": "Estar is for a passing state."}}
    view = lessons.lesson_view(LANG, POINT, "en", episode)
    assert view["source"] == "fallback" and view["lesson"] is None
    assert view["title"] == "Greeting and introducing yourself" and view["learner_goal"].startswith("Can ")
    assert view["explanation"] == "Estar is for a passing state."
    assert "notice" not in view and "explanation_seed" not in view


def test_examples_get_their_computed_pronunciation(lang_db):
    pytest.importorskip("pypinyin")
    from services.lang_point_lesson import _with_aids

    lesson = {"rule": "r", "remember": "m", "uses": [], "pitfalls": [],
              "examples": [{"text": "你好。", "translation": "Bonjour."}]}
    assert _with_aids("mandarin", lesson)["examples"][0]["pron"] == "nǐ hǎo"
    arabic = {**lesson, "examples": [{"text": "كِتَابْ", "translation": "livre"}]}
    assert _with_aids("arabe", arabic)["examples"][0]["pron"]
    assert _with_aids(LANG, _fake_lesson())["examples"][0]["pron"] is None


# ── Entraînement : items déterministes ────────────────────────────────────────

def test_lesson_items_are_deterministic_and_graded_like_the_others():
    from config.settings import LANG_LESSON_ITEMS

    lesson = lessons.validate_lesson(LANG, _fake_lesson(), "fr")[0]
    items = lessons.lesson_items(LANG, lesson, seed=7)
    assert items == lessons.lesson_items(LANG, lesson, seed=7)
    assert len(items) == LANG_LESSON_ITEMS
    assert {it["prompt"].get("source") for it in items if it["kind"] == "bonne_forme"} == {"forms", "pitfall"}
    assert any(it["kind"] == "remettre_en_ordre" for it in items)
    for it in items:
        assert it["ref"].startswith("lecon.lesson.") and games.grade(it, it["expected"]) is True
    trap = next(it for it in items if it["prompt"].get("source") == "pitfall")
    assert games.grade(trap, "Soy cansado.") is False
    assert lessons.lesson_items(LANG, None, seed=7) == []


def test_validate_lessons_file():
    from services.lang_static import validate_lessons_file

    good = {"language": LANG, "lessons": {POINT: {"lesson": _fake_lesson(), "lesson_en": _fake_lesson(en=True)}}}
    assert validate_lessons_file(good, LANG, {POINT}) == []
    bad = copy.deepcopy(good)
    bad["lessons"]["es.zz.inconnu"] = {"lesson": _fake_lesson()}
    bad["lessons"][POINT]["lesson_en"]["rule"] = "Estar dit un état passager et il est très utile."
    errors = validate_lessons_file(bad, LANG, {POINT})
    assert any("hors programme" in e for e in errors) and any("(en)" in e for e in errors)
    assert validate_lessons_file({"language": "allemand"}, LANG, {POINT}) == ["fichier absent ou language incorrect"]
