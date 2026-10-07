# Parseurs et validateurs déterministes du feuilleton (plan G3-G10 ; V1-V2).
#
# Les sorties « réelles » viennent de tests/fixtures/lang/ : épisodes écrits par
# gemma4:e4b au banc (tools/lang_bench.py) et acceptés. Chaque règle est ensuite
# vérifiée sur une variante cassée de ces sorties — c'est ainsi qu'un petit
# modèle se trompe vraiment (traduction oubliée, ancre réécrite, français glissé).
import copy
import json
from pathlib import Path

import pytest

from llm import schema_json
from services import lang_episodes as ep
from services import lang_progress as progress
from services.lang_text import fold

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "lang"
REAL = json.loads((FIXTURES / "espagnol_gemma_2026-09-24.json").read_text(encoding="utf-8"))


def _ctx(episode, **extra):
    names = REAL["bible_characters"]
    return {
        "params": episode["params"], "kind": "normal", "format": episode["format"],
        "speakers": {fold(n) for n in names} | {fold(ep.NARRATOR)}, "speaker_names": set(names),
        "lexicon": {}, "lexicon_forms": set(), "lexicon_size": 0, "recent": [], "pausal": True,
        "seen_chars": set(), **extra,
    }


@pytest.fixture(params=range(len(REAL["episodes"])))
def real(request):
    return copy.deepcopy(REAL["episodes"][request.param])


@pytest.fixture
def clean():
    """Un épisode réel accepté par toutes les règles actuelles."""
    return copy.deepcopy(next(e for e in REAL["episodes"] if not e["expected_text_errors"]))


# ── Parseurs (G3) ─────────────────────────────────────────────────────────────

def test_parsers_accept_the_real_outputs(real):
    assert schema_json.parse_lang_episode_text(json.dumps(real["text"]))["lines"]
    glossary = {"entries": [[g["form"], g["lemma"], g["translation"], g["pos"], g["gender"] or ""]
                            for g in real["glossary"]]}
    assert len(schema_json.parse_lang_episode_glossary(json.dumps(glossary))["entries"]) == len(real["glossary"])
    assert schema_json.parse_lang_episode_notes_point(json.dumps(real["notes_point"]))["point"]["examples"]


def test_parsers_reject_structurally_broken_outputs():
    assert schema_json.parse_lang_episode_text('{"title": "x", "lines": []}') is None
    assert schema_json.parse_lang_episode_glossary('{"entries": [["mot"]]}') is None
    assert schema_json.parse_lang_episode_notes_point('{"notes": [], "point": {"explanation": ""}}') is None
    assert schema_json.parse_lang_story_bible('{"characters": [{"name": "Ana"}]}') is None
    assert schema_json.parse_lang_story_arc('{"beats": []}') is None
    assert schema_json.parse_lang_weekly_analysis('{"observations": []}') is None


def test_parsers_recover_a_truncated_text():
    raw = json.dumps({"title": "t", "summary": "s", "teaser": "a",
                      "lines": [{"speaker": "Ana", "text": "Hola.", "translation": "Salut."}] * 3})[:-40]
    parsed = schema_json.parse_lang_episode_text(raw)
    assert parsed and parsed["summary"] == "s"  # résumé placé avant les répliques : il survit


# ── Texte (G4-G6, G9) ─────────────────────────────────────────────────────────

def test_real_text_is_judged_as_recorded(real):
    """Une sortie réelle acceptée passe ; celle qu'une règle ajoutée depuis
    refuse (`expected_text_errors`) est refusée pour cette raison-là."""
    _, errors = ep.validate_text("espagnol", real["text"], _ctx(real))
    expected = real["expected_text_errors"]
    if not expected:
        assert errors == []
    for needle in expected:
        assert any(needle in e for e in errors), errors


@pytest.mark.parametrize("mutation,needle", [
    (lambda t: t["lines"].__delitem__(slice(2, None)), "répliques au lieu de"),
    (lambda t: t["lines"][0].update(translation=""), "traduction française manquante"),
    (lambda t: [ln.update(speaker=f"Inconnu{i % 2}") for i, ln in enumerate(t["lines"])], "hors de la bible"),
    (lambda t: t["lines"][2].update(text="Mi portfolio es un game changer, ¿sabes?"), "mots anglais"),
    (lambda t: t["lines"][2].update(text="Je suis très content et nous sommes avec elle."), "du français"),
    (lambda t: t["lines"][0].update(text="¡Mi *networking* es genial!"), "astérisques"),
    (lambda t: t.update(summary=""), '"summary" manquant'),
    (lambda t: t.update(title="x" * 200), "trop long"),
])
def test_text_rules(clean, mutation, needle):
    text = clean["text"]
    mutation(text)
    _, errors = ep.validate_text("espagnol", text, _ctx(clean))
    assert any(needle in e for e in errors), errors


