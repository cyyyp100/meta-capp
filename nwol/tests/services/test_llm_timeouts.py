"""Budget temps des générations LLM (§ A2).

Avant cette correction, chaque appelant écrivait son timeout à la main au-dessus
d'un timeout socket fixe de 60 s : cinq d'entre eux (90 à 150 s) attendaient une
échéance que la socket ne leur laissait jamais atteindre, et un timeout
n'annulait rien — le worker unique continuait de traiter un travail dont plus
personne ne voulait le résultat.
"""
from __future__ import annotations

import threading
import time

import pytest

from config import settings
from config.settings import (
    LLM_MODELS,
    ModelProfile,
    OLLAMA_TASK_OPTIONS,
    OLLAMA_TIMEOUT,
    OLLAMA_TIMEOUT_MAX,
    OLLAMA_WALL_TIMEOUT_MAX,
    task_options,
    task_timeout_s,
    task_wall_timeout_s,
)
from llm import ollama_client
from services.llm_bridge import run_llm_sync


# Tâche lourde de référence (3000 tokens à écrire). Synthétique : ces tests
# portent sur la forme du calcul de budget, pas sur une tâche de production
# susceptible de disparaître (l'ancien curriculum de langue, retiré).
HEAVY_TASK = "tache_lourde"


@pytest.fixture(autouse=True)
def heavy_task(monkeypatch):
    monkeypatch.setitem(OLLAMA_TASK_OPTIONS, HEAVY_TASK, {"num_ctx": 4096, "num_predict": 3000, "temperature": 0.1})


def _wait_worker_idle(timeout: float = 10.0) -> None:
    """La file LLM est PARTAGÉE par toute la suite : un test précédent peut y
    avoir laissé des tâches de fond. On attend qu'elle soit vide avant de
    raisonner sur ce que fait le worker."""
    deadline = time.monotonic() + timeout
    while ollama_client._LLM_QUEUE.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not ollama_client._LLM_QUEUE.unfinished_tasks, "worker LLM encore occupé par un test précédent"


def test_budget_grows_with_the_token_budget_of_the_task():
    """Une tâche qui demande plus de tokens obtient plus de temps."""
    court = task_timeout_s("document_digest")        # num_predict = 260
    long = task_timeout_s(HEAVY_TASK)               # num_predict = 3000
    assert court == OLLAMA_TIMEOUT                   # plancher
    assert long > court
    assert long <= OLLAMA_TIMEOUT_MAX                # plafond dur


def test_budget_is_bounded_and_defined_for_every_declared_task():
    for task in OLLAMA_TASK_OPTIONS:
        assert OLLAMA_TIMEOUT <= task_timeout_s(task) <= OLLAMA_TIMEOUT_MAX
    # Tâche inconnue : plancher, jamais d'exception.
    assert task_timeout_s("tache_inexistante") == OLLAMA_TIMEOUT


def test_every_model_keeps_every_task_inside_its_own_bounds():
    """Les budgets suivent le modèle choisi. Le plancher ne bouge pas (c'est le
    temps en dessous duquel on n'attend pas) ; le plafond, lui, s'étire du coût
    du modèle — `OLLAMA_TIMEOUT_MAX` ne borne plus que la machine de référence
    sur le modèle de référence."""
    for name, profile in LLM_MODELS.items():
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(settings, "_active_profile", lambda profile=profile: profile)
            stretch = max(settings._model_factors(profile))
            for task in OLLAMA_TASK_OPTIONS:
                budget = task_timeout_s(task)
                assert OLLAMA_TIMEOUT <= budget <= OLLAMA_TIMEOUT_MAX * stretch, (name, task)
                assert task_wall_timeout_s(task) <= OLLAMA_WALL_TIMEOUT_MAX * stretch, (name, task)


def test_a_slower_model_gets_more_time_for_the_same_task():
    """`gemma4:31b` écrit trois fois moins vite que `gemma4:e2b` : une tâche qui
    demande des centaines de tokens ne peut pas tenir dans le même budget."""
    budgets = {}
    for name in ("gemma4:e2b", "gemma4:31b"):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(settings, "_active_profile", lambda name=name: LLM_MODELS[name])
            budgets[name] = {task: task_timeout_s(task) for task in OLLAMA_TASK_OPTIONS}
    lourdes = [t for t, o in OLLAMA_TASK_OPTIONS.items() if (o.get("num_predict") or 0) > 200]
    assert lourdes
    for task in lourdes:
        assert budgets["gemma4:31b"][task] > budgets["gemma4:e2b"][task], task


