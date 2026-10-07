# Difficulté, décision du prochain épisode et acquis (plan § 9 ; V7-V8).
# Tout est déterministe : aucune de ces décisions ne passe par Clikoda.
import pytest

from config.settings import (
    LANG_DIFFICULTY_LADDER,
    LANG_LADDER_BAND,
    LANG_LADDER_STEPS_PER_TIER,
    LANG_MAX_CONSECUTIVE_RESPIRATION,
)
from services import lang_progress as progress


def test_ladder_anchors_and_interpolation():
    first = progress.ladder_params("espagnol", 0)
    anchor = LANG_DIFFICULTY_LADDER["latin"][0]
    assert first["lines"] == anchor["lines"] and first["translation"] == "toujours"
    mid = progress.ladder_params("espagnol", LANG_LADDER_STEPS_PER_TIER // 2)
    nxt = LANG_DIFFICULTY_LADDER["latin"][1]
    assert anchor["lines"][0] < mid["lines"][0] < nxt["lines"][0]
    # Qualitatif : la traduction reste celle du palier inférieur jusqu'au suivant.
    assert mid["translation"] == "toujours"
    assert progress.ladder_params("espagnol", LANG_LADDER_STEPS_PER_TIER)["translation"] == "masquable"


def test_ladder_is_bounded_and_free_length_is_kept():
    top = progress.ladder_params("espagnol", 10**6)
    assert top["step"] == progress.ladder_max_step("espagnol")
    assert top["words_per_line"] is None
    assert progress.ladder_params("espagnol", -5)["step"] == 0


def test_families_have_their_own_ladder_and_formats():
    assert progress.ladder_params("mandarin", 0)["new_words"] == LANG_DIFFICULTY_LADDER["hanzi"][0]["new_words"]
    assert "lettre" in progress.ladder_params("arabe", 0)["formats"]  # fuṣḥā : lettres dès le début
    assert progress.ladder_params("espagnol", 0)["formats"] == ["dialogue"]


def test_prompt_constraints_mention_every_bound():
    params = progress.ladder_params("espagnol", 3)
    text = progress.prompt_constraints("espagnol", params, "normal")
    assert f"entre {params['lines'][0]} et {params['lines'][1]} répliques" in text
    assert "mots nouveaux" in text
    assert "RESPIRATION" in progress.prompt_constraints("espagnol", params, "respiration")
    assert "caractères" in progress.prompt_constraints("mandarin", progress.ladder_params("mandarin", 0), "normal")


@pytest.mark.parametrize("signals,expected", [
    ({"reveal_rate": 20.0, "understood": "compris"}, "hard"),
    ({"reveal_rate": 5.0, "understood": "pas_compris"}, "hard"),
    ({"reveal_rate": 5.0, "understood": "compris", "games_rate": 0.3}, "hard"),
    ({"reveal_rate": 1.0, "understood": "compris", "games_rate": 1.0}, "easy"),
    ({"reveal_rate": 1.0, "understood": "a_peu_pres"}, "ok"),
    ({"reveal_rate": None, "understood": None}, "ok"),  # rien de mesuré n'est jamais « facile »
])
def test_classify(signals, expected):
    assert progress.classify(signals) == expected


def test_success_rate_weights_second_wave():
    assert progress.success_rate({"games_rate": None, "second_wave_rate": None}) is None
    assert progress.success_rate({"games_rate": 1.0, "second_wave_rate": 0.0}) == pytest.approx(0.5)


def test_a_point_about_a_written_form_gets_it():
    params = {"formats": ["dialogue"]}
    assert progress.choose_format("espagnol", params, {"formats_allowed": ["lettre", "sms", "dialogue"]}, [], 0) == "lettre"


def test_format_rotation_avoids_recent_formats():
    params = {"formats": ["dialogue", "sms", "lettre"]}
    point = {"formats_allowed": ["dialogue", "sms", "lettre"]}
    assert progress.choose_format("espagnol", params, point, ["dialogue", "sms"], seed=0) == "lettre"
    # Aucune forme fraîche : on retombe sur ce qui est autorisé.
    assert progress.choose_format("espagnol", {"formats": ["dialogue"]}, point, ["dialogue"], seed=3) == "dialogue"


# ── Décision sur base réelle (programme espagnol injecté) ─────────────────────

@pytest.fixture
def profile(fresh_lang_db):
    from services import lang_runs

    return lang_runs.ensure_feuilleton("espagnol")


@pytest.fixture
def fresh_lang_db(tmp_path, monkeypatch):
    import db

    db.close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "lang.db"))
    from db.schema import initialize_schema
    from services.lang_runs import on_startup

    initialize_schema()
    on_startup()
    yield
    db.close_connection()