def test_repetition_is_rejected(real):
    recent = [(real["text"]["title"], real["text"]["summary"])]
    _, errors = ep.validate_text("espagnol", real["text"], _ctx(real, recent=recent))
    assert any("trop proche" in e for e in errors)


def test_too_many_new_words_is_a_soft_problem(clean):
    """Le dépassement est estimé : c'est un problème DOUX, que `_attempts`
    accepte en dernier recours, jamais une raison de faire échouer l'épisode."""
    ctx = _ctx(clean, lexicon_size=500, lexicon_forms={"hola"}, check_new_words=True)
    value, errors = ep.validate_text("espagnol", clean["text"], ctx)
    soft = [e for e in errors if "mots nouveaux" in e]
    assert soft and all(isinstance(e, ep.SoftProblem) and e.weight > 1 for e in soft)
    assert value["new_words_estimate"]["checked"] is True
    assert value["new_words_estimate"]["estimate"] > value["new_words_estimate"]["cap"]
    from services.lang_text import words
    known = {fold(w) for ln in clean["text"]["lines"] for w in words(ln["text"])}
    _, errors = ep.validate_text("espagnol", clean["text"], _ctx(clean, lexicon_forms=known, check_new_words=True))
    assert not any("mots nouveaux" in e for e in errors)


def test_new_words_are_only_checked_when_the_context_says_so(clean):
    value, errors = ep.validate_text("espagnol", clean["text"], _ctx(clean, lexicon_size=500, lexicon_forms={"hola"}))
    assert not any("mots nouveaux" in e for e in errors)
    assert value["new_words_estimate"]["checked"] is False  # estimé quand même, pour le journal


def test_words_already_read_are_known(clean):
    """Une forme fléchie, un mot court ou un mot jamais glosé, déjà LU dans un
    épisode joué, n'est pas nouveau ; un nombre non plus."""
    text = {"lines": [{"speaker": "Ana", "text": "Tiene 25 años y él come.", "translation": "x"}]}
    ctx = {"speakers": set(), "lexicon_forms": {"tener"}}
    assert ep.estimate_new_words("espagnol", text["lines"], ctx) == 5  # tiene, años, y, él, come
    ctx["seen_forms"] = {ep._match_key("espagnol", w) for w in ("tiene", "y", "él", "comemos")}
    assert ep.estimate_new_words("espagnol", text["lines"], ctx) == 1  # años
    assert ep.estimate_new_words("mandarin", [{"text": "你好吗"}], {"seen_chars": {"你"}, "read_chars": ["好"]}) == 1


def test_mandarin_tokens_and_simplified_characters():
    params = progress.ladder_params("mandarin", 0)
    ctx = {"params": params, "kind": "normal", "format": "dialogue", "speakers": {"ana", "li", fold(ep.NARRATOR)},
           "speaker_names": {"Ana", "Li"}, "lexicon_size": 0, "recent": []}
    good = {"title": "t", "summary": "s", "teaser": "a", "lines": [
        {"speaker": "Ana", "text": "你好，我是安娜。", "translation": "Bonjour, je suis Anna.",
         "tokens": ["你好", "，", "我", "是", "安娜", "。"]},
        {"speaker": "Li", "text": "你好！我叫小李。", "translation": "Bonjour ! Je m'appelle Petit Li.",
         "tokens": ["你好", "！", "我", "叫", "小李", "。"]},
    ] * 3}
    assert ep.validate_text("mandarin", good, ctx)[1] == []
    bad = copy.deepcopy(good)
    bad["lines"][0]["tokens"] = ["你好", "我", "是"]
    bad["lines"][1]["text"] = "你們好！我叫小李。"
    bad["lines"][1]["tokens"] = ["你們", "好", "！", "我", "叫", "小李", "。"]
    errors = ep.validate_text("mandarin", bad, ctx)[1]
    assert any("recollent" in e for e in errors) and any("traditionnels" in e for e in errors)


