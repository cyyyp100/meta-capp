"""Le mode économe (config/settings.py, § Mode économe ; services/llm_models).

Sur une machine de 4 Gio, seul le palier minuscule tient, sur le seul
processeur. Ces tests figent ce que le mode y change — et qu'il le décide en
UN endroit : un contexte unique (aucun rechargement du modèle entre deux
tâches), des budgets étirés mais bornés à un quart d'heure, le même plafond de
lenteur pour les budgets et pour les débits mesurés, aucun travail de fond,
aucune aide autonome, aucun embedding, aucune image envoyée à un modèle qui ne
les lit pas. Et qu'il ne change RIEN quand il est coupé.
"""
from __future__ import annotations

import threading

import pytest

from config import settings
from config.settings import (
    ECONOMY_NUM_BATCH,
    ECONOMY_NUM_CTX,
    LLM_MODELS,
    LLM_REFERENCE_PROFILE,
    OLLAMA_BACKGROUND_TASKS,
    OLLAMA_KEEP_ALIVE,
    OLLAMA_KEEP_ALIVE_ECONOMY,
    OLLAMA_MAX_SLOWDOWN,
    OLLAMA_MAX_SLOWDOWN_ECONOMY,
    OLLAMA_TASK_OPTIONS,
    OLLAMA_TIMEOUT_MAX_ECONOMY,
    OLLAMA_WALL_TIMEOUT_MAX_ECONOMY,
    task_options,
    task_timeout_s,
    task_wall_timeout_s,
)
from llm import ollama_client, throughput
from services import llm_models

TINY = LLM_MODELS["qwen3:1.7b"]


@pytest.fixture
def economy(monkeypatch):
    """Mode économe forcé, sur le modèle de référence sauf avis contraire."""
    monkeypatch.setattr(llm_models, "economy_preference", lambda: "on")
    return monkeypatch


def _slow_machine(tokens_per_s: float, model: str = "") -> None:
    """Une génération mesurée à `tokens_per_s` (lecture du prompt 10 fois plus lente que la référence)."""
    ns = 1_000_000_000
    reference = llm_models.profile(model or llm_models.active())
    throughput.record_call({
        "eval_count": 200, "eval_duration": int(200 / tokens_per_s * ns),
        "prompt_eval_count": 2000,
        "prompt_eval_duration": int(2000 / (reference.prompt_tokens_per_s / 10) * ns),
    }, model)


# ── La décision, sans base ni HTTP ───────────────────────────────────────────


def test_auto_economizes_the_tiny_tier_and_small_machines_only():
    assert llm_models.economy_decision("auto", "tiny", 16.0) == "tiny_model"
    assert llm_models.economy_decision("auto", "small", 4.0) == "low_ram"
    assert llm_models.economy_decision("auto", "standard", 16.0) is None
    # Une RAM inconnue n'active rien : un inconnu n'est pas un refus.
    assert llm_models.economy_decision("auto", "standard", None) is None


def test_an_explicit_choice_wins_in_both_directions():
    """Il faut pouvoir forcer dans les deux sens : une machine de 16 Go qui veut
    économiser, une de 4 Go qui préfère attendre que perdre l'aide autonome."""
    assert llm_models.economy_decision("on", "large", 64.0) == "preference"
    assert llm_models.economy_decision("off", "tiny", 4.0) is None


def test_the_tiny_tier_is_what_auto_picks_on_a_4_gb_machine():
    installed = ["qwen3:1.7b", "gemma4:e2b", "gemma4:e4b"]
    assert llm_models.auto_pick(installed, 4.0) == "qwen3:1.7b"
    # … et jamais ailleurs : sur 16 Go, le palier minuscule est le moins bien classé.
    assert llm_models.auto_pick(installed, 16.0) == "gemma4:e4b"
    assert llm_models.resolve("auto", ["qwen3:1.7b"], 4.0)["reason"] is None


def test_every_model_name_and_economy_value_survives_lowercasing():
    """`preferences._validate` met en minuscules : une valeur de la table qui ne
    l'est pas rendrait le réglage inécrivable."""
    from services.preferences import PREFERENCES

    for key in ("llm_model", "llm_economy"):
        for value in PREFERENCES[key].choices:
            assert value == value.lower(), (key, value)


