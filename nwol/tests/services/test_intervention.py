# Politique d'intervention — moteur unique partagé par le lecteur web.
#
# Ces tests couvrent les garde-fous que le chemin web n'avait pas avant
# l'unification (plafond par session, cooldown par page, déclencheur `hard_page`)
# et vérifient qu'aucun seuil n'est réintroduit en dur.
import time

import pytest

from services.intervention import (
    AssistantInterventionPolicy,
    _is_math_heavy,
    detect_answer_fatigue,
)
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
    policy.start_reading()
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


def test_first_intervention_fires_on_a_freshly_booted_machine(monkeypatch):
    # Régression CI : `time.monotonic()` a une origine ARBITRAIRE (uptime de la
    # machine). Sur un runner fraîchement démarré il vaut quelques centaines de
    # secondes seulement ; une sentinelle « jamais encore intervenu » à 0.0
    # rendait donc TOUS les cooldowns actifs et la toute première intervention
    # de la session ne partait jamais. Sur un poste allumé depuis des heures le
    # même code passait — d'où un test vert en local et rouge en CI.
    monkeypatch.setattr(time, "monotonic", lambda: 12.0)
    policy, _memory, fired, _ctx, _page = make_policy(monkeypatch, page_cooldown=3600.0, cooldown=240.0)

    policy.tick()

    assert len(fired) == 1


def test_silent_until_reading_starts(monkeypatch):
    # Le sas d'entrée (mise en condition + cartes de révision) n'est pas de la
    # lecture : tant que le lecteur ne l'a pas franchi, aucune intervention, même
    # warm-up à zéro.
    policy, _memory, fired, _ctx, _page = make_policy(monkeypatch)
    policy._opened_at = None  # socket ouvert, sas pas encore franchi

    for _ in range(5):
        policy.tick()
    assert fired == []

    policy.start_reading()
    policy.tick()
    assert len(fired) == 1


def test_warmup_counts_from_reading_start_not_from_opening(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])
    policy, _memory, fired, _ctx, _page = make_policy(monkeypatch, warmup=240.0)
    policy._opened_at = None  # ouverture du document à t=1000

    clock["t"] = 1300.0  # cinq minutes dans le sas : plus que le warm-up entier
    policy.start_reading()
    policy.tick()
    assert fired == []  # le warm-up part de l'entrée dans la lecture

    clock["t"] = 1300.0 + 240.0
    policy.tick()
    assert len(fired) == 1

    # Un second signal d'entrée ne relance pas le silence en pleine lecture.
    policy.start_reading()
    assert policy._opened_at == 1300.0


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


# ── Fatigue : les réponses rétrécissent ─────────────────────────────────────
# Le signal « il n'apprend plus ». La longueur des réponses était calculée à
# chaque évaluation puis jetée : rien n'en gardait la SÉRIE, donc rien ne
# pouvait voir une production qui s'effondre.


@pytest.mark.parametrize(
    "lengths,expected",
    [
        ([], False),
        ([200, 100], False),        # fenêtre incomplète
        ([200, 120, 40], True),
        ([200, 40, 120], False),    # ça remonte : ce n'est pas une chute
        ([200, 120, 119], False),   # décroît à peine
        ([30, 20, 10], False),      # a toujours écrit court : rien à conclure
    ],
)
def test_detect_answer_fatigue(lengths, expected):
    assert detect_answer_fatigue(lengths) is expected


def test_answer_fatigue_fires_then_waits_a_whole_new_window(monkeypatch):
    # dwell=inf neutralise `long_dwell` : on isole le signal testé.
    policy, memory, _fired, contexts, _page = make_policy(monkeypatch, dwell=float("inf"))

    memory.on_answer(1, "correct", chars=180)
    memory.on_answer(1, "partial", chars=90)
    policy.tick()
    assert contexts == []  # deux réponses seulement : la fenêtre n'est pas pleine

    memory.on_answer(1, "partial", chars=40)
    policy.tick()
    assert contexts[-1]["trigger"] == "answer_fatigue"
    # Le prompt reçoit ce qui a été observé, pas un vague « tu sembles fatigué ».
    assert contexts[-1]["answer_lengths"] == [180, 90, 40]

    # Une réponse de plus ne relance pas le signal : il faut une fenêtre ENTIÈRE
    # de nouvelles réponses. Sans ce réarmement, la fatigue repartirait à chaque
    # tick — l'anti-répétition par (page, raison) ne la couvre pas, puisqu'elle
    # parle de la session et non de la page.
    memory.on_answer(1, "partial", chars=25)
    policy.tick()
    assert len(contexts) == 1


def test_fatigue_outranks_the_page_signals(monkeypatch):
    # Quand la production s'effondre, la bonne réaction est une pause — pas une
    # question de plus sur la page où l'étudiant traîne depuis dix minutes.
    policy, memory, _fired, contexts, _page = make_policy(monkeypatch)
    memory._entered_at = time.monotonic() - 600.0
    for chars in (200, 110, 45):
        memory.on_answer(1, "partial", chars=chars)

    policy.tick()

    assert contexts[-1]["trigger"] == "answer_fatigue"


# ── Formules à venir ────────────────────────────────────────────────────────
# `hard_page` ne regardait que la page affichée, et arrivait derrière le
# plancher de dwell : il ne pouvait que constater un blocage déjà installé.


def _formula_page() -> str:
    return "f(x) = ∑ λ_i × ∫ √(x^2 ± σ) ∂x ≈ μ ≤ Ω / θ " * 12


def test_math_ahead_warns_before_reaching_the_formulas(monkeypatch):
    policy, memory, _fired, contexts, _page = make_policy(monkeypatch, dwell=float("inf"))
    memory._entered_at = time.monotonic() - 60.0
    prose = "un paragraphe de prose parfaitement ordinaire. " * 40
    policy._get_page_text = lambda p: _formula_page() if p == 2 else prose

    policy.tick()

    assert contexts[-1]["trigger"] == "math_ahead"
    # La page suivante voyage à part : `page_text` reste la page AFFICHÉE, seule
    # dans laquelle les surlignages savent retrouver une citation.
    assert contexts[-1]["page_text"].startswith("un paragraphe de prose")
    assert "∑" in contexts[-1]["next_page_text"]


def test_math_ahead_stays_silent_once_the_formulas_are_on_screen(monkeypatch):
    # Annoncer des formules à quelqu'un qui en lit déjà n'apprend rien : ce
    # cas-là, c'est `hard_page`.
    policy, memory, _fired, contexts, _page = make_policy(monkeypatch, dwell=float("inf"))
    memory._entered_at = time.monotonic() - 60.0
    policy._get_page_text = lambda p: _formula_page()

    policy.tick()

    assert contexts[-1]["trigger"] == "hard_page"


def test_stagnant_since_resets_on_interaction() -> None:
    """Un geste (scroll, souris, clavier) remet l'immobilité à zéro sans changer
    la page : lire une deuxième colonne n'est pas du décrochage."""
    memory = SessionMemory()
    memory.on_page_view(3, now=1000.0)
    assert memory.stagnant_since(1200.0) == 200.0
    assert memory.current_dwell(1200.0) == 200.0
    memory.on_interaction(now=1190.0)
    assert memory.stagnant_since(1200.0) == 10.0
    # Le dwell, lui, ne bouge pas : `long_dwell` continue de lire le temps sur la page.
    assert memory.current_dwell(1200.0) == 200.0
    # Jamais plus que le dwell (interaction antérieure à l'entrée sur la page).
    memory.on_page_view(4, now=1300.0)
    assert memory.stagnant_since(1305.0) == 5.0