def test_arabic_vocalization_and_pausal_form():
    params = progress.ladder_params("arabe", 0)
    ctx = {"params": params, "kind": "normal", "format": "dialogue", "speakers": {"سمير", "ليلى", fold(ep.NARRATOR)},
           "speaker_names": set(), "lexicon_size": 0, "recent": [], "pausal": True}
    lines = [{"speaker": "سمير", "text": "مَرْحَبًا يَا لَيْلَى، كَيْفَ حَالُكِ؟", "translation": "Bonjour Leïla, comment vas-tu ?"},
             {"speaker": "ليلى", "text": "أَنَا بِخَيْرٍ، وَالْحَمْدُ لِلّٰهْ.", "translation": "Je vais bien, Dieu merci."}] * 3
    for ln in lines:
        ln["speaker"] = "سمير" if ln["speaker"] == "سمير" else "ليلى"
    ctx["speakers"] = {fold("سمير"), fold("ليلى"), fold(ep.NARRATOR)}
    good = {"title": "t", "summary": "s", "teaser": "a", "lines": lines}
    errors = ep.validate_text("arabe", good, ctx)[1]
    assert not any("vocalisation" in e for e in errors), errors
    bare = copy.deepcopy(good)
    bare["lines"][0]["text"] = "مرحبا يا ليلى، كيف حالك؟"
    assert any("vocalisation incomplète" in e for e in ep.validate_text("arabe", bare, ctx)[1])
    # A3 : la forme pausale est calculée, pas redemandée (au banc, Clikoda laissait
    # la voyelle finale dans deux textes sur trois).
    not_pausal = copy.deepcopy(good)
    not_pausal["lines"][1]["text"] = "أَنَا بِخَيْرٍ، وَالْحَمْدُ لِلّٰهِ."
    value, errors = ep.validate_text("arabe", not_pausal, ctx)
    assert not any("forme pausale" in e for e in errors), errors
    assert value["lines"][1]["text"] == "أَنَا بِخَيْرٍ، وَالْحَمْدُ لِلّٰهْ."
    # Après l'iʿrāb, les désinences restent telles quelles.
    value = ep.validate_text("arabe", not_pausal, {**ctx, "pausal": False})[0]
    assert value["lines"][1]["text"].endswith("لِلّٰهِ.")


@pytest.mark.parametrize("text,expected", [
    ("هٰذَا كِتَابٌ جَمِيلٌ", "هٰذَا كِتَابٌ جَمِيلْ"),       # -un -> sukūn
    ("أَنَا عَرَبِيٌّ", "أَنَا عَرَبِيّْ"),                 # la šadda reste
    ("هِيَ طَالِبَةٌ؟", "هِيَ طَالِبَةْ؟"),                 # tāʾ marbūṭa
    ("مَا اسْمُكَ؟", "مَا اسْمُكْ؟"),                     # pronom suffixe
    ("شُكْرًا جَزِيلًا!", "شُكْرًا جَزِيلًا!"),             # -an : inchangé
    ("هٰذَا لِي", "هٰذَا لِي"),                           # voyelle longue : inchangé
    ("الْغُرْفَةُ رَقْمُ ١٢", "الْغُرْفَةُ رَقْمُ ١٢"),       # fini par un nombre : inchangé
])
def test_to_pausal(text, expected):
    from services import lang_arabic

    assert lang_arabic.to_pausal(text) == expected
    assert not ep._arabic_problems(lang_arabic.to_pausal(text), True)


# ── Glossaire (G7) ────────────────────────────────────────────────────────────

def _lines(real):
    return ep.build_tokens("espagnol", real["text"]["lines"])


def test_glossary_request_skips_names_and_known_words(real):
    lines = _lines(real)
    asked, known = ep.glossary_request("espagnol", lines, _ctx(real))
    assert asked and not known
    assert not {fold(n) for n in REAL["bible_characters"]} & {fold(w) for w in asked}
    lexicon = {"hola": {"form": "Hola", "lemma": "hola", "translation": "salut", "pos": "interjection", "gender": None,
                        "pron": "ˈola"}}
    asked2, known2 = ep.glossary_request("espagnol", lines, _ctx(real, lexicon=lexicon))
    if any(fold(w) == "hola" for w in asked):
        assert known2 and known2[0]["translation"] == "salut" and len(asked2) == len(asked) - 1


def test_glossary_needs_one_entry_per_requested_word(real):
    lines = _lines(real)
    asked, _ = ep.glossary_request("espagnol", lines, _ctx(real))
    entries = [{"form": w, "lemma": w.lower(), "translation": "x", "pos": "nom", "gender": "m", "pron": "x"}
               for w in asked]
    kept, errors = ep.validate_glossary("espagnol", {"entries": entries}, lines, _ctx(real), asked)
    assert errors == [] and len(kept) == len(asked)
    kept, errors = ep.validate_glossary("espagnol", {"entries": entries[:2]}, lines, _ctx(real), asked)
    assert any("il manque une entrée" in e for e in errors)


def test_expressions_must_be_in_the_text(real):
    lines = _lines(real)
    words = [t["text"] for t in lines[0]["tokens"] if t["w"]]
    expr = " ".join(words[:2])
    result = {"entries": [], "expressions": [
        {"form": expr, "lemma": expr, "translation": "x", "pos": "expression", "gender": None, "pron": "x"},
        {"form": "no está aquí", "lemma": "x", "translation": "x", "pos": "expression", "gender": None, "pron": "x"},
    ]}
    kept, _ = ep.validate_glossary("espagnol", result, lines, _ctx(real), [])
    assert [e["form"] for e in kept] == [expr]


