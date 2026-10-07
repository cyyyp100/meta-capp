"""Budgets temps adaptés au débit RÉEL de la machine (llm/throughput).

Les budgets partaient d'un débit mesuré sur un Mac Apple Silicon. Sur un PC
sans GPU, Clikoda va plusieurs fois moins vite : chaque réponse longue expirait
alors que le modèle travaillait normalement. Ces tests figent le contrat :
une machine lente obtient plus de temps, une machine rapide jamais moins, et
une expiration suffit à apprendre que la machine est lente.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from config.settings import (
    OLLAMA_MAX_SLOWDOWN,
    OLLAMA_PROMPT_TOKENS_PER_S,
    OLLAMA_TIMEOUT_MAX,
    OLLAMA_TOKENS_PER_S,
    OLLAMA_WALL_TIMEOUT_MAX,
    task_timeout_s,
    task_wall_timeout_s,
)
from llm import ollama_client, throughput

NS = 1_000_000_000


def _ollama_reply(output_tps: float, prompt_tps: float, output_tokens: int = 200, prompt_tokens: int = 2000) -> dict:
    return {
        "response": "{}",
        "eval_count": output_tokens,
        "eval_duration": int(output_tokens / output_tps * NS),
        "prompt_eval_count": prompt_tokens,
        "prompt_eval_duration": int(prompt_tokens / prompt_tps * NS),
    }


def test_unmeasured_machine_keeps_the_reference_budgets():
    assert throughput.slowdown() == (1.0, 1.0)
    # 25 s + 3000 / 18 tokens/s : la formule d'origine, inchangée.
    assert task_timeout_s("lang_curriculum") == pytest.approx(25.0 + 3000 / OLLAMA_TOKENS_PER_S)


def test_slow_machine_gets_proportionally_more_time():
    """PC sans GPU : 6 tokens/s écrits (3× la référence), 50 lus (4×)."""
    before = task_timeout_s("assistant_answer")
    throughput.record_call(_ollama_reply(output_tps=6.0, prompt_tps=50.0))

    gen_slow, prompt_slow = throughput.slowdown()
    assert gen_slow == pytest.approx(OLLAMA_TOKENS_PER_S / 6.0)
    assert prompt_slow == pytest.approx(OLLAMA_PROMPT_TOKENS_PER_S / 50.0)
    after = task_timeout_s("assistant_answer")
    # 700 tokens à 6/s + 4 × 25 s de lecture : ~217 s, là où 64 s expiraient.
    assert after == pytest.approx(25.0 * prompt_slow + 700 / 6.0)
    assert after > 3 * before


def test_ceilings_stretch_with_the_machine():
    """Sans plafond étiré, `lang_curriculum` (3000 tokens) restait bloqué à
    240 s — 500 s de travail à 6 tokens/s : un échec à tous les coups."""
    throughput.record_call(_ollama_reply(output_tps=6.0, prompt_tps=50.0))
    assert task_timeout_s("lang_curriculum") > OLLAMA_TIMEOUT_MAX
    assert task_timeout_s("lang_curriculum") >= 3000 / 6.0
    assert task_wall_timeout_s("lang_curriculum") > OLLAMA_WALL_TIMEOUT_MAX


def test_fast_machine_never_shortens_a_budget():
    reference = task_timeout_s("assistant_answer")
    throughput.record_call(_ollama_reply(output_tps=120.0, prompt_tps=3000.0))
    assert throughput.slowdown() == (1.0, 1.0)
    assert task_timeout_s("assistant_answer") == reference


def test_tiny_samples_are_ignored():
    """Une poignée de tokens mesure les frais fixes de l'appel, pas le débit."""
    throughput.record_call(_ollama_reply(output_tps=1.0, prompt_tps=5.0, output_tokens=3, prompt_tokens=20))
    assert throughput.slowdown() == (1.0, 1.0)