def test_the_context_of_a_task_is_capped_by_what_the_model_holds():
    """Ollama ne refuse pas un prompt plus long que `num_ctx` : il en tronque
    silencieusement le DÉBUT. Le plafond du modèle doit donc s'appliquer là où
    les options sont lues — en un seul endroit."""
    etroit = ModelProfile(
        name="test:etroit", rank=0, tier="tiny", download_gb=1.0, min_ram_gb=4.0,
        tokens_per_s=20.0, prompt_tokens_per_s=300.0, load_overhead_s=10.0,
        max_num_ctx=2048, supports_images=False,
    )
    assert task_options("assistant_answer")["num_ctx"] == 8192
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "_active_profile", lambda: etroit)
        assert task_options("assistant_answer")["num_ctx"] == 2048
        # Les autres options de la tâche sont intactes, et la table n'est pas touchée.
        assert task_options("assistant_answer")["num_predict"] == 700
    assert OLLAMA_TASK_OPTIONS["assistant_answer"]["num_ctx"] == 8192


def test_heavy_task_gets_more_than_the_floor():
    """Une tâche de 3000 tokens ne peut pas tenir dans 60 s : c'est très
    exactement le cas qui échouait à tous les coups avant la correction."""
    assert task_timeout_s(HEAVY_TASK) > OLLAMA_TIMEOUT * 2


def test_wall_budget_covers_the_retries():
    """L'appelant attend la tâche ENTIÈRE. `_generate_json` peut rejouer une
    sortie non conforme : si l'attente ne couvrait qu'une tentative, la
    deuxième travaillerait pour un destinataire déjà parti."""
    for task in ("document_digest", "quiz_distractors", HEAVY_TASK):
        assert task_wall_timeout_s(task) > task_timeout_s(task)
        assert task_wall_timeout_s(task) <= OLLAMA_WALL_TIMEOUT_MAX


def test_async_task_publishes_its_own_budget_to_the_caller():
    """L'appelant synchrone n'invente plus son temps d'attente : il reprend
    celui que la tâche publie — le budget total, dérivé du num_predict."""
    seen: dict[str, float | None] = {}

    def fake_async(on_success, on_error):
        # Ce que fait `_run_json_async` : publier le budget de sa tâche.
        slot = ollama_client._current_caller_slot()
        slot.timeout_s = task_wall_timeout_s(HEAVY_TASK)
        seen["budget"] = slot.timeout_s
        on_success({"ok": True})

    assert run_llm_sync(fake_async) == {"ok": True}
    assert seen["budget"] == task_wall_timeout_s(HEAVY_TASK)


def test_caller_waits_for_the_budget_republished_when_the_task_starts():
    """Le budget publié à la mise en file précède le calibrage du démarrage,
    passé en tête de file : sur une machine lente, la tâche s'accorde davantage
    en partant. L'appelant l'attend, au lieu de renoncer pendant qu'elle
    travaille encore pour lui."""

    def slow_machine(on_success, on_error):
        slot = ollama_client._current_caller_slot()
        slot.timeout_s = 0.2  # à la mise en file

        def worker():
            slot.timeout_s = 2.0  # republié au départ (`_start_task_clock`)
            slot.started.set()
            time.sleep(0.5)  # au-delà du premier budget, en deçà du second
            on_success("réponse")

        threading.Thread(target=worker, daemon=True).start()

    assert run_llm_sync(slow_machine) == "réponse"


def test_timeout_raises_and_flags_the_task_as_abandoned():
    """Sur timeout, le drapeau d'abandon est levé : le worker jettera la tâche
    au lieu de bloquer la file pour tout le monde."""
    captured: dict[str, threading.Event] = {}

    def never_answers(on_success, on_error):
        captured["abandon"] = ollama_client._current_caller_slot().abandon

    with pytest.raises(TimeoutError):
        run_llm_sync(never_answers, timeout=0.05)

    assert captured["abandon"].is_set()