def test_german_nouns_need_a_gender():
    lines = ep.build_tokens("allemand", [{"speaker": "Anna", "text": "Das Haus ist groß.", "translation": "La maison est grande."}])
    ctx = {"params": progress.ladder_params("allemand", 0), "speakers": set(), "lexicon": {}}
    result = {"entries": [{"form": "Haus", "lemma": "Haus", "translation": "maison", "pos": "nom", "gender": None}]}
    assert any("genre manquant" in e for e in ep.validate_glossary("allemand", result, lines, ctx, ["Haus"])[1])
    result["entries"][0]["gender"] = "f"
    assert any("contredit" in e for e in ep.validate_glossary("allemand", result, lines, ctx, ["Haus"])[1])


# ── Notes et point (G8) ───────────────────────────────────────────────────────

def test_real_notes_and_point_pass(real):
    cleaned, errors = ep.validate_notes_point("espagnol", real["notes_point"], _lines(real))
    assert errors == [] and cleaned["point"]["examples"]


def test_anchors_and_examples_must_be_literal(real):
    broken = copy.deepcopy(real["notes_point"])
    for note in broken["notes"]:
        note["anchor"] = note["anchor"] + " (réécrit)"
    broken["point"]["examples"] = ["une phrase qui n'existe pas"]
    _, errors = ep.validate_notes_point("espagnol", broken, _lines(real))
    assert any("note(s) valide(s)" in e for e in errors) and any("exemples absents" in e for e in errors)


def test_distractors_equal_to_the_answer_are_dropped(real):
    np = copy.deepcopy(real["notes_point"])
    example = np["point"]["examples"][0]
    np["point"]["variants"] = [{"example": example, "distractors": [example, "forme fausse"]}]
    cleaned, _ = ep.validate_notes_point("espagnol", np, _lines(real))
    assert cleaned["point"]["variants"][0]["distractors"] == ["forme fausse"]


# ── Calculs déterministes (G11-G13) ───────────────────────────────────────────

def test_tokens_are_linked_to_the_glossary(real):
    lines = _lines(real)
    glossary = ep.enrich_glossary("espagnol", real["glossary"], {})
    ep.link_glossary("espagnol", lines, glossary)
    linked = sum(1 for ln in lines for t in ln["tokens"] if t.get("g") is not None)
    words = sum(1 for ln in lines for t in ln["tokens"] if t["w"])
    assert linked / words > 0.6
    assert all(g["new"] for g in glossary)


def test_a_bible_with_linguistic_quirks_is_refused():
    """Mesuré au banc : un personnage « qui abuse des anglicismes » truffait
    chaque texte de mots anglais entre astérisques."""
    bad = {"characters": [{"name": "Manolo", "role": "graphiste", "trait": "Exagère l'usage de l'anglicisme."},
                          {"name": "Ana", "role": "boulangère", "trait": "pragmatique"},
                          {"name": "Luis", "role": "retraité", "trait": "distrait"}]}
    assert any("travers linguistique" in p for p in ep._bible_problems(bad))
    bad["characters"][0]["trait"] = "toujours en retard"
    assert ep._bible_problems(bad) == []


def test_bible_names_are_kept_in_the_target_script():
    """Mesuré au banc mandarin : bible « 老李 (Lǎo Lǐ) », répliques « 老李 » ->
    chaque texte refusé (« locuteurs hors de la bible »)."""
    assert ep.clean_character_name("mandarin", "老李 (Lǎo Lǐ)") == "老李"
    assert ep.clean_character_name("mandarin", "Xiao Wang (小王)") == "小王"
    assert ep.clean_character_name("arabe", "سَلْمَى (Salmā)") == "سَلْمَى"
    assert ep.clean_character_name("espagnol", "Lucía (la patronne)") == "Lucía"
    bible = {"characters": [{"name": "老李 (Lǎo Lǐ)"}, {"name": "Xiao Fang (小芳)"}, {"name": "王大爷"}]}
    assert {fold("老李"), fold("小芳"), fold("王大爷")} <= ep._speaker_names(bible)
    # Un prénom en transcription seule ne peut pas être celui des répliques.
    latin_only = {"characters": [{"name": "Lao Li", "role": "r", "trait": "t"},
                                 {"name": "小芳", "role": "r", "trait": "t"},
                                 {"name": "王大爷", "role": "r", "trait": "t"}]}
    assert any("Lao Li" in p for p in ep._bible_problems(latin_only, "mandarin"))
    assert ep._bible_problems(latin_only, "espagnol") == []


