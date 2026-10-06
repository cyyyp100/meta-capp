# Tests du cœur métacognitif (trou 🔴 de l'audit : aucun test direct).
import pytest

from db.metacog import CRITERIA


# ── Jauges (pur, sans DB) ────────────────────────────────────────────────────

def test_initialize_session_gauges_inherits_profile():
    from metacog.gauges import SESSION_INHERITANCE_FACTOR, initialize_session_gauges

    values = initialize_session_gauges({"attention": 80.0})
    assert values["attention"] == pytest.approx(80.0 * SESSION_INHERITANCE_FACTOR)
    # Critère absent du profil -> base 50 héritée.
    assert values["curiosity"] == pytest.approx(50.0 * SESSION_INHERITANCE_FACTOR)
    assert set(values) == set(CRITERIA)


def test_gauges_always_clamped_0_100():
    from metacog.gauges import GaugeState

    g = GaugeState("retention", 99.0)
    for _ in range(10):
        g.update(signal=2.0, verdict="correct")
    assert g.value == 100.0
    for _ in range(50):
        g.update(signal=-2.0, verdict="incorrect")
    assert g.value == 0.0


def test_update_from_evaluation_moves_targeted_gauge_more():
    from metacog.gauges import make_gauges, update_gauges_from_evaluation

    # Question de curiosité : la jauge curiosity doit bouger plus que retention.
    gauges = make_gauges({c: 50.0 for c in CRITERIA})
    before = {k: g.value for k, g in gauges.items()}
    update_gauges_from_evaluation(
        gauges,
        {
            "verdict": "correct",
            "question_type": "curiosity",
            "metacog_signals": {c: 1.0 for c in CRITERIA},
        },
    )
    curiosity_delta = gauges["curiosity"].value - before["curiosity"]
    retention_delta = gauges["retention"].value - before["retention"]
    assert curiosity_delta > retention_delta > 0


def test_update_from_evaluation_tolerates_garbage_signals():
    from metacog.gauges import make_gauges, update_gauges_from_evaluation

    gauges = make_gauges()
    # Signaux non numériques, types inattendus -> pas d'exception, valeurs clampées.
    values = update_gauges_from_evaluation(
        gauges,
        {
            "verdict": "partial",
            "metacog_signals": {"attention": "beaucoup", "curiosity": None},
            "curiosity_signals": "pas-un-dict",
            "creativity_signals": {"depth_of_reflection": "??"},
        },
    )
    assert all(0.0 <= v <= 100.0 for v in values.values())


def test_attention_penalizes_slow_and_wrong_answers():
    from metacog.gauges import GaugeState

    slow = GaugeState("attention", 50.0)
    slow.update(signal=0.0, verdict="incorrect", response_time_ms=30000, consecutive_incorrect=3)
    fast = GaugeState("attention", 50.0)
    fast.update(signal=0.0, verdict="correct", response_time_ms=2000)
    assert slow.value < 50.0 < fast.value


def test_profile_update_blends_session_and_profile():
    from metacog.gauges import update_profile_gauges_from_session

    updates = update_profile_gauges_from_session(
        {c: 40.0 for c in CRITERIA}, {c: 90.0 for c in CRITERIA}, session_weight=0.1
    )
    for criterion in CRITERIA:
        assert updates[criterion] == pytest.approx(45.0)  # 40*0.9 + 90*0.1


# ── Profil permanent (avec DB isolée) ────────────────────────────────────────

@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    import db

    db.close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nwol.db"))
    from db.schema import initialize_schema

    initialize_schema()
    yield
    db.close_connection()


def test_compute_alpha_decreases_with_experience():
    from metacog.profile import ALPHA_MIN, compute_alpha

    assert compute_alpha(0) == 1.0
    assert compute_alpha(5) == pytest.approx(0.5)
    assert compute_alpha(10_000) == ALPHA_MIN