def test_a_single_fast_outlier_does_not_erase_a_slow_measure():
    throughput.record_call(_ollama_reply(output_tps=6.0, prompt_tps=50.0))
    slow = throughput.slowdown()[0]
    throughput.record_call(_ollama_reply(output_tps=60.0, prompt_tps=500.0))
    assert throughput.slowdown()[0] > 1.0
    assert throughput.slowdown()[0] < slow


def test_a_cached_prompt_never_makes_the_machine_look_faster():
    """Ollama compte tout le prompt dans `prompt_eval_count` mais ne chronomètre
    que la partie hors cache : un prompt qui recommence comme le précédent
    paraît huit fois plus rapide (mesuré : 2 050 tokens/s au lieu de 260)."""
    throughput.record_call(_ollama_reply(output_tps=6.0, prompt_tps=30.0))
    measured = throughput.slowdown()[1]
    throughput.record_call(_ollama_reply(output_tps=6.0, prompt_tps=240.0))  # préfixe en cache
    assert throughput.slowdown()[1] == pytest.approx(measured)
    throughput.record_call(_ollama_reply(output_tps=6.0, prompt_tps=15.0))  # plus lent : une preuve
    assert throughput.slowdown()[1] > measured


def test_a_timeout_doubles_the_time_and_stays_bounded():
    throughput.record_timeout()
    assert throughput.slowdown() == (pytest.approx(2.0), pytest.approx(2.0))
    for _ in range(10):
        throughput.record_timeout()
    assert throughput.slowdown() == (OLLAMA_MAX_SLOWDOWN, OLLAMA_MAX_SLOWDOWN)
    assert task_timeout_s("lang_curriculum") <= OLLAMA_TIMEOUT_MAX * OLLAMA_MAX_SLOWDOWN


# ── Bout en bout : ce que renvoie (ou ne renvoie pas) Ollama ─────────────────


@pytest.fixture
def fake_ollama(monkeypatch):
    """Un « Ollama » HTTP local dont on choisit la réponse ; compte les requêtes."""
    state = {"status": 200, "body": {}, "requests": 0, "delay": 0.0, "tags": {"models": []}}
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - API de http.server (`/api/tags`)
            payload = json.dumps(state["tags"]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):  # noqa: N802 - API de http.server
            state["last"] = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            state["requests"] += 1
            if state["delay"]:
                stop.wait(state["delay"])
            payload = json.dumps(state["body"]).encode()
            try:
                self.send_response(state["status"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except OSError:
                pass  # le client a déjà raccroché (timeout simulé)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        ollama_client, "OLLAMA_URL", f"http://127.0.0.1:{server.server_address[1]}/api/generate"
    )
    yield state
    stop.set()
    server.shutdown()
    server.server_close()


def test_every_successful_call_feeds_the_measure(fake_ollama):
    fake_ollama["body"] = _ollama_reply(output_tps=6.0, prompt_tps=50.0)
    ollama_client._call_ollama_http("prompt", "model", task="question")
    assert throughput.snapshot()["output_tokens_per_s"] == pytest.approx(6.0)
    assert throughput.slowdown()[0] > 1.0


def test_an_expired_call_teaches_that_the_machine_is_slow(fake_ollama, monkeypatch):
    """Le cas qui bloquait : la PREMIÈRE génération d'une machine lente expire,
    ne renvoie aucune durée, et la suivante expirait exactement pareil."""
    fake_ollama["delay"] = 2.0
    monkeypatch.setattr(ollama_client, "task_timeout_s", lambda _task: 0.3)
    with pytest.raises(RuntimeError):
        ollama_client._call_ollama_http("prompt", "model", task="question")
    assert throughput.slowdown() == (pytest.approx(2.0), pytest.approx(2.0))


def test_an_attempt_never_outlives_its_task(fake_ollama):
    """Une tentative lancée tard est bornée par l'échéance de sa tâche — celle
    que l'appelant attend — et cette coupure-là ne dit rien de la vitesse de la
    machine : elle n'étire pas les budgets."""
    fake_ollama["delay"] = 4.0
    ollama_client._TASK_DEADLINE.value = time.monotonic() + 0.2
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError):
            ollama_client._call_ollama_http("prompt", "model", task="question")
    finally:
        ollama_client._TASK_DEADLINE.value = None
    assert time.monotonic() - started < 3.0
    assert throughput.slowdown() == (1.0, 1.0)