def test_one_secondary_speaker_is_tolerated(clean):
    text = clean["text"]
    text["lines"][0]["speaker"] = "La turista"
    assert not any("hors de la bible" in e for e in ep.validate_text("espagnol", text, _ctx(clean))[1])


def test_glossary_is_cumulative_across_attempts(clean, monkeypatch):
    """Mesuré au banc : Clikoda rend parfois UNE entrée sur vingt. La tentative
    suivante ne redemande que les mots manquants, et les entrées s'additionnent."""
    from llm import ollama_client

    lines = _lines(clean)
    asked, _ = ep.glossary_request("espagnol", lines, _ctx(clean))
    calls = []

    def stingy(params, ok, err, on_metrics=None, model=None):
        calls.append(list(params["words"]))
        w = params["words"][0]
        ok({"entries": [{"form": w, "lemma": w.lower(), "translation": "x", "pos": "nom", "gender": "m", "pron": "x"}],
            "expressions": []})

    monkeypatch.setattr(ollama_client, "generate_lang_episode_glossary_async", stingy)
    log, metrics = [], []
    with pytest.raises(ep.GenerationFailed):  # une entrée par appel ne suffira pas…
        ep._glossary_in_chunks("espagnol", lines, _ctx(clean), asked, {"language_label": "espagnol"}, log, metrics)
    assert calls[1][0] == asked[1]  # …mais chaque appel ne redemande que ce qui manque

    def generous(params, ok, err, on_metrics=None, model=None):
        ok({"entries": [{"form": w, "lemma": w.lower(), "translation": "x", "pos": "nom", "gender": "m", "pron": "x"}
                        for w in params["words"]], "expressions": []})

    monkeypatch.setattr(ollama_client, "generate_lang_episode_glossary_async", generous)
    got = ep._glossary_in_chunks("espagnol", lines, _ctx(clean), asked, {"language_label": "espagnol"}, [], [])
    assert len(got) == len(asked)


def test_truncated_last_lines_are_dropped_not_fatal(clean):
    text = clean["text"]
    text["lines"].append({"speaker": text["lines"][0]["speaker"], "text": "Y entonces", "translation": ""})
    cleaned, errors = ep.validate_text("espagnol", text, _ctx(clean))
    assert errors == [] and cleaned["lines"][-1]["translation"]


# ── Accents : deux mots distincts, deux entrées (§ 14, n° 4) ──────────────────

def _es_lines(*texts):
    return ep.build_tokens("espagnol", [{"speaker": "Ana", "text": t, "translation": "x"} for t in texts])


def _es_ctx(**extra):
    return {"params": progress.ladder_params("espagnol", 0), "speakers": {fold("Ana")}, "lexicon": {}, **extra}


def test_words_differing_by_an_accent_are_two_glossary_entries():
    """Vérifié à l'exécution avant correction : « él » était relié à l'entrée de
    « el » et affichait « le »."""
    lines = _es_lines("El café es para él.")
    asked, known = ep.glossary_request("espagnol", lines, _es_ctx())
    assert "El" in asked and "él" in asked and not known
    entries = [{"form": w, "lemma": {"El": "el", "él": "él"}.get(w, w.lower()),
                "translation": {"El": "le", "él": "lui", "café": "café", "es": "être", "para": "pour"}[w],
                "pos": "pronom", "gender": None, "pron": "x"} for w in asked]
    kept, errors = ep.validate_glossary("espagnol", {"entries": entries}, lines, _es_ctx(), asked)
    assert errors == [] and len(kept) == len(asked)
    glossary = ep.enrich_glossary("espagnol", kept, {})
    ep.link_glossary("espagnol", lines, glossary)
    by_token = {t["text"]: glossary[t["g"]]["translation"] for t in lines[0]["tokens"] if t.get("g") is not None}
    assert by_token["El"] == "le" and by_token["él"] == "lui"


def test_a_known_word_does_not_gloss_its_accented_twin():
    lines = _es_lines("Sí, si quieres.")
    lexicon = {"si": {"form": "si", "lemma": "si", "translation": "si", "pos": "conjonction", "gender": None,
                      "pron": "si"}}
    asked, known = ep.glossary_request("espagnol", lines, _es_ctx(lexicon=lexicon))
    assert asked[0] == "Sí" and [k["form"] for k in known] == ["si"]
    ctx = _es_ctx(lexicon_forms={ep._match_key("espagnol", "si"), ep._match_key("espagnol", "quieres")})
    assert ep.estimate_new_words("espagnol", _es_lines("Sí."), ctx) == 1  # « sí » n'est pas « si »