def test_update_profile_persists_and_increments_sessions(fresh_db):
    from db.user import DEFAULT_USER_ID
    from metacog.profile import update_profile

    profile = update_profile(DEFAULT_USER_ID, {c: 100.0 for c in CRITERIA}, session_id=None)
    assert profile["sessions_count"] == 1
    # Première session (alpha=1.0) : le profil adopte le score de session.
    assert float(profile["attention"]) == pytest.approx(100.0)

    profile = update_profile(DEFAULT_USER_ID, {c: 0.0 for c in CRITERIA}, session_id=None)
    assert profile["sessions_count"] == 2
    # Les sessions suivantes pèsent moins : la chute est amortie.
    assert 0.0 < float(profile["attention"]) < 100.0


# ── Modèle du verdict (quiz, langues : mesures sans signal du LLM) ──────────

def test_a_verdict_pulls_only_the_targeted_performance_gauges():
    """Un QCM vise rétention + attention : elles parcourent GAUGE_VERDICT_WEIGHT
    du chemin vers la cible du verdict. Les autres ne bougent pas — être juste ne
    dit rien de la curiosité ni de la créativité."""
    from config.settings import GAUGE_VERDICT_TARGETS, GAUGE_VERDICT_WEIGHT
    from metacog.gauges import make_gauges, update_gauges_from_verdict

    gauges = make_gauges({c: 50.0 for c in CRITERIA})  # amorce : 40 partout
    values = update_gauges_from_verdict(gauges, "correct", ("retention", "attention"))
    expected = 40.0 + GAUGE_VERDICT_WEIGHT * (GAUGE_VERDICT_TARGETS["correct"] - 40.0)
    assert values["retention"] == pytest.approx(expected)
    assert values["attention"] == pytest.approx(expected)
    for untouched in ("context_comprehension", "curiosity", "creativity", "meta_cognition"):
        assert values[untouched] == pytest.approx(40.0)


def test_a_verdict_never_moves_curiosity_creativity_or_metacognition():
    """Même visées par le type de question (estimation -> curiosité), ces trois
    jauges restent intactes : un verdict n'informe que la performance."""
    from metacog.gauges import make_gauges, update_gauges_from_verdict

    gauges = make_gauges({c: 50.0 for c in CRITERIA})
    values = update_gauges_from_verdict(
        gauges, "correct", ("curiosity", "creativity", "meta_cognition", "context_comprehension"),
    )
    assert values["context_comprehension"] > 40.0
    assert values["curiosity"] == values["creativity"] == values["meta_cognition"] == pytest.approx(40.0)


def test_a_missing_verdict_moves_nothing():
    """Un signal absent n'est jamais un succès (P-5) — ni un échec."""
    from metacog.gauges import make_gauges, snapshot, update_gauges_from_verdict

    gauges = make_gauges({c: 50.0 for c in CRITERIA})
    before = snapshot(gauges)
    assert update_gauges_from_verdict(gauges, None, ("retention",)) == before
    assert update_gauges_from_verdict(gauges, "peut-être", ("retention",)) == before


def test_a_verdict_session_converges_on_its_success_rate_whatever_its_seed():
    """Huit bonnes réponses portent la jauge bien au-dessus du profil, huit
    mauvaises bien en dessous : la courbe dit la séance, pas son amorce."""
    from metacog.gauges import make_gauges, update_gauges_from_verdict

    good = make_gauges({"retention": 50.0})
    bad = make_gauges({"retention": 50.0})
    for _ in range(8):
        update_gauges_from_verdict(good, "correct", ("retention",))
        update_gauges_from_verdict(bad, "incorrect", ("retention",))
    assert good["retention"].value > 80.0
    assert bad["retention"].value < 25.0


def test_slow_answers_and_error_streaks_cost_attention_even_untargeted():
    """Lenteur et série d'erreurs sont des observations : elles coûtent de
    l'attention quel que soit le type, comme dans le lecteur."""
    from metacog.gauges import make_gauges, update_gauges_from_verdict

    gauges = make_gauges({c: 50.0 for c in CRITERIA})
    values = update_gauges_from_verdict(
        gauges, "incorrect", ("retention",), response_time_ms=24000, consecutive_incorrect=3,
    )
    # 6 points de lenteur (plafond) + 2 de série d'erreurs.
    assert values["attention"] == pytest.approx(40.0 - 6.0 - 2.0)


