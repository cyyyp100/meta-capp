# Difficulté, décision du prochain épisode et acquis (plan § 9 ; V7-V8).
# Tout est déterministe : aucune de ces décisions ne passe par Gemma.
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


def _add(profile, n, kind="normal", point="es.a1.saludos", params=None):
    from db import lang_episode_db as store

    return store.create_episode(profile["id"], n, kind=kind, program_point_id=point, format="dialogue",
                                ladder_step=0, params=params or {})


def test_normal_episode_takes_the_next_point(profile):
    decision = progress.next_episode_decision({**profile, "program_order": 4}, "espagnol",
                                              current=None, signals=None, episode_n=1)
    assert decision["kind"] == "normal"
    assert decision["program_point_id"] == progress.program("espagnol")[4]["id"]


def test_hard_episode_breathes_on_the_same_point_and_steps_down(profile):
    from db import lang_episode_db as store

    _add(profile, 1)
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
    _add(profile, 1, params={"easy_streak": 0})
    first = progress.next_episode_decision({**profile, "program_order": 1, "ladder_step": 1}, "espagnol",
                                           current=store.get_episode_by_n(profile["id"], 1), signals=easy,
                                           episode_n=2)
    assert first["ladder_step"] == 1 and first["params"]["easy_streak"] == 1
    _add(profile, 2, params=first["params"])
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
