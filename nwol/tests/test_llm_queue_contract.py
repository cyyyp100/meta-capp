# Contrat de la file LLM (llm/ollama_client._enqueue_task).
#
# Retour d'usage (2026-10-22) : après la finalisation au démarrage des séances
# quittées en fermant le logiciel, Clikoda ne posait plus de questions dans le
# lecteur. Trois défauts de la file y concouraient, figés ici :
#   * une tâche pouvait finir SANS rappel (appelant parti), ou en recevoir DEUX
#     (un `on_success` qui levait recevait aussi `on_error`) — or le lecteur
#     compte ses générations et la politique attend sa décision ;
#   * le bilan d'une séance reprise partait à la priorité du sas de sortie,
#     devant chaque question du lecteur, et fermer le lecteur le coupait ;
#   * rien n'empêchait un rappel (sur le worker) d'attendre une autre tâche.
from __future__ import annotations

import threading
import time

import pytest


def _calls():
    """Rappels reçus, dans l'ordre : ("ok", résultat) / ("err", message)."""
    got: list[tuple[str, object]] = []
    return got, (lambda r: got.append(("ok", r))), (lambda m: got.append(("err", m)))


def _generates(monkeypatch, fn):
    from llm import ollama_client

    monkeypatch.setattr(ollama_client, "_generate_json", fn)


# ── Un rappel, toujours, et un seul ───────────────────────────────────────────

def test_a_generation_calls_back_once_with_its_result(monkeypatch, captured_queue):
    from llm import ollama_client

    _generates(monkeypatch, lambda label, *a, **k: {"label": label})
    got, ok, err = _calls()
    ollama_client._run_json_async("question", "p", lambda r: r, ok, err, "m")
    captured_queue.run_all()
    assert got == [("ok", {"label": "question"})]


def test_a_failure_calls_back_once_with_its_message(monkeypatch, captured_queue):
    from llm import ollama_client

    def boom(*_a, **_k):
        raise RuntimeError("Ollama indisponible")

    _generates(monkeypatch, boom)
    got, ok, err = _calls()
    ollama_client._run_json_async("question", "p", lambda r: r, ok, err, "m")
    captured_queue.run_all()
    assert got == [("err", "Ollama indisponible")]


def test_a_task_whose_caller_gave_up_still_calls_back(monkeypatch, captured_queue):
    """Elle retournait sans rien dire : le pont synchrone, parti, ne s'en
    souciait pas, mais tout appelant qui attend un rappel restait suspendu."""
    from llm import ollama_client

    generated: list[str] = []
    _generates(monkeypatch, lambda label, *a, **k: generated.append(label) or {})
    got, ok, err = _calls()
    slot = ollama_client.open_caller_slot()
    try:
        ollama_client._run_json_async("question", "p", lambda r: r, ok, err, "m")
    finally:
        ollama_client.close_caller_slot()
    slot.abandon.set()
    captured_queue.run_all()
    assert generated == []  # rien n'est parti chez Ollama
    assert got == [("err", ollama_client.CANCELLED_MESSAGE)]


def test_a_failure_before_the_generation_still_calls_back(monkeypatch, captured_queue):
    """Le départ de l'horloge (débit, préférence en base) était hors du
    `try` : une exception y finissait la tâche sans rappel."""
    from llm import ollama_client

    def broken_clock(*_a):
        raise RuntimeError("débit illisible")

    monkeypatch.setattr(ollama_client, "_start_task_clock", broken_clock)
    got, ok, err = _calls()
    ollama_client._run_text_async("brainstorm_answer", "p", ok, err, "m")
    captured_queue.run_all()
    assert got == [("err", "débit illisible")]


def test_a_raising_callback_is_logged_never_called_back_twice(monkeypatch, captured_queue, caplog):
    from llm import ollama_client

    _generates(monkeypatch, lambda label, *a, **k: {"ok": True})
    errors: list[str] = []

    def on_success(_result):
        raise ValueError("traitement du résultat")

    ollama_client._run_json_async("question", "p", lambda r: r, on_success, errors.append, "m")
    with caplog.at_level("ERROR", logger="LLM"):
        captured_queue.run_all()
    assert errors == []
    assert "Rappel de la tâche LLM question en échec" in caplog.text


def test_a_task_ending_without_callback_is_returned_as_cancelled(monkeypatch, captured_queue, caplog):
    """Filet du `finally` : une sortie qu'une modification future oublierait
    de rappeler est rendue comme annulée, et dite dans le journal."""
    from llm import ollama_client

    _generates(monkeypatch, lambda label, *a, **k: {"ok": True})
    monkeypatch.setattr(ollama_client._Outcome, "success", lambda self, result: None)
    got, ok, err = _calls()
    ollama_client._run_json_async("question", "p", lambda r: r, ok, err, "m")
    with caplog.at_level("ERROR", logger="LLM"):
        captured_queue.run_all()
    assert got == [("err", ollama_client.CANCELLED_MESSAGE)]
    assert "finie sans rappel" in caplog.text