# ── Ce que le mode change, et ce qu'il ne change pas ─────────────────────────


def test_off_changes_nothing():
    """Coupé, le mode économe ne touche à rien : les options sont celles de la
    table, au caractère près (le plafond du modèle de référence est 8192)."""
    assert not llm_models.economy()
    for task, options in OLLAMA_TASK_OPTIONS.items():
        assert task_options(task) == options, task
    assert settings.keep_alive() == OLLAMA_KEEP_ALIVE
    assert settings.max_slowdown() == OLLAMA_MAX_SLOWDOWN
    assert not settings.compact_context()


def test_one_context_for_every_task_so_the_model_never_reloads(economy):
    """Ollama recharge le modèle à chaque changement de `num_ctx` ou de
    `num_batch` (mesuré) : en mode économe, toutes les tâches partagent les deux."""
    shapes = {(task_options(t)["num_ctx"], task_options(t)["num_batch"]) for t in OLLAMA_TASK_OPTIONS}
    assert shapes == {(ECONOMY_NUM_CTX, ECONOMY_NUM_BATCH)}
    # Le reste des options de la tâche est intact, et la table n'est pas touchée.
    assert task_options("assistant_answer")["num_predict"] == OLLAMA_TASK_OPTIONS["assistant_answer"]["num_predict"]
    assert "num_batch" not in OLLAMA_TASK_OPTIONS["assistant_answer"]
    assert settings.keep_alive() == OLLAMA_KEEP_ALIVE_ECONOMY
    assert settings.compact_context()


def test_the_tiny_tier_is_compact_even_with_economy_forced_off(monkeypatch):
    """C'est la taille du contexte qui décide de la taille du prompt, pas le
    réglage qui l'a produite : qwen3 ne tient que 4096 tokens."""
    monkeypatch.setattr(settings, "_active_profile", lambda: TINY)
    monkeypatch.setattr(llm_models, "economy_preference", lambda: "off")
    assert not llm_models.economy()
    assert settings.compact_context()
    assert task_options("assistant_answer")["num_ctx"] == TINY.max_num_ctx
    assert "num_batch" not in task_options("assistant_answer")


def test_the_slowest_machine_gets_its_budget_but_never_more_than_a_quarter_hour(economy):
    """≈ 0,9 token/s : hors mode économe, la lenteur admise plafonne à 8 et la
    réponse expire ; en mode économe elle monte à 20, et le quart d'heure tient."""
    _slow_machine(0.9)
    gen_slow, _ = throughput.slowdown()
    assert gen_slow == pytest.approx(min(OLLAMA_MAX_SLOWDOWN_ECONOMY, LLM_REFERENCE_PROFILE.tokens_per_s / 0.9))
    for task in OLLAMA_TASK_OPTIONS:
        assert task_timeout_s(task) <= OLLAMA_TIMEOUT_MAX_ECONOMY, task
        assert task_wall_timeout_s(task) <= OLLAMA_WALL_TIMEOUT_MAX_ECONOMY, task
    # La réponse libre (700 tokens) tient dans son budget à cette vitesse.
    assert task_timeout_s("assistant_answer") >= 700 / 0.9 * 0.95


def test_the_measured_floor_and_the_budget_ceiling_are_the_same_number(economy):
    """`llm/throughput` lisait `OLLAMA_MAX_SLOWDOWN` à l'import : en mode
    économe, le plancher des débits serait resté à 8 pendant que les budgets
    montaient à 20 — un facteur 2,5 entre les deux. Ils lisent maintenant le
    même `max_slowdown()`."""
    for _ in range(12):
        throughput.record_timeout()
    assert throughput.slowdown() == (OLLAMA_MAX_SLOWDOWN_ECONOMY, OLLAMA_MAX_SLOWDOWN_ECONOMY)
    # Le mode s'arrête : la mesure n'est pas jetée, elle est bornée au plafond normal.
    economy.setattr(llm_models, "economy_preference", lambda: "off")
    assert throughput.slowdown() == (OLLAMA_MAX_SLOWDOWN, OLLAMA_MAX_SLOWDOWN)