def test_a_continuous_score_sits_on_the_verdict_scale():
    from config.settings import GAUGE_VERDICT_TARGETS
    from metacog.gauges import score_target

    assert score_target(1.0) == pytest.approx(GAUGE_VERDICT_TARGETS["correct"])
    assert score_target(0.5) == pytest.approx(GAUGE_VERDICT_TARGETS["partial"])
    assert score_target(0.0) == pytest.approx(GAUGE_VERDICT_TARGETS["incorrect"])
    assert GAUGE_VERDICT_TARGETS["partial"] < score_target(0.75) < GAUGE_VERDICT_TARGETS["correct"]


def test_replay_starts_on_the_seed_and_adds_one_point_per_measure():
    """La courbe d'une séance de pratique : l'amorce, puis un point par mesure,
    sur l'axe que la mesure donne. Une mesure sans verdict n'en est pas une."""
    from config.settings import GAUGE_VERDICT_TARGETS as TARGETS
    from config.settings import GAUGE_VERDICT_WEIGHT as W
    from metacog.gauges import replay

    seed = {c: 40.0 for c in CRITERIA}
    points = replay(seed, [
        {"t": 1, "verdict": "correct", "targets": ("retention",)},
        {"t": 2, "verdict": None, "targets": ("retention",)},
        {"t": 3, "verdict": "incorrect", "targets": ("retention",)},
    ])
    assert [t for t, _ in points] == [0.0, 1.0, 3.0]
    assert points[0][1] == seed
    after_good = 40.0 + W * (TARGETS["correct"] - 40.0)
    assert points[1][1]["retention"] == pytest.approx(after_good)
    assert points[2][1]["retention"] == pytest.approx(after_good + W * (TARGETS["incorrect"] - after_good))
    # Rejouer les mêmes mesures donne la même courbe.
    assert replay(seed, [{"t": 1, "verdict": "correct", "targets": ("retention",)}]) == points[:2]


def test_replay_follows_the_reader_model_when_the_llm_graded_the_answer():
    """Une réponse rédigée corrigée par le LLM porte ses signaux : elle suit le
    modèle du lecteur (signal amplifié sur la jauge visée par le type)."""
    from metacog.gauges import replay

    seed = {c: 40.0 for c in CRITERIA}
    (_, _), (_, after) = replay(seed, [{
        "t": 1, "verdict": "correct", "question_type": "curiosity", "targets": ("curiosity",),
        "evaluation": {"metacog_signals": {"curiosity": 1.0}},
    }])
    assert after["curiosity"] > 40.0 + 8.0  # signal × 8 × 1,5 + bonus de verdict
    # Ce que l'évaluation n'informe pas reste à l'amorce : ni bonus de verdict
    # sur la créativité, ni dérive de la métacognition (elle se note au sas).
    assert after["creativity"] == pytest.approx(40.0)
    assert after["meta_cognition"] == pytest.approx(40.0)
    assert after["attention"] != pytest.approx(40.0)  # chaque réponse observe l'attention


def test_replay_counts_the_measures_that_informed_each_criterion():
    """Le poids de chaque critère à la finalisation : quatre QCM éprouvent la
    rétention quatre fois ; une réponse rédigée relève la curiosité une fois."""
    from metacog.gauges import informed_counts

    seed = {c: 40.0 for c in CRITERIA}
    counts = informed_counts(seed, [
        *({"t": i, "verdict": "correct", "targets": ("retention", "attention")} for i in range(1, 5)),
        {"t": 5, "verdict": "partial", "question_type": "open", "targets": (),
         "evaluation": {"metacog_signals": {"curiosity": 0.5, "creativity": 0.0}}},
    ])
    assert counts["retention"] == 4
    assert counts["attention"] == 5
    assert counts["curiosity"] == 1
    assert "meta_cognition" not in counts


