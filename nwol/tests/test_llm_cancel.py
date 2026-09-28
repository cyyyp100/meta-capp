# Annulation d'une génération EN VOL.
#
# `cancel_pending_generations()` se contentait d'invalider un token : les tâches
# encore en file étaient jetées, mais celle déjà partie chez Ollama tournait
# jusqu'au bout — GPU occupé, et la première réponse du document suivant
# attendait derrière. Ces tests figent le nouveau contrat : la socket est coupée,
# l'appel en vol se termine tout de suite par `GenerationCancelled`, et rien
# n'est rejoué.
from __future__ import annotations

import socket
import threading
import time

import pytest


@pytest.fixture
def silent_server(monkeypatch):
    """Un « Ollama » qui accepte la connexion, lit la requête et ne répond jamais."""
    from llm import ollama_client

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    accepted: list[socket.socket] = []
    stop = threading.Event()

    def serve() -> None:
        srv.settimeout(0.1)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            accepted.append(conn)
            conn.settimeout(0.1)
            while not stop.is_set():
                try:
                    if not conn.recv(4096):
                        break
                except socket.timeout:
                    continue
                except OSError:
                    break

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    monkeypatch.setattr(ollama_client, "OLLAMA_URL", f"http://127.0.0.1:{port}/api/generate")
    # Un timeout socket confortable : c'est l'annulation qui doit terminer l'appel.
    monkeypatch.setattr(ollama_client, "task_timeout_s", lambda _task: 30.0)
    yield accepted
    stop.set()
    thread.join(timeout=2)
    for conn in accepted:
        conn.close()
    srv.close()


def test_cancel_cuts_the_inflight_call_immediately(silent_server):
    from llm import ollama_client

    outcome: dict = {}

    def call() -> None:
        try:
            ollama_client._call_ollama_http("prompt", "model", task="question")
        except Exception as exc:  # noqa: BLE001 - on veut le type exact
            outcome["exc"] = exc

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    # Attendre que la requête soit réellement partie (connexion acceptée).
    deadline = time.monotonic() + 3
    while not silent_server and time.monotonic() < deadline:
        time.sleep(0.01)
    assert silent_server, "la connexion n'a jamais atteint le serveur"

    t0 = time.monotonic()
    ollama_client.cancel_pending_generations()
    worker.join(timeout=3)

    assert not worker.is_alive(), "l'appel en vol est resté bloqué malgré l'annulation"
    assert time.monotonic() - t0 < 2
    assert isinstance(outcome.get("exc"), ollama_client.GenerationCancelled)


def test_cancelled_generation_is_not_retried(monkeypatch):
    """`_generate_json` rejoue une panne ; une annulation, jamais."""
    from llm import ollama_client

    calls = []

    def cut(*_a, **_k):
        calls.append(1)
        raise ollama_client.GenerationCancelled("coupée")

    monkeypatch.setattr(ollama_client, "_call_ollama", cut)
    with pytest.raises(ollama_client.GenerationCancelled):
        ollama_client._generate_json("question", "p", lambda raw: {}, model="m", retries=3)
    assert len(calls) == 1


def test_cancel_without_inflight_call_is_harmless():
    from llm import ollama_client

    before = ollama_client._generation_token
    ollama_client.cancel_pending_generations()
    assert ollama_client._generation_token == before + 1


# ── Domaines d'annulation (K3, G18) ───────────────────────────────────────────

class _CapturedQueue:
    """File LLM de substitution : les tâches enfilées sont gardées et jouées par
    le test, dans l'ordre de priorité, sur SON thread.

    Ces tests attendaient le worker LLM unique de l'application : quand une
    tâche laissée par un test précédent l'occupait plus de 3 s, ils échouaient
    (une fois sur trois dans la suite langue complète, jamais seuls — § 14,
    n° 9). `get`/`task_done` restent ceux de la vraie file : le worker, s'il
    termine une tâche pendant le test, retourne attendre là où il attendait."""

    def __init__(self, real):
        self.items: list = []
        self.get = real.get
        self.task_done = real.task_done

    def put(self, item) -> None:
        self.items.append(item)

    def run_all(self) -> None:
        for _prio, _seq, fn in sorted(self.items, key=lambda it: it[:2]):
            fn()
        self.items.clear()


@pytest.fixture
def captured_queue(monkeypatch):
    from llm import ollama_client

    queue = _CapturedQueue(ollama_client._LLM_QUEUE)
    monkeypatch.setattr(ollama_client, "_LLM_QUEUE", queue)
    return queue


def test_reader_cancel_never_touches_a_language_generation(monkeypatch, captured_queue):
    """Fermer le lecteur coupait aussi la pré-génération d'un épisode : les
    deux domaines ont désormais chacun leur token et leur coupure en vol."""
    from llm import ollama_client

    results: list = []

    def generate(label, *_a, **_k):
        # Le lecteur se ferme PENDANT la première question (tâche en vol).
        if label == "question" and not results:
            ollama_client.cancel_pending_generations()
        return {"label": label}

    monkeypatch.setattr(ollama_client, "_generate_json", generate)
    for name, label in (("reader1", "question"), ("lang", "lang_episode_text"), ("reader2", "question")):
        ollama_client._run_json_async(label, "p", lambda r: r, lambda r, n=name: results.append((n, r)),
                                      lambda m, n=name: results.append((f"{n}-err", m)), "m")
    captured_queue.run_all()
    kinds = {k for k, _ in results}
    assert kinds == {"reader1-err", "reader2-err", "lang"}