# ── L'attente annoncée au lecteur ────────────────────────────────────────────


def test_a_fast_machine_announces_nothing():
    assert llm_models.wait_estimate_s("assistant_answer") is None


def test_economy_announces_the_total_budget(economy):
    assert llm_models.wait_estimate_s("assistant_answer") == round(task_wall_timeout_s("assistant_answer"))


def test_a_machine_revealed_slow_announces_it_too():
    _slow_machine(LLM_REFERENCE_PROFILE.tokens_per_s / 3)
    estimate = llm_models.wait_estimate_s("question")
    assert estimate == round(task_wall_timeout_s("question"))
    assert estimate > 2 * 60


def test_status_says_why_economy_is_on(monkeypatch):
    monkeypatch.setattr(ollama_client, "list_models", lambda: [{"name": "qwen3:1.7b", "size": 1_400_000_000}])
    monkeypatch.setattr(llm_models, "host_ram_gb", lambda: 4.0)
    llm_models.invalidate()
    state = llm_models.status()
    assert state["model"] == "qwen3:1.7b" and state["tier"] == "tiny"
    assert state["economy"] is True and state["economy_reason"] == "tiny_model"
    assert state["economy_preference"] == "auto"
    assert state["supports_images"] is False


# ── La file : le travail de fond ne part pas ─────────────────────────────────


def test_the_background_list_spares_what_the_student_waits_for():
    for kept in ("lang_writing_feedback", "lang_episode_hook", "calibration", "assistant_answer"):
        assert kept not in OLLAMA_BACKGROUND_TASKS
    assert set(OLLAMA_BACKGROUND_TASKS) <= set(OLLAMA_TASK_OPTIONS)


def _run_task(label: str, prompt: str = "prompt", parser=lambda raw: raw) -> dict:
    done = threading.Event()
    box: dict = {}

    def ok(result):
        box["result"] = result
        done.set()

    def err(message):
        box["error"] = message
        done.set()

    ollama_client._run_json_async(label, prompt, parser, ok, err, "")
    assert done.wait(10)
    return box


def test_an_episode_task_is_suspended_without_calling_the_model(economy):
    calls = []
    economy.setattr(ollama_client, "_generate_json", lambda *a, **kw: calls.append(a) or {"x": 1})
    box = _run_task("lang_episode_text")
    assert ollama_client.is_suspended_error(box.get("error"))
    assert not calls


def test_a_document_digest_falls_back_to_the_local_heuristic(economy):
    """La fiche d'un document importé : même repli que hors ligne, tout de
    suite, sans appel au modèle — la recherche de la bibliothèque reste utile."""
    from llm.prompts import build_document_digest_prompt
    from llm.schema_json import parse_document_digest

    calls = []
    economy.setattr(ollama_client, "_generate_json", lambda *a, **kw: calls.append(a) or {"x": 1})
    excerpt = "La photosynthèse transforme la lumière en énergie chimique dans les chloroplastes. " * 5
    box = _run_task("document_digest", build_document_digest_prompt("biologie", excerpt), parse_document_digest)
    assert "error" not in box and box["result"].get("keywords")
    assert not calls


def test_what_the_student_waits_for_still_runs(economy):
    calls = []
    economy.setattr(ollama_client, "_generate_json", lambda *a, **kw: calls.append(a[0]) or {"x": 1})
    for label in ("lang_writing_feedback", "lang_episode_hook", "assistant_answer"):
        assert _run_task(label).get("result") == {"x": 1}
    assert calls == ["lang_writing_feedback", "lang_episode_hook", "assistant_answer"]


def test_off_suspends_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(ollama_client, "_generate_json", lambda *a, **kw: calls.append(a[0]) or {"x": 1})
    assert _run_task("lang_episode_text").get("result") == {"x": 1}
    assert calls == ["lang_episode_text"]


# ── Un modèle sans vision ne reçoit pas l'image ──────────────────────────────