def _add(profile, n, kind="normal", point="es.a1.saludos", params=None, step=0):
    from db import lang_episode_db as store

    return store.create_episode(profile["id"], n, kind=kind, program_point_id=point, format="dialogue",
                                ladder_step=step, params=params or {})


def test_normal_episode_takes_the_next_point(profile):
    decision = progress.next_episode_decision({**profile, "program_order": 4}, "espagnol",
                                              current=None, signals=None, episode_n=1)
    assert decision["kind"] == "normal"
    assert decision["program_point_id"] == progress.program("espagnol")[4]["id"]


def test_hard_episode_breathes_on_the_same_point_and_steps_down(profile):
    from db import lang_episode_db as store

    _add(profile, 1, step=2)
    current = store.get_episode_by_n(profile["id"], 1)
    decision = progress.next_episode_decision({**profile, "program_order": 1, "ladder_step": 2}, "espagnol",
                                              current=current, signals={"reveal_rate": 30.0}, episode_n=2)
    assert decision["kind"] == "respiration" and decision["program_point_id"] == "es.a1.saludos"
    assert decision["ladder_step"] == 1


def test_never_more_than_two_respirations_in_a_row(profile):
    from db import lang_episode_db as store

    _add(profile, 1)
    for n in range(2, 2 + LANG_MAX_CONSECUTIVE_RESPIRATION):
        _add(profile, n, kind="respiration")
    current = store.get_episode_by_n(profile["id"], 1 + LANG_MAX_CONSECUTIVE_RESPIRATION)
    decision = progress.next_episode_decision({**profile, "program_order": 1}, "espagnol", current=current,
                                              signals={"reveal_rate": 30.0},
                                              episode_n=2 + LANG_MAX_CONSECUTIVE_RESPIRATION)
    assert decision["kind"] == "normal"


def test_two_easy_episodes_in_a_row_step_up_by_one(profile):
    from db import lang_episode_db as store

    easy = {"reveal_rate": 0.5, "understood": "compris", "games_rate": 1.0}
    _add(profile, 1, params={"easy_streak": 0}, step=1)
    first = progress.next_episode_decision({**profile, "program_order": 1, "ladder_step": 1}, "espagnol",
                                           current=store.get_episode_by_n(profile["id"], 1), signals=easy,
                                           episode_n=2)
    assert first["ladder_step"] == 1 and first["params"]["easy_streak"] == 1
    _add(profile, 2, params=first["params"], step=first["ladder_step"])
    second = progress.next_episode_decision({**profile, "program_order": 2, "ladder_step": 1}, "espagnol",
                                            current=store.get_episode_by_n(profile["id"], 2), signals=easy,
                                            episode_n=3)
    assert second["ladder_step"] == 2 and second["params"]["easy_streak"] == 0


def test_step_stays_within_the_band_of_the_programme(profile):
    order = 200  # un point de niveau B2
    target = progress.target_step("espagnol", order)
    assert progress.clamp_step("espagnol", 0, order) == target - LANG_LADDER_BAND
    assert progress.clamp_step("espagnol", 999, order) == min(progress.ladder_max_step("espagnol"),
                                                              target + LANG_LADDER_BAND)


def test_level_is_the_position_in_the_programme(profile):
    assert progress.current_cefr("espagnol", 0) == "A1"
    orders = {p["cefr"]: p["order"] for p in reversed(progress.program("espagnol"))}
    assert progress.current_cefr("espagnol", orders["B1"]) == "B1"