def test_a_missing_accent_is_forgiven_only_when_unambiguous():
    lines = _es_lines("Es para él.")
    entry = {"form": "el", "lemma": "él", "translation": "lui", "pos": "pronom", "gender": None, "pron": "el"}
    kept, errors = ep.validate_glossary("espagnol", {"entries": [entry]}, lines, _es_ctx(), ["él"])
    assert [e["form"] for e in kept] == ["él"] and errors == []
    both = _es_lines("El café es para él.")
    kept, _ = ep.validate_glossary("espagnol", {"entries": [dict(entry, translation="le")]}, both, _es_ctx(), ["El", "él"])
    assert [e["form"] for e in kept] == ["El"]  # « el » exact : c'est l'article, pas le pronom


def test_an_accent_only_distractor_is_a_real_wrong_form():
    """« esta » est une forme fausse plausible de « está » : le jeu « bonne
    forme » les distingue (accents compris), le filtre ne doit pas la jeter."""
    lines = _es_lines("La sopa está caliente.", "Sí, está muy buena.")
    np = {"notes": [], "point": {"observation": "o", "explanation": "e", "examples": ["está caliente", "está muy"],
                                 "variants": [{"example": "está caliente",
                                               "distractors": ["esta caliente", "Está caliente", "es caliente"]}]}}
    cleaned, _ = ep.validate_notes_point("espagnol", np, lines)
    assert cleaned["point"]["variants"][0]["distractors"] == ["esta caliente", "es caliente"]


# ── Prononciation des langues latines : écrite par Clikoda ───────────────────

def test_the_glossary_parser_reads_the_pronunciation():
    raw = '{"entries": [["casa", "casa", "maison", "nom", "f", "/ˈkasa/"]], "expressions": []}'
    assert schema_json.parse_lang_episode_glossary(raw)["entries"][0]["pron"] == "ˈkasa"
    five = '{"entries": [["casa", "casa", "maison", "nom", "f"]]}'
    assert schema_json.parse_lang_episode_glossary(five)["entries"][0]["pron"] is None


def test_a_latin_entry_without_pronunciation_is_asked_again():
    lines = _es_lines("Hola, por favor.")
    entries = [{"form": "Hola", "lemma": "hola", "translation": "salut", "pos": "interjection", "gender": None,
                "pron": "ˈola"},
               {"form": "por", "lemma": "por", "translation": "par", "pos": "préposition", "gender": None,
                "pron": None}]
    expressions = [{"form": "por favor", "lemma": "por favor", "translation": "s'il te plaît",
                    "pos": "expression", "gender": None, "pron": None}]
    check = ep.check_glossary("espagnol", {"entries": entries, "expressions": expressions}, lines, _es_ctx(),
                              ["Hola", "por"])
    assert [e["form"] for e in check["kept"]] == ["Hola"] and check["missing"] == ["por"]
    assert any("prononciation manquante pour : por" in e for e in check["errors"])


def test_computed_pronunciations_are_not_asked_to_clikoda():
    assert ep.pron_from_clikoda("espagnol") and ep.pron_from_clikoda("allemand")
    assert not ep.pron_from_clikoda("mandarin") and not ep.pron_from_clikoda("arabe")


def test_a_known_word_without_pronunciation_is_glossed_again():
    """Inscrit au lexique avant qu'on demande la prononciation : sans elle, il ne
    deviendrait jamais une carte."""
    lines = _es_lines("Sí, si quieres.")
    lexicon = {"si": {"form": "si", "lemma": "si", "translation": "si", "pos": "conjonction", "gender": None,
                      "pron": None}}
    asked, known = ep.glossary_request("espagnol", lines, _es_ctx(lexicon=lexicon))
    assert "si" in asked and not known


# ── Genre allemand : refusé mot par mot, redemandé (§ 14, n° 5) ───────────────

def test_a_german_gender_error_is_asked_again_not_fatal(monkeypatch):
    from llm import ollama_client

    lines = ep.build_tokens("allemand", [{"speaker": "Anna", "text": "Das Haus ist groß.",
                                          "translation": "La maison est grande."}])
    ctx = {"params": progress.ladder_params("allemand", 0), "speakers": set(), "lexicon": {}}
    calls = []

    def glossary(params, ok, err, on_metrics=None, model=None):
        calls.append(params)
        gender = "f" if len(calls) == 1 else "n"  # d'abord contredit par « das », puis juste
        entries = [{"form": w, "lemma": w if w == "Haus" else w.lower(), "translation": "x",
                    "pos": "nom" if w == "Haus" else "adjectif", "gender": gender if w == "Haus" else None,
                    "pron": "x"} for w in params["words"]]
        ok({"entries": entries, "expressions": []})

    monkeypatch.setattr(ollama_client, "generate_lang_episode_glossary_async", glossary)
    log = []
    got = ep._glossary_in_chunks("allemand", lines, ctx, ["Haus", "groß"], {"language_label": "allemand"}, log, [])
    assert {e["form"]: e.get("gender") for e in got} == {"Haus": "n", "groß": None}
    assert calls[1]["words"] == ["Haus"] and "contredit" in calls[1]["rejected"]
    assert log[0]["ok"] is False and log[-1]["ok"] is True