def test_inflight_abort_is_scoped_to_its_domain():
    from llm import ollama_client

    class FakeConn:
        closed = False
        sock = None

        def close(self):
            self.closed = True

    conn = FakeConn()
    with ollama_client._INFLIGHT_LOCK:
        ollama_client._inflight.update(conn=conn, cancelled=False, domain="lang")
    try:
        ollama_client._abort_inflight_generation("default")
        assert not conn.closed and not ollama_client._inflight["cancelled"]
        ollama_client._abort_inflight_generation("lang")
        assert conn.closed and ollama_client._inflight["cancelled"]
    finally:
        with ollama_client._INFLIGHT_LOCK:
            ollama_client._inflight.update(conn=None, cancelled=False, domain="default")


def test_every_language_task_has_a_priority():
    """K2 : aucune tâche `lang_*` ne retombe sur la priorité par défaut, et la
    correction attendue par l'apprenant passe devant le préchargement."""
    from config.settings import OLLAMA_TASK_OPTIONS
    from llm import ollama_client

    lang_tasks = {t for t in OLLAMA_TASK_OPTIONS if t.startswith("lang_")}
    assert lang_tasks <= set(ollama_client._TASK_PRIORITY)
    prio = ollama_client._TASK_PRIORITY
    assert prio["lang_correction"] < prio["lang_content_dialogue"]
    assert prio["lang_episode_text"] < prio["document_digest"]


def test_call_metrics_are_collected_per_task(monkeypatch, captured_queue):
    """G19 : chaque appel HTTP journalise ses mesures ; `on_metrics` les reçoit."""
    from llm import ollama_client

    def fake_generate(label, prompt, parser, **_k):
        ollama_client._record_call_metrics(label, {"eval_count": 12, "prompt_eval_count": 34,
                                                   "load_duration": 2e9}, 1.5)
        return {"ok": True}

    monkeypatch.setattr(ollama_client, "_generate_json", fake_generate)
    got, done = [], threading.Event()
    ollama_client._run_json_async("lang_episode_glossary", "p", lambda r: r, lambda r: done.set(),
                                  lambda m: done.set(), "m", on_metrics=got.extend)
    captured_queue.run_all()
    assert done.is_set()
    assert got and got[0]["output_tokens"] == 12 and got[0]["load_s"] == 2.0


# ── File d'attente et budget d'un appel de fond (§ 14, n° 6) ──────────────────

def test_a_background_call_budget_starts_when_the_worker_takes_it(monkeypatch, captured_queue):
    """Le temps passé en file derrière le lecteur ne consomme plus le budget
    d'un appel d'épisode : il n'expire plus avant d'avoir commencé."""
    from llm import ollama_client
    from services.llm_bridge import run_llm_sync

    monkeypatch.setattr(ollama_client, "task_wall_timeout_s", lambda _task: 0.3)
    monkeypatch.setattr(ollama_client, "_generate_json", lambda label, *a, **k: {"ok": label})

    def worker_busy_then_free():
        time.sleep(0.6)  # le lecteur occupe le worker deux fois le budget de l'appel
        captured_queue.run_all()

    threading.Thread(target=worker_busy_then_free, daemon=True).start()
    enqueue = lambda ok, err: ollama_client._run_json_async("lang_episode_text", "p", lambda r: r, ok, err, "m")  # noqa: E731
    assert run_llm_sync(enqueue, queue_wait_s=5.0) == {"ok": "lang_episode_text"}


def test_a_foreground_call_still_counts_its_queue_time(monkeypatch, captured_queue):
    """Un endpoint que l'utilisateur attend garde l'ancien contrat : file comprise."""
    from llm import ollama_client
    from services.llm_bridge import run_llm_sync

    monkeypatch.setattr(ollama_client, "task_wall_timeout_s", lambda _task: 0.2)
    enqueue = lambda ok, err: ollama_client._run_json_async("question", "p", lambda r: r, ok, err, "m")  # noqa: E731
    with pytest.raises(TimeoutError):
        run_llm_sync(enqueue)
    captured_queue.items.clear()


def test_a_background_call_gives_up_after_its_queue_allowance(captured_queue):
    from llm import ollama_client
    from services.llm_bridge import run_llm_sync

    slot_seen = {}

    def enqueue(ok, err):
        ollama_client._run_json_async("lang_episode_text", "p", lambda r: r, ok, err, "m")
        slot_seen["slot"] = ollama_client._current_caller_slot()

    with pytest.raises(TimeoutError, match="file"):
        run_llm_sync(enqueue, queue_wait_s=0.05)
    assert slot_seen["slot"].abandon.is_set()  # le worker jettera la tâche au lieu de la lancer
    captured_queue.items.clear()