def test_placement_start_is_the_last_consecutive_pass_minus_margin(profile):
    from config.settings import LANG_PLACEMENT_SAFETY_MARGIN

    points = progress.program("espagnol")
    passed = [points[9]["id"], points[30]["id"]]
    assert progress.placement_start_order("espagnol", passed) == 31 - LANG_PLACEMENT_SAFETY_MARGIN + 1
    assert progress.placement_start_order("espagnol", []) == 1


def test_point_introduced_never_goes_back(profile):
    from db import lang_episode_db as store
    from db.lang_db import get_lang_profile_by_id

    progress.mark_point_introduced(profile, "espagnol", "es.a1.hay", 5)
    order = store.get_point("espagnol", "es.a1.hay")["order"]
    refreshed = store.decode_profile(get_lang_profile_by_id(profile["id"]))
    assert refreshed["program_order"] == order
    progress.mark_point_introduced(refreshed, "espagnol", "es.a1.saludos", 6)
    again = store.decode_profile(get_lang_profile_by_id(profile["id"]))
    assert again["program_order"] == order
    assert store.get_level_history(profile["id"])[-1]["source"] == "progression"


def test_the_step_starts_from_the_played_episode_not_the_profile(profile):
    """Une respiration imposée par une reprise redécide un épisode déjà réservé :
    le cran du profil a déjà avancé avec lui. Elle part du cran de l'épisode
    joué, sinon elle montait d'un cran (3 → 4, base de dev)."""
    from db import lang_episode_db as store

    _add(profile, 1, step=3)
    current = store.get_episode_by_n(profile["id"], 1)
    decision = progress.next_episode_decision(
        {**profile, "program_order": 1, "ladder_step": 4, "force_respiration": 1}, "espagnol",
        current=current, signals=None, episode_n=2)
    assert decision["kind"] == "respiration" and decision["ladder_step"] == 3


def test_new_words_cap_is_shared_by_prompt_and_validator():
    from config.settings import LANG_RESPIRATION_NEW_WORDS_FACTOR

    params = progress.ladder_params("espagnol", 0)
    cap = params["new_words"][1]
    assert progress.new_words_cap(params, "normal") == cap
    assert progress.new_words_cap(params, "respiration") == max(1, round(cap * LANG_RESPIRATION_NEW_WORDS_FACTOR))
    assert f"au plus {progress.new_words_cap(params, 'respiration')} mots nouveaux" in \
        progress.prompt_constraints("espagnol", params, "respiration")


@pytest.mark.parametrize("tier,lexicon,start,expected", [
    (0, 60, 1, True),
    (1, 500, 1, True),
    (2, 500, 1, False),   # B1 : le lexique ne dit plus ce qu'il sait
    (0, 59, 1, False),    # lexique pas encore amorcé
    (0, 500, 23, False),  # placé par le test de niveau
])
def test_new_words_check_applies_only_where_the_lexicon_is_meaningful(tier, lexicon, start, expected):
    assert progress.new_words_check_applies({"tier_index": tier}, lexicon, start) is expected


def test_start_order_is_the_last_placement(profile):
    from db import lang_episode_db as store

    assert progress.start_order_of(profile["id"]) == 1  # aucun historique : parti du début
    store.add_level_history(profile["id"], "A1", 1, "placement")
    store.add_level_history(profile["id"], "A1", 23, "placement")
    store.add_level_history(profile["id"], "A2", 40, "progression")
    assert progress.start_order_of(profile["id"]) == 23


@pytest.mark.parametrize("language,form,lemma,translation,expected", [
    ("anglais", "demographic", "démographie", "démographie", True),
    ("anglais", "quantifying", "quantifier", "quantifier", True),
    ("anglais", "restaurants", "restaurant", "restaurant", False),  # un vrai lemme
    ("anglais", "local", "local", "local", False),                  # mot transparent
    ("espagnol", "hablo", "hablar", "parler", False),
    ("mandarin", "你好", "bonjour", "bonjour", True),                 # hors écriture cible
    ("mandarin", "你好", "你好", "bonjour", False),
    ("arabe", "كِتَابٌ", "livre", "livre", True),
    ("arabe", "كِتَابٌ", "كِتَاب", "livre", False),
])
def test_polluted_lemmas(language, form, lemma, translation, expected):
    assert progress.lemma_polluted(language, form, lemma, translation) is expected


