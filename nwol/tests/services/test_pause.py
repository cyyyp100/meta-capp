# Pauses de lecture — ce qui est mesuré quand tout s'arrête (services/pause.py).
#
# Deux questions seulement : combien de temps, et est-ce que la pause suivait
# une recommandation du LLM. Plus le crédit d'attention, réservé à la pause
# conseillée par Gemma.
from config.settings import PAUSE_ATTENTION_RECOVERY, PAUSE_RECOMMENDATION_WINDOW_S
from services.pause import PauseTracker, attention_credit, summarize


def test_a_manual_pause_measures_its_duration():
    tracker = PauseTracker()
    assert tracker.start(1000.0, source="manual", page=4, attention=51.23)
    assert tracker.active
    record = tracker.stop(1420.0)
    assert not tracker.active
    assert record.duration_s == 420.0
    assert record.page == 4
    assert record.attention_at_start == 51.2
    assert record.source == "manual"
    assert record.ended_by == "resume"
    # Une durée conseillée n'a de sens que pour la carte de Gemma.
    assert record.planned_s is None


def test_a_second_start_or_stop_does_nothing():
    tracker = PauseTracker()
    assert tracker.start(10.0)
    assert not tracker.start(20.0)  # déjà en pause : le début reste le premier
    assert tracker.stop(70.0).duration_s == 60.0
    assert tracker.stop(80.0) is None


def test_without_any_recommendation_the_pause_is_spontaneous():
    tracker = PauseTracker()
    tracker.start(5000.0)
    record = tracker.stop(5100.0)
    assert record.after_recommendation is False
    assert record.recommendation_kind is None
    assert record.recommendation_delay_s is None


def test_a_manual_pause_right_after_an_intervention_follows_it():
    tracker = PauseTracker()
    tracker.note_recommendation("offer_help", now=1000.0)
    tracker.note_recommendation("suggest_pause", now=1100.0)  # seule la dernière compte
    tracker.start(1190.0, source="manual")
    record = tracker.stop(1250.0)
    assert record.after_recommendation is True
    assert record.recommendation_kind == "suggest_pause"
    assert record.recommendation_delay_s == 90.0


def test_a_recommendation_outside_the_window_is_kept_but_does_not_count():
    tracker = PauseTracker()
    tracker.note_recommendation("session_hint", now=0.0)
    tracker.start(PAUSE_RECOMMENDATION_WINDOW_S + 1.0)
    record = tracker.stop(PAUSE_RECOMMENDATION_WINDOW_S + 61.0)
    assert record.after_recommendation is False
    # Gardés bruts : la fenêtre peut être revue après coup.
    assert record.recommendation_kind == "session_hint"
    assert record.recommendation_delay_s == PAUSE_RECOMMENDATION_WINDOW_S + 1.0


def test_accepting_gemmas_card_is_following_the_recommendation():
    tracker = PauseTracker()
    tracker.start(0.0, source="suggested", planned_s=300.0)
    record = tracker.stop(150.0)
    assert record.after_recommendation is True
    assert record.planned_s == 300.0


def test_an_unknown_source_counts_as_manual():
    tracker = PauseTracker()
    tracker.start(0.0, source="hack", planned_s=300.0)
    record = tracker.stop(10.0)
    assert record.source == "manual"
    assert record.planned_s is None


def test_only_a_suggested_pause_that_was_taken_credits_attention():
    def record(source, duration, planned, ended_by="resume"):
        tracker = PauseTracker()
        tracker.start(0.0, source=source, planned_s=planned)
        return tracker.stop(duration, ended_by=ended_by)

    # Au prorata du temps pris sur la durée conseillée, plafonné à 100 %.
    assert attention_credit(record("suggested", 150.0, 300.0)) == PAUSE_ATTENTION_RECOVERY / 2
    assert attention_credit(record("suggested", 900.0, 300.0)) == PAUSE_ATTENTION_RECOVERY
    # Une pause manuelle est neutre pour les jauges.
    assert attention_credit(record("manual", 900.0, 300.0)) == 0.0
    # Une séance fermée pendant la pause : plus de lecture à mesurer.
    assert attention_credit(record("suggested", 300.0, 300.0, ended_by="disconnect")) == 0.0


def test_summarize_a_session():
    pauses = [
        {"duration_s": 120.4, "after_recommendation": True},
        {"duration_s": 60.0, "after_recommendation": False},
    ]
    assert summarize(pauses) == {"pauses": 2, "pause_s": 180, "pauses_after_recommendation": 1}
    assert summarize([]) == {"pauses": 0, "pause_s": 0, "pauses_after_recommendation": 0}