# ── Langue d'explication anglaise (§ 14, n° 14) ───────────────────────────────

def _english(text):
    """La sortie réelle, traduite en anglais (ce que rend un prompt anglais)."""
    out = copy.deepcopy(text)
    out.update(title="The lost coffee", summary="Pablo is late again and Lucía loses patience.",
               teaser="Tomorrow, Carmen has news.")
    for i, ln in enumerate(out["lines"]):
        ln["translation"] = f"English line number {i + 1}, said with a smile."
    return out


def test_english_explanations_pass_and_french_ones_are_refused(clean):
    ctx = _ctx(clean, explain_lang="en")
    english = _english(clean["text"])
    assert ep.validate_text("espagnol", english, ctx)[1] == []
    # La traduction française d'origine est refusée, avec une raison en anglais.
    errors = ep.validate_text("espagnol", clean["text"], ctx)[1]
    assert any("translations not written in English" in e for e in errors), errors
    # Et l'inverse : une traduction anglaise n'est pas une traduction française.
    errors_fr = ep.validate_text("espagnol", english, _ctx(clean))[1]
    assert any("traductions qui ne sont pas en français" in e for e in errors_fr), errors_fr


def test_french_notes_are_dropped_for_an_english_learner(clean):
    np = copy.deepcopy(clean["notes_point"])
    for note in np["notes"]:
        note["text"] = "Ceci est une note en français, avec des mots-outils et une explication."
    np["point"]["observation"] = "What do you notice?"
    np["point"]["explanation"] = "It is used with a passing state."
    _, errors = ep.validate_notes_point("espagnol", np, _lines(clean), "en")
    assert any("valid note(s)" in e and "written in English" in e for e in errors), errors


def test_english_prompts_ask_for_english_everywhere():
    p = {"language_label": "Spanish", "episode_n": 3, "characters": [], "setting": "", "recent": [],
         "beat": "", "format_rule": prompts_en_rule(), "point_title": "Greeting", "point_constraint": "",
         "constraints": progress.prompt_constraints("espagnol", progress.ladder_params("espagnol", 0), "normal", "en"),
         "recycle": [], "script_rules": "", "lines_target": 7,
         "line_schema": '{"speaker": "first name", "text": "line", "translation": "English translation"}',
         "rejected": "2 lines instead of 6 to 8", "explain_lang": "en"}
    from llm import prompts

    text = prompts.build_lang_episode_text_prompt(p)
    assert "faithful ENGLISH" in text and "traduction" not in text
    assert "between 6 and 8 lines" in text and "REJECTED: 2 lines" in text
    french = prompts.build_lang_episode_text_prompt({**p, "explain_lang": "fr",
                                                     "constraints": "entre 6 et 8 répliques."})
    assert "traduction française fidèle" in french and "English" not in french.replace("English translation", "")


def prompts_en_rule():
    from llm.prompts import LANG_FORMAT_RULES_EN

    return LANG_FORMAT_RULES_EN["dialogue"]


def test_english_enum_values_are_mapped_to_the_canonical_ones():
    glossary = schema_json.parse_lang_episode_glossary(json.dumps({"entries": [
        ["Haus", "Haus", "house", "noun", "n"], ["gehen", "gehen", "to go", "verb", ""],
        ["Anna", "Anna", "Anna", "proper noun", ""]]}))
    assert [e["pos"] for e in glossary["entries"]] == ["nom", "verbe", "nom propre"]
    notes = schema_json.parse_lang_episode_notes_point(json.dumps({
        "notes": [{"line": 1, "anchor": "a", "kind": "grammar", "text": "t"},
                  {"line": 1, "anchor": "a", "kind": "pronunciation", "text": "t"}],
        "point": {"observation": "o", "explanation": "e", "examples": ["a"], "variants": []}}))
    assert [n["kind"] for n in notes["notes"]] == ["grammaire", "prononciation"]
    weekly = schema_json.parse_lang_weekly_analysis(json.dumps({"observations": ["ok"], "tone": "reassure"}))
    assert weekly["tone"] == "rassurer"


def test_transparent_words_compare_with_the_explanation_language():
    from services.lang_latin import faux_ami, is_transparent

    assert is_transparent("familia", "the family", "en") and is_transparent("familia", "la famille", "fr")
    assert not is_transparent("perro", "the dog", "en")
    # Les faux-amis sont écrits pour un francophone : rien pour un anglophone.
    assert faux_ami("espagnol", "embarazada", "fr") and faux_ami("espagnol", "embarazada", "en") is None


