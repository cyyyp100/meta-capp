# Politique d'intervention — moteur unique partagé par le lecteur web.
#
# Ces tests couvrent les garde-fous que le chemin web n'avait pas avant
# l'unification (plafond par session, cooldown par page, déclencheur `hard_page`)
# et vérifient qu'aucun seuil n'est réintroduit en dur.
import time

import pytest

from services.intervention import AssistantInterventionPolicy, _is_math_heavy
from services.session_memory import SessionMemory


def make_policy(monkeypatch, **overrides):
    """Politique branchée sur des décisions LLM immédiates et acceptées."""
    from services import intervention

    modes = ("discret", "normal", "coach")
    defaults = {"dwell": 0.0, "cooldown": 0.0, "page_cooldown": 0.0, "warmup": 0.0}
    defaults.update(overrides)
    monkeypatch.setattr(intervention, "ASSISTANT_DWELL_TRIGGER_S", dict.fromkeys(modes, defaults["dwell"]))
    monkeypatch.setattr(intervention, "ASSISTANT_GLOBAL_COOLDOWN", dict.fromkeys(modes, defaults["cooldown"]))
    monkeypatch.setattr(intervention, "ASSISTANT_PAGE_COOLDOWN", dict.fromkeys(modes, defaults["page_cooldown"]))
    monkeypatch.setattr(intervention, "ASSISTANT_WARMUP_S", dict.fromkeys(modes, defaults["warmup"]))

    memory = SessionMemory()
    memory.on_page_view(1)
    fired: list[dict] = []
    contexts: list[dict] = []
    page = {"n": 1}

    policy = AssistantInterventionPolicy(
        memory=memory,
        get_mode=lambda: "normal",
        get_gauges=lambda: {"attention": 100.0},
        get_current_page=lambda: page["n"],
        get_page_text=lambda p: "texte de page ordinaire. " * 40,
        request_decision=lambda ctx, done: (contexts.append(ctx), done({"should_intervene": True, "kind": "offer_help"}))[1],
        on_intervention=fired.append,
    )
    return policy, memory, fired, contexts, page


def test_max_interventions_per_session_is_enforced(monkeypatch):
    # Garde-fou absent du chemin web avant l'unification.
    from services import intervention

    monkeypatch.setattr(intervention, "ASSISTANT_MAX_INTERVENTIONS", 3)
    policy, memory, fired, _ctx, page = make_policy(monkeypatch)

    for n in range(2, 12):  # une page neuve à chaque tour -> un déclencheur à chaque tour
        policy.tick()
        page["n"] = n
        memory.on_page_view(n)

    assert len(fired) == 3


def test_page_cooldown_blocks_second_intervention_on_same_page(monkeypatch):
    # Cooldown PAR PAGE : absent du chemin web avant l'unification.
    policy, _memory, fired, _ctx, _page = make_policy(monkeypatch, page_cooldown=3600.0)

    policy.tick()
    assert len(fired) == 1
    # Même page, cooldown d'une heure : plus rien, même si le cooldown global est nul.
    policy._fired_reasons.clear()  # neutralise l'anti-répétition par raison
    policy.tick()
    assert len(fired) == 1


def test_hard_page_trigger_on_math_density(monkeypatch):
    # Déclencheur `hard_page` (densité mathématique) : absent du chemin web.
    # dwell=inf neutralise `long_dwell` pour isoler le signal testé ; les
    # déclencheurs « doux » demandent un temps de lecture minimal, qu'on simule.
    policy, memory, _fired, contexts, _page = make_policy(monkeypatch, dwell=float("inf"))
    memory._entered_at = time.monotonic() - 60.0
    formula = "f(x) = ∑ λ_i × ∫ √(x^2 ± σ) ∂x ≈ μ ≤ Ω / θ " * 12
    policy._get_page_text = lambda p: formula

    policy.tick()

    assert contexts and contexts[0]["trigger"] == "hard_page"


def test_discret_mode_never_intervenes(monkeypatch):
    policy, _memory, fired, _ctx, _page = make_policy(monkeypatch)
    policy._get_mode = lambda: "discret"

    for _ in range(5):
        policy.tick()

    assert fired == []


def test_busy_suspends_interventions(monkeypatch):
    # Question bloquante en cours -> silence (set_busy depuis le WebSocket).
    policy, _memory, fired, _ctx, _page = make_policy(monkeypatch)

    policy.set_busy(True)
    policy.tick()
    assert fired == []

    policy.set_busy(False)
    policy.tick()
    assert len(fired) == 1


def test_thresholds_come_from_settings_not_literals():
    """Anti-régression : la cadence doit rester pilotée par config/settings.py."""
    import inspect

    from services import intervention

    source = inspect.getsource(intervention.AssistantInterventionPolicy)
    for name in (
        "ASSISTANT_DWELL_TRIGGER_S", "ASSISTANT_GLOBAL_COOLDOWN", "ASSISTANT_PAGE_COOLDOWN",
        "ASSISTANT_WARMUP_S", "ASSISTANT_MAX_INTERVENTIONS",
    ):
        assert name in source, f"{name} n'est plus lu par la politique"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", False),
        ("Un paragraphe de prose tout à fait ordinaire. " * 10, False),
        ("∑ λ ∫ √ ± × ÷ ≈ ≤ ≥ ∂ ∇ = f(x) " * 30, True),
    ],
)
def test_is_math_heavy(text, expected):
    assert _is_math_heavy(text) is expected