def test_the_budget_is_set_when_the_task_leaves_the_queue():
    """Publié à la mise en file, le budget ignorait ce que le calibrage — passé
    entre-temps, en tête de file — venait d'apprendre de la machine."""
    slot = ollama_client.CallerSlot()
    queued_budget = task_wall_timeout_s("assistant_answer")
    throughput.record_call(_ollama_reply(output_tps=4.0, prompt_tps=40.0))
    try:
        ollama_client._start_task_clock("assistant_answer", slot)
        assert slot.started.is_set()
        assert slot.timeout_s == pytest.approx(task_wall_timeout_s("assistant_answer"))
        assert slot.timeout_s > queued_budget
        assert ollama_client._TASK_DEADLINE.value == pytest.approx(time.monotonic() + slot.timeout_s, abs=1.0)
    finally:
        ollama_client._TASK_DEADLINE.value = None


def test_ollama_is_reached_without_the_system_proxy(fake_ollama, monkeypatch):
    """`urlopen` applique le proxy du système même à 127.0.0.1 : derrière celui
    d'un réseau d'école, Clikoda passait pour éteinte."""
    fake_ollama["tags"] = {"models": [{"name": "gemma4:e4b"}]}
    for name in ("http_proxy", "HTTP_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")  # proxy injoignable
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.setattr(urllib.request, "_opener", None)  # l'opener par défaut relirait l'environnement
    assert ollama_client._model_installed("gemma4:e4b")


@pytest.fixture
def real_provider(monkeypatch):
    """`no_real_generation` coupe le fournisseur : on le rebranche sur le faux serveur."""
    from services import llm_provider

    monkeypatch.setattr(
        llm_provider, "_ollama_generate",
        lambda prompt, model, images, options, format_json, task="": ollama_client._call_ollama_http(
            prompt, model, images=images, options=options, format_json=format_json, task=task,
        ),
    )


def _out_of_memory(state: dict) -> None:
    state["status"] = 500
    state["body"] = {"error": "model requires more system memory (10.2 GiB) than is available (6.1 GiB)"}


def test_out_of_memory_is_explained_and_not_retried(fake_ollama, real_provider):
    """Une question de l'étudiant : il lit POURQUOI Clikoda ne répond pas, pas
    une réponse générique de repli qui cacherait que la machine est trop juste."""
    _out_of_memory(fake_ollama)
    with pytest.raises(ollama_client.ModelOutOfMemory) as excinfo:
        ollama_client._generate_json(
            "assistant_answer", "prompt", lambda _raw: None, model="model", retries=3,
        )
    message = str(excinfo.value)
    assert "10.2 GiB" in message and "6.1 GiB" in message
    assert "Échec LLM" not in message  # pas d'enveloppe technique devant l'étudiant
    assert fake_ollama["requests"] == 1  # recharger 10 Go quatre fois n'y changerait rien


def test_out_of_memory_keeps_the_silent_fallback_of_background_tasks(fake_ollama, real_provider):
    """Une intervention autonome se tait, comme quand Ollama est éteint."""
    _out_of_memory(fake_ollama)
    result = ollama_client._generate_json(
        "assistant_intervention", "prompt", lambda _raw: None, model="model", retries=3,
    )
    assert result["should_intervene"] is False
    assert fake_ollama["requests"] == 1


def test_calibration_is_skipped_when_ollama_is_off(monkeypatch):
    queued: list = []
    monkeypatch.setattr(ollama_client._LLM_QUEUE, "put", queued.append)
    monkeypatch.setattr(ollama_client, "is_ollama_available", lambda: False)
    ollama_client.calibrate_throughput()
    assert queued == []