def test_polluted_lexemes_are_never_recycled_nor_known(profile):
    from db import lang_episode_db as store

    store.insert_lexeme(profile["id"], {"form": "ciudad", "lemma": "ciudad", "translation": "ville"}, 1)
    store.insert_lexeme(profile["id"], {"form": "demografía", "lemma": "démographie",
                                        "translation": "démographie"}, 1)
    assert progress.recycle_words(profile["id"], "espagnol", 10) == ["ciudad"]
    assert progress.known_words_for_prompt(profile["id"], "espagnol") == ["ciudad"]


def test_known_words_put_acquired_lemmas_first_and_fit_the_budget(profile):
    from config.settings import LANG_KNOWN_WORDS_PROMPT_TOKENS
    from db import lang_episode_db as store
    from llm.prompts import estimate_prompt_tokens

    for i in range(400):
        store.insert_lexeme(profile["id"], {"form": f"palabra{i}", "lemma": f"palabra{i}", "translation": "x"}, 1)
    acquired = store.get_lexeme(profile["id"], "palabra399")
    store.update_lexeme(acquired["id"], acquired_at="2026-09-01 10:00:00")
    known = progress.known_words_for_prompt(profile["id"], "espagnol", exclude=["palabra0"])
    assert known[0] == "palabra399" and "palabra0" not in known
    assert 0 < len(known) < 400
    assert estimate_prompt_tokens(", ".join(known)) <= LANG_KNOWN_WORDS_PROMPT_TOKENS


def test_the_end_of_the_programme_is_noted(profile):
    last = progress.program("espagnol")[-1]["order"]
    assert not progress.program_ended("espagnol", last - 1)
    assert progress.program_ended("espagnol", last)
    decision = progress.next_episode_decision({**profile, "program_order": last}, "espagnol",
                                              current=None, signals=None, episode_n=1)
    assert decision["params"]["program_end"] is True


@pytest.mark.parametrize("signals,expected", [
    # « Tout traduire » en A1 : une aide prévue, jamais un échec — mais pas « facile » non plus.
    ({"translated_share": 1.0, "tier_index": 0, "reveal_rate": None, "understood": "compris"}, "ok"),
    ({"translated_share": 1.0, "tier_index": 1, "reveal_rate": 1.0, "understood": "compris"}, "ok"),
    # 90 % traduit en B1 : le texte était trop dur.
    ({"translated_share": 0.9, "tier_index": 2, "reveal_rate": 1.0, "understood": "compris"}, "hard"),
    ({"translated_share": 0.6, "tier_index": 3, "reveal_rate": 1.0, "understood": "compris"}, "hard"),
    # « Facile » demande d'être resté sous le seuil du palier.
    ({"translated_share": 0.3, "tier_index": 0, "reveal_rate": 1.0, "understood": "compris"}, "easy"),
    ({"translated_share": 0.4, "tier_index": 2, "reveal_rate": 1.0, "understood": "compris"}, "ok"),
    # D'anciens signaux (sans part traduite) se classent comme avant.
    ({"reveal_rate": 1.0, "understood": "compris"}, "easy"),
])
def test_translated_share_is_judged_by_tier(signals, expected):
    assert progress.classify(signals) == expected


def test_a_known_false_positive_of_the_lemma_repair_is_documented():
    """Un infinitif espagnol qui s'écrit comme l'infinitif français ressemble à
    une traduction prise pour lemme (architecture/18 § 14, rév. 4) : la règle le
    répare en sa forme. Ce test fixe ce comportement assumé."""
    assert progress.lemma_polluted("espagnol", "viene", "venir", "venir") is True
    assert progress.lemma_polluted("espagnol", "venir", "venir", "venir") is False