# ── Problèmes doux : la meilleure tentative est acceptée (génération fiable) ──

def _scripted(outputs):
    """Faux Clikoda qui rend `outputs` dans l'ordre ; garde chaque `rejected` reçu."""
    rejected = []

    def fn(params, ok, err, on_metrics=None, model=None):
        rejected.append(params["rejected"])
        ok(outputs[min(len(rejected) - 1, len(outputs) - 1)])

    return fn, rejected


def _soft_or_hard(result):
    if result.get("hard"):
        return result, ["2 répliques au lieu de 6 à 8", ep.SoftProblem("trop de mots nouveaux", 3.0)]
    return result, [ep.SoftProblem(f"environ {result['fresh']} mots nouveaux", weight=result["fresh"] / 10)]


def test_the_best_soft_attempt_is_accepted_after_one_retry():
    from config.settings import LANG_SOFT_PROBLEM_RETRIES

    fn, rejected = _scripted([{"fresh": 30}, {"fresh": 12}, {"fresh": 5}])
    log = []
    value = ep._attempts("text", fn, lambda rej: {"rejected": rej}, _soft_or_hard, log, [], soft_ok=True)
    assert value == {"fresh": 12}  # la moins mauvaise des deux tentatives jouées
    assert len(rejected) == 1 + LANG_SOFT_PROBLEM_RETRIES  # pas de troisième appel pour un problème doux
    assert rejected[1] == "environ 30 mots nouveaux"
    assert [bool(c.get("soft_accepted")) for c in log] == [False, True] and all(c["soft"] for c in log)


def test_a_soft_attempt_survives_a_later_hard_error():
    fn, rejected = _scripted([{"hard": True}, {"fresh": 20}, {"hard": True}])
    log = []
    assert ep._attempts("text", fn, lambda rej: {"rejected": rej}, _soft_or_hard, log, [], soft_ok=True) == {"fresh": 20}
    assert len(rejected) == 3 and log[1]["soft_accepted"] is True


def test_a_hard_error_is_still_fatal():
    fn, rejected = _scripted([{"hard": True}])
    with pytest.raises(ep.GenerationFailed):
        ep._attempts("text", fn, lambda rej: {"rejected": rej}, _soft_or_hard, [], [], soft_ok=True)
    assert len(rejected) == 3


def test_soft_problems_are_fatal_where_they_are_not_allowed():
    """Notes et glossaire restent stricts : `soft_ok` n'est donné qu'au texte."""
    fn, rejected = _scripted([{"fresh": 30}])
    with pytest.raises(ep.GenerationFailed):
        ep._attempts("notes_point", fn, lambda rej: {"rejected": rej}, _soft_or_hard, [], [])
    assert len(rejected) == 3


# ── Lemmes pollués : réparés, pas redemandés ──────────────────────────────────

def _en_lines(text):
    return ep.build_tokens("anglais", [{"speaker": "Ann", "text": text, "translation": "x"}])


def test_a_polluted_lemma_is_repaired_not_asked_again():
    """Base de dev : le glossaire anglais avait pris des traductions françaises
    pour lemmes (« démographie »), qui revenaient ensuite dans les mots à
    réemployer. Le lemme devient la forme du texte ; « restaurants » →
    « restaurant » est un vrai lemme et ne bouge pas."""
    lines = _en_lines("Demographic data and the restaurants.")
    ctx = {"params": progress.ladder_params("anglais", 0), "speakers": set(), "lexicon": {}}
    entries = [
        {"form": "Demographic", "lemma": "démographie", "translation": "démographie", "pos": "nom", "gender": None,
         "pron": "x"},
        {"form": "restaurants", "lemma": "restaurant", "translation": "restaurant", "pos": "nom", "gender": None,
         "pron": "x"},
    ]
    check = ep.check_glossary("anglais", {"entries": entries}, lines, ctx, ["Demographic", "restaurants"])
    assert check["missing"] == [] and check["errors"] == []
    assert {e["form"]: e["lemma"] for e in check["kept"]} == {"Demographic": "demographic", "restaurants": "restaurant"}
    assert check["repaired"] == [{"form": "Demographic", "was": "démographie", "lemma": "demographic"}]


def test_a_polluted_lexicon_line_is_glossed_again():
    lines = _en_lines("Demographic data.")
    lexicon = {"démographie": {"form": "demographic", "lemma": "démographie", "translation": "démographie",
                               "pos": "nom", "gender": None, "pron": "x"}}
    asked, known = ep.glossary_request("anglais", lines, {"params": progress.ladder_params("anglais", 0),
                                                          "speakers": set(), "lexicon": lexicon})
    assert "Demographic" in asked and not known