def test_update_profile_weighs_each_criterion_by_its_own_confidence(fresh_db):
    """Une séance de pratique pondère critère par critère : un critère absent
    des poids n'a rien mesuré et ne bouge pas, même si sa jauge a bougé."""
    from db.user import DEFAULT_USER_ID
    from metacog.profile import update_profile

    update_profile(DEFAULT_USER_ID, {c: 50.0 for c in CRITERIA}, session_id=None)  # sessions_count = 1
    profile = update_profile(
        DEFAULT_USER_ID,
        {"retention": 90.0, "curiosity": 90.0, "creativity": 90.0},
        session_id=None,
        confidence={"retention": 1.0, "curiosity": 0.25},
    )
    retention_move = float(profile["retention"]) - 50.0
    curiosity_move = float(profile["curiosity"]) - 50.0
    assert retention_move > 0 and curiosity_move > 0
    assert curiosity_move == pytest.approx(retention_move / 4)
    assert float(profile["creativity"]) == pytest.approx(50.0)


def test_web_and_shared_engine_apply_the_same_alpha(fresh_db):
    """Anti-régression § A4 : un seul moteur d'apprentissage du profil.

    `services.session.nudge_metacog_profile` (chemin web) doit produire exactement
    le même profil que `metacog.profile.update_profile` (moteur partagé). Avant
    l'unification, le web appliquait un alpha fixe de 0,1 : sur une première
    session l'écart était d'un facteur 10."""
    from db.user import DEFAULT_USER_ID
    from services.session import nudge_metacog_profile

    gauges = {c: 90.0 for c in CRITERIA}
    values = nudge_metacog_profile(
        DEFAULT_USER_ID, score=90.0, responses=[], metrics={},
        session_id=None, session_gauges=gauges,
    )
    # Première session -> alpha = 1.0 : le profil adopte les jauges de session.
    assert values["attention"] == pytest.approx(90.0)
    assert values["creativity"] == pytest.approx(90.0)
    assert set(values) == set(CRITERIA)


def test_fallback_moves_only_evidence_backed_criteria(fresh_db):
    # Sans canal temps réel, le taux de réussite n'informe que 3 critères :
    # les autres restent inchangés plutôt que d'être déduits d'un score.
    from db.metacog import ensure_profile
    from db.user import DEFAULT_USER_ID
    from services.session import nudge_metacog_profile

    before = dict(ensure_profile(DEFAULT_USER_ID))
    values = nudge_metacog_profile(
        DEFAULT_USER_ID, score=100.0, responses=[], metrics={}, session_id=None,
    )
    assert set(values) == {"attention", "context_comprehension", "retention"}
    after = ensure_profile(DEFAULT_USER_ID)
    for untouched in ("curiosity", "creativity", "meta_cognition"):
        assert float(after[untouched]) == pytest.approx(float(before[untouched]))


# ── Attention : les signaux comportementaux (§ constats 1 et 2) ──────────────

def test_attention_falls_on_slow_answer_and_error_streak():
    """Le modèle d'attention attendait `response_time_ms` et la série d'erreurs.

    Personne ne les lui passait : deux de ses quatre termes étaient inertes, et
    `attention` n'était qu'un dérivé de la performance."""
    from metacog.gauges import make_gauges, update_gauges_from_evaluation

    evaluation = {"verdict": "partial", "metacog_signals": {c: 0.0 for c in CRITERIA}}

    quick = make_gauges({c: 60.0 for c in CRITERIA})
    update_gauges_from_evaluation(quick, dict(evaluation), response_time_ms=3000)

    slow = make_gauges({c: 60.0 for c in CRITERIA})
    update_gauges_from_evaluation(slow, dict(evaluation), response_time_ms=30000)
    assert slow["attention"].value < quick["attention"].value

    streak = make_gauges({c: 60.0 for c in CRITERIA})
    update_gauges_from_evaluation(
        streak, {"verdict": "incorrect", "metacog_signals": {}}, consecutive_incorrect=4
    )
    single = make_gauges({c: 60.0 for c in CRITERIA})
    update_gauges_from_evaluation(
        single, {"verdict": "incorrect", "metacog_signals": {}}, consecutive_incorrect=1
    )
    assert streak["attention"].value < single["attention"].value