def test_calibration_runs_first_and_measures(monkeypatch):
    queued: list = []
    calls: list[str] = []
    monkeypatch.setattr(ollama_client._LLM_QUEUE, "put", queued.append)
    monkeypatch.setattr(ollama_client, "is_ollama_available", lambda: True)
    monkeypatch.setattr(ollama_client, "_model_installed", lambda _model: True)

    def fake_call(_prompt, _model, images=None, options=None, format_json=True, task=""):
        calls.append(task)
        throughput.record_call(_ollama_reply(output_tps=6.0, prompt_tps=50.0))
        return "ok"

    monkeypatch.setattr(ollama_client, "_call_ollama", fake_call)
    ollama_client.calibrate_throughput()

    assert len(queued) == 1
    priority, _seq, run = queued[0]
    assert priority == min(ollama_client._TASK_PRIORITY.values())
    run()
    assert calls == ["calibration"]
    assert throughput.slowdown()[0] > 1.0


def test_each_calibration_starts_differently(monkeypatch):
    """Relancé avant la fin du `keep_alive`, un prompt identique serait servi par
    le cache de préfixe d'Ollama : la lecture mesurée serait fausse."""
    queued: list = []
    prompts: list[str] = []
    monkeypatch.setattr(ollama_client._LLM_QUEUE, "put", queued.append)
    monkeypatch.setattr(ollama_client, "is_ollama_available", lambda: True)
    monkeypatch.setattr(ollama_client, "_model_installed", lambda _model: True)
    monkeypatch.setattr(
        ollama_client, "_call_ollama",
        lambda prompt, _model, images=None, options=None, format_json=True, task="": prompts.append(prompt) or "ok",
    )
    for _ in range(2):
        ollama_client.calibrate_throughput()
    for _priority, _seq, run in queued:
        run()
    assert prompts[0] != prompts[1]
    assert prompts[0].split("\n", 1)[0] != prompts[1].split("\n", 1)[0], "la différence doit être au DÉBUT"
    assert all(p.endswith(ollama_client._CALIBRATION_PROMPT) for p in prompts)


def test_a_json_schema_constrains_the_decoding(fake_ollama):
    """Sorties structurées : un schéma passe tel quel dans `format` (le glossaire
    y impose une entrée par mot) ; sans lui, le simple mode JSON."""
    from llm.schema_json import lang_episode_glossary_schema

    fake_ollama["body"] = _ollama_reply(output_tps=30.0, prompt_tps=300.0)
    schema = lang_episode_glossary_schema(20, pron=True)
    ollama_client._call_ollama_http("prompt", "model", format_json=schema, task="lang_episode_glossary_pron")
    assert fake_ollama["last"]["format"] == schema
    assert schema["properties"]["entries"]["minItems"] == schema["properties"]["entries"]["maxItems"] == 20
    assert schema["properties"]["entries"]["items"]["minItems"] == 6
    ollama_client._call_ollama_http("prompt", "model", task="question")
    assert fake_ollama["last"]["format"] == "json"


def test_the_glossary_asks_one_entry_per_word_at_decoding(monkeypatch):
    """gemma4:e4b refermait la liste du glossaire après UNE entrée, à chaque
    appel, sur certains textes (banc du 2026-10-07) : le nombre d'entrées est
    imposé au décodage, et la consigne reste la même."""
    seen = {}
    monkeypatch.setattr(ollama_client, "_run_json_async", lambda label, prompt, parser, *a, **kw: seen.update(label=label, **kw))
    ollama_client.generate_lang_episode_glossary_async(
        {"language_label": "espagnol", "words": ["Hola", "Cómo", "te"], "lines": [("Hola", "Salut")], "pron": True},
        lambda r: None, lambda e: None)
    entries = seen["json_schema"]["properties"]["entries"]
    assert seen["label"] == "lang_episode_glossary_pron" and entries["minItems"] == entries["maxItems"] == 3
    calls = []
    monkeypatch.setattr(ollama_client, "_call_ollama",
                        lambda prompt, model, images=None, options=None, format_json=True, task="": calls.append(format_json) or '{"entries": []}')
    ollama_client._generate_json("lang_episode_glossary", "p", lambda raw: {"ok": True}, model="m",
                                 json_schema={"type": "object"})
    assert calls == [{"type": "object"}]