def test_the_page_image_is_dropped_before_the_call_for_a_model_without_vision(monkeypatch, tmp_path):
    image = tmp_path / "page.png"
    image.write_bytes(b"\x89PNG fake")
    seen = []

    def fake_call(prompt, model, images=None, options=None, format_json=True, task=""):
        seen.append(images)
        return '{"ok": true}'

    monkeypatch.setattr(ollama_client, "_call_ollama", fake_call)
    ollama_client._generate_json("question", "p", lambda raw: {"ok": True}, model="qwen3:1.7b",
                                 image_paths=[str(image)])
    ollama_client._generate_json("question", "p", lambda raw: {"ok": True}, model="gemma4:e4b",
                                 image_paths=[str(image)])
    assert seen[0] == [] and len(seen[1]) == 1


def test_the_reader_does_not_even_render_the_page_for_a_model_without_vision(monkeypatch):
    from services import assistant, library

    rendered = []
    monkeypatch.setattr(library, "render_page", lambda *a, **kw: rendered.append(a) or "/tmp/x.png")
    monkeypatch.setattr(assistant, "_served_as_text_blocks", lambda *a: False)
    monkeypatch.setattr(llm_models, "active_profile", lambda: TINY)
    assert assistant._page_image_paths(1, 1) == []
    assert not rendered


# ── Ni aide autonome, ni embeddings ──────────────────────────────────────────


def _policy_asks(monkeypatch) -> bool:
    """Une politique dont tous les seuils sont tombés (attention basse, page
    lue depuis assez longtemps) : demande-t-elle une décision à Clikoda ?"""
    from services import intervention
    from services.intervention import AssistantInterventionPolicy
    from services.session_memory import SessionMemory

    modes = ("discret", "normal", "coach")
    monkeypatch.setattr(intervention, "ASSISTANT_DWELL_TRIGGER_S", dict.fromkeys(modes, 0.0))
    monkeypatch.setattr(intervention, "ASSISTANT_WARMUP_S", dict.fromkeys(modes, 0.0))
    memory = SessionMemory()
    memory.on_page_view(1)
    asked = []
    policy = AssistantInterventionPolicy(
        memory, lambda: "coach", lambda: {"attention": 10.0}, lambda: 1, lambda _p: "texte",
        lambda ctx, done: asked.append(ctx), lambda payload: None,
    )
    policy.start_reading()
    policy._opened_at = -1e9  # warm-up écoulé
    policy.tick()
    return bool(asked)


def test_no_autonomous_help_in_economy(monkeypatch):
    assert _policy_asks(monkeypatch)  # témoin : hors mode économe, elle demande
    monkeypatch.setattr(llm_models, "economy_preference", lambda: "on")
    assert not _policy_asks(monkeypatch)


def test_no_embeddings_in_economy(monkeypatch):
    """Le modèle d'embeddings se chargerait À CÔTÉ de celui de Clikoda : la
    recherche reste lexicale, à l'ouverture du lecteur comme à la question."""
    from services import pdf_rag

    vectors = []
    monkeypatch.setattr(pdf_rag, "_build_index", lambda doc_id: {"chunks": [{"page": 1, "text": "x"}]})
    monkeypatch.setattr(pdf_rag, "_ensure_vectors", lambda *a, **kw: vectors.append(a))
    pdf_rag.warm_index(1)
    assert len(vectors) == 1  # témoin : hors mode économe, l'indexation part
    monkeypatch.setattr(llm_models, "economy_preference", lambda: "on")
    pdf_rag.warm_index(1)
    assert len(vectors) == 1


# ── La mémoire : le message nomme le modèle et SA RAM ────────────────────────


def test_the_out_of_memory_message_names_the_model_and_its_ram():
    with pytest.raises(ollama_client.ModelOutOfMemory) as caught:
        ollama_client._raise_if_out_of_memory("model requires more system memory (2.1 GiB) than is available "
                                              "(1.0 GiB)", "qwen3:1.7b")
    message = str(caught.value)
    assert "qwen3:1.7b" in message and "4" in message
    assert "16" not in message