def test_reading_attention_delta_reads_behaviour_not_performance():
    from metacog.gauges import reading_attention_delta

    # Fenêtre masquée : l'étudiant n'est pas là.
    assert reading_attention_delta(60.0, 10.0, 0, away=True) < 0
    # Page immobile bien au-delà de la grâce : décrochage probable.
    assert reading_attention_delta(60.0, 600.0, 0, away=False) < 0
    # Lecture lente mais dans la grâce : on ne sanctionne pas.
    assert reading_attention_delta(60.0, 30.0, 0, away=False) == 0.0
    # La lecture avance : petit crédit.
    assert reading_attention_delta(60.0, 600.0, 3, away=False) > 0


def test_live_gauges_passive_drift_stops_at_the_floor(fresh_db):
    """La seule dérive passive fait descendre l'attention, jamais la vider."""
    from config.settings import ATTENTION_PASSIVE_FLOOR
    from services.session import LiveGauges

    gauges = LiveGauges()
    for _ in range(400):  # ~33 minutes de fenêtre masquée
        gauges.apply_reading_behaviour(
            elapsed_s=5.0, stagnant_s=600.0, pages_progressed=0, away=True
        )
    assert gauges.snapshot()["attention"] == pytest.approx(ATTENTION_PASSIVE_FLOOR)
    # Le crédit de progression, lui, s'applique toujours.
    gauges.apply_reading_behaviour(
        elapsed_s=5.0, stagnant_s=0.0, pages_progressed=2, away=False
    )
    assert gauges.snapshot()["attention"] > ATTENTION_PASSIVE_FLOOR


# ── Confiance : le profil ne bouge qu'à hauteur de ce qui est mesuré ─────────

def test_confidence_scales_the_session_weight():
    from metacog.profile import FULL_CONFIDENCE_MEASURES, compute_confidence

    assert compute_confidence(0) == 0.0
    assert compute_confidence(None) == 1.0  # l'appelant affirme ses jauges
    assert compute_confidence(FULL_CONFIDENCE_MEASURES) == 1.0
    assert compute_confidence(FULL_CONFIDENCE_MEASURES * 10) == 1.0
    assert 0.0 < compute_confidence(1) < 1.0


def test_short_session_moves_the_profile_less_than_a_full_one(fresh_db):
    from db.user import DEFAULT_USER_ID
    from metacog.profile import FULL_CONFIDENCE_MEASURES, update_profile

    gauges = {c: 100.0 for c in CRITERIA}
    partial = update_profile(DEFAULT_USER_ID, gauges, None, confidence=0.25)
    partial_value = float(partial["attention"])

    full = update_profile(DEFAULT_USER_ID, gauges, None, confidence=1.0)
    assert float(full["attention"]) > partial_value
    assert FULL_CONFIDENCE_MEASURES >= 1


def test_a_quiz_weighs_less_than_a_language_session_in_the_profile(fresh_db):
    """Une lecture et une séance de langue font apprendre, un quiz vérifie : à
    mesures égales, un quiz déplace le profil d'autant moins que son poids de
    catégorie le dit (`PROFILE_SESSION_KIND_WEIGHT`, en plus de l'α adaptatif et
    de la confiance de la séance)."""
    from config.settings import PROFILE_SESSION_KIND_WEIGHT as WEIGHT
    from db.metacog import get_history
    from db.user import DEFAULT_USER_ID
    from metacog.profile import compute_alpha, compute_confidence
    from services import practice
    from services.session import nudge_metacog_profile

    assert WEIGHT["quiz"] < WEIGHT["lang"] and WEIGHT["quiz"] < WEIGHT["reading"]
    measures = [{"t": i, "verdict": "correct", "targets": ("retention",)} for i in range(1, 5)]
    for sessions_before, kind in enumerate(("quiz", "lang")):
        sid = practice.start(kind, DEFAULT_USER_ID)
        practice.close(sid, measures, 60)
        nudge_metacog_profile(DEFAULT_USER_ID, 0.0, [], {}, practice_session_id=sid, measures=len(measures))
        row = next(
            r for r in get_history()
            if r["practice_session_id"] == sid and r["criterion"] == "retention"
        )
        expected = compute_alpha(sessions_before) * compute_confidence(len(measures)) * WEIGHT[kind]
        assert row["alpha"] == pytest.approx(expected)