# ── Le travail de fond passe après l'écran ────────────────────────────────────

def test_background_work_runs_after_everything_a_screen_waits_for(monkeypatch, captured_queue):
    """Le bilan d'une séance reprise (priorité 1 au sas de sortie) passait
    devant la question et l'intervention du lecteur ; en fond, il passe après
    tout, fiche de document comprise, et garde son ordre parmi le fond."""
    from llm import ollama_client

    order: list[str] = []
    _generates(monkeypatch, lambda label, *a, **k: order.append(label) or {})
    ignore = lambda _x: None  # noqa: E731
    with ollama_client.background_tasks():
        ollama_client._run_json_async("session_summary", "p", lambda r: r, ignore, ignore, "m")
        ollama_client._run_json_async("profile_analysis", "p", lambda r: r, ignore, ignore, "m")
    for label in ("document_digest", "assistant_intervention", "question"):
        ollama_client._run_json_async(label, "p", lambda r: r, ignore, ignore, "m")
    assert not ollama_client.in_background()  # le bloc ne fuit pas
    captured_queue.run_all()
    assert order == ["question", "assistant_intervention", "document_digest", "session_summary", "profile_analysis"]


def test_closing_the_reader_never_cancels_background_work(monkeypatch, captured_queue):
    from llm import ollama_client

    domains: list[object] = []
    _generates(monkeypatch, lambda label, *a, **k: domains.append(ollama_client._TASK_DOMAIN.value) or {"ok": label})
    reader, ok_r, err_r = _calls()
    background, ok_b, err_b = _calls()
    ollama_client._run_json_async("question", "p", lambda r: r, ok_r, err_r, "m")
    with ollama_client.background_tasks():
        ollama_client._run_json_async("session_summary", "p", lambda r: r, ok_b, err_b, "m")
    ollama_client.cancel_pending_generations()  # le lecteur se ferme
    captured_queue.run_all()
    assert reader == [("err", ollama_client.CANCELLED_MESSAGE)]
    assert background == [("ok", {"ok": "session_summary"})]
    # La génération en vol se déclare du fond : la coupure du lecteur
    # (`_abort_inflight_generation("default")`) ne la touche pas.
    assert domains == ["background"]


def test_a_background_sync_call_does_not_count_its_queue_time(monkeypatch, captured_queue):
    """Dans `background_tasks()`, `run_llm_sync` est un appelant de fond : le
    temps passé derrière le lecteur ne consomme pas son budget."""
    from llm import ollama_client
    from services.llm_bridge import run_llm_sync

    monkeypatch.setattr(ollama_client, "task_wall_timeout_s", lambda _task: 0.3)
    _generates(monkeypatch, lambda label, *a, **k: {"ok": label})

    def reader_then_free():
        time.sleep(0.6)  # le lecteur occupe le worker deux fois le budget
        captured_queue.run_all()

    threading.Thread(target=reader_then_free, daemon=True).start()
    enqueue = lambda ok, err: ollama_client._run_json_async("session_summary", "p", lambda r: r, ok, err, "m")  # noqa: E731
    with ollama_client.background_tasks():
        assert run_llm_sync(enqueue) == {"ok": "session_summary"}


# ── Le worker ne s'attend jamais lui-même ─────────────────────────────────────

def test_a_callback_cannot_wait_for_another_task():
    """Un rappel tourne sur le worker : attendre une autre tâche (pont
    synchrone) figeait la file entière jusqu'au timeout. Refus immédiat."""
    from llm import ollama_client
    from services.llm_bridge import run_llm_sync

    outcome: dict[str, object] = {}
    done = threading.Event()

    def on_worker():
        try:
            run_llm_sync(lambda ok, err: ok("jamais"))
        except RuntimeError as exc:
            outcome["error"] = str(exc)
        finally:
            done.set()

    ollama_client._LLM_QUEUE.put((0, next(ollama_client._QUEUE_COUNTER), on_worker))
    assert done.wait(10)
    assert "worker LLM" in str(outcome.get("error"))


@pytest.mark.parametrize("label", ["question", "session_summary", "lang_episode_text"])
def test_background_priorities_stay_below_every_screen(label):
    from llm import ollama_client

    with ollama_client.background_tasks():
        priority, domain = ollama_client._task_placement(label)
    assert priority > max(ollama_client._TASK_PRIORITY.values())
    assert domain == "background"