def test_abandoned_task_is_dropped_by_the_worker(monkeypatch):
    """Bout en bout sur la vraie file : une tâche abandonnée pendant qu'elle
    attend son tour ne doit jamais s'exécuter."""
    started = threading.Event()
    release = threading.Event()
    ran_second = threading.Event()

    def bloque_le_worker():
        started.set()
        release.wait(5)

    # 1) On occupe le worker unique.
    _wait_worker_idle()
    ollama_client._LLM_QUEUE.put((0, -2, bloque_le_worker))
    assert started.wait(5)

    # 2) On enfile une tâche derrière, via le chemin réel, et on renonce.
    #    Le budget vient de la tâche : on le rend minuscule pour ce test plutôt
    #    que d'attendre les 60 s réelles de `document_digest`.
    monkeypatch.setattr(ollama_client, "task_wall_timeout_s", lambda _task: 0.1)
    # La file est PARTAGÉE avec les autres tests (fiches de document remises en
    # file après une annulation, par exemple) : on ne compte que NOTRE tâche.
    prompt = "prompt-abandonne"

    def _generate(label, p, *a, **kw):
        if p == prompt:
            ran_second.set()
        return {"x": 1}

    monkeypatch.setattr(ollama_client, "_generate_json", _generate)

    def enqueue(on_success, on_error):
        ollama_client._run_json_async(
            "document_digest", prompt, lambda raw: raw, on_success, on_error, "modele",
        )

    with pytest.raises(TimeoutError):
        run_llm_sync(enqueue)

    # 3) Le worker se libère : la tâche abandonnée est jetée sans être lancée.
    release.set()
    time.sleep(0.3)
    assert not ran_second.is_set()


def test_task_enqueued_outside_run_llm_sync_is_never_marked_abandoned(monkeypatch):
    """Le slot est refermé après l'enfilement : une tâche du chemin WebSocket
    (asyncio, hors run_llm_sync) ne doit pas hériter du drapeau d'un appelant
    synchrone précédent du même thread."""
    with pytest.raises(TimeoutError):
        run_llm_sync(lambda ok, err: None, timeout=0.05)

    assert ollama_client._current_caller_slot() is None

    ran = threading.Event()
    _wait_worker_idle()
    monkeypatch.setattr(
        ollama_client, "_generate_json",
        lambda *a, **kw: ran.set() or {"x": 1},
    )
    ollama_client._run_json_async(
        "document_digest", "prompt", lambda raw: raw, lambda r: None, lambda e: None, "modele",
    )
    assert ran.wait(5)


def test_explicit_timeout_is_only_a_fallback():
    """Le nombre passé par l'appelant ne sert plus QUE si la tâche n'a pas publié
    de budget (appel hors file : test, callback immédiat). Dès qu'une vraie tâche
    est enfilée, c'est son budget qui gagne — sinon on réintroduirait exactement
    la divergence que cette correction supprime.

    Preuve : une tâche qui répond en 0,3 s survit à un `timeout=0.01` explicite
    parce qu'elle a publié un budget de 5 s. Avant, elle était tuée."""
    def repond_apres_300ms(on_success, on_error):
        ollama_client._current_caller_slot().timeout_s = 5.0
        threading.Timer(0.3, lambda: on_success({"ok": True})).start()

    started = time.monotonic()
    assert run_llm_sync(repond_apres_300ms, timeout=0.01) == {"ok": True}
    # Marge de 50 ms : sous Windows, `threading.Timer` s'appuie sur
    # `Event.wait()`, dont la granularité est celle de l'horloge système
    # (~15,6 ms) — il rend la main quelques millisecondes AVANT l'échéance
    # (mesuré : 0,297 s pour 0,3 s demandées). Ce qu'on prouve ici n'a pas
    # besoin de cette précision : c'est que l'appel a attendu la tâche au lieu
    # d'être tué à 0,01 s. 0,25 s reste 25 fois le timeout explicite.
    assert time.monotonic() - started >= 0.25

    # Inversement, sans budget publié, le nombre de l'appelant s'applique.
    with pytest.raises(TimeoutError):
        run_llm_sync(lambda ok, err: None, timeout=0.05)


def test_retry_loop_stops_at_the_wall_deadline(monkeypatch):
    """La boucle de réparation JSON et l'appelant partagent UNE échéance : passé
    le budget total, on ne rejoue plus. Sans ça, 4 tentatives à budget plein
    tiendraient le worker unique bien après le départ de l'appelant."""
    appels = []

    def _lent_et_invalide(prompt, model, images=None, options=None, format_json=True, task=""):
        appels.append(time.monotonic())
        time.sleep(0.15)
        return "pas du json"

    monkeypatch.setattr(ollama_client, "_call_ollama", _lent_et_invalide)
    monkeypatch.setattr(ollama_client, "task_wall_timeout_s", lambda _task: 0.2)
    monkeypatch.setattr(ollama_client, "_fallback_json_result", lambda *a, **kw: None)

    with pytest.raises(ValueError):
        ollama_client._generate_json(
            "document_digest", "prompt", lambda raw: None, model="modele", retries=3,
        )

    # 4 tentatives étaient autorisées ; l'échéance en coupe l'essentiel.
    assert 1 <= len(appels) <= 2, appels
