"""`GET /api/llm/status` — l'application dit enfin si Clikoda est là.

La pastille « Connecté à Clikoda » ne reflétait que le WebSocket du lecteur :
elle restait verte avec Ollama éteint, et rien dans l'interface ne nommait le
modèle manquant. `orchestrator.llm_status()` existait et personne ne l'appelait.

Ces tests figent les deux choses qui comptent : les quatre raisons sont
distinctes (on ne dit pas « modèle absent » quand Ollama est muet), et la sonde
de démarrage `/api/health` reste à l'écart — c'est elle que la coque desktop
interroge en boucle avant d'ouvrir la fenêtre.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def ollama(monkeypatch):
    """Le magasin d'Ollama et la RAM de la machine, choisis par le test."""
    from llm import ollama_client
    from services import llm_models

    state: dict = {"models": [{"name": "gemma4:e4b", "size": 9_600_000_000}], "ram": 16.0, "pref": "auto"}
    monkeypatch.setattr(ollama_client, "list_models", lambda: state["models"])
    monkeypatch.setattr(llm_models, "host_ram_gb", lambda: state["ram"])
    monkeypatch.setattr(llm_models, "preference", lambda: state["pref"])
    llm_models.invalidate()
    yield state
    llm_models.invalidate()


def test_status_names_the_model_that_runs(client, ollama):
    res = client.get("/api/llm/status")
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is True and body["ollama_up"] is True
    assert body["model"] == "gemma4:e4b"
    assert body["preference"] == "auto" and body["reason"] is None
    assert body["ram_gb"] == 16.0 and body["fits"] is True
    assert body["pull_command"] == "ollama pull gemma4:e4b"


def test_auto_takes_the_only_installed_model(client, ollama):
    ollama["models"] = [{"name": "gemma4:e2b", "size": 7_200_000_000}]
    body = client.get("/api/llm/status").json()
    assert body["model"] == "gemma4:e2b" and body["tier"] == "small"
    assert [entry["name"] for entry in body["installed"]] == ["gemma4:e2b"]


def test_ollama_down_is_said_as_such(client, ollama):
    ollama["models"] = None  # la requête /api/tags n'a pas abouti
    body = client.get("/api/llm/status").json()
    assert body["ollama_up"] is False and body["available"] is False
    assert body["reason"] == "ollama_down"
    assert body["model"]  # un nom à citer, et des budgets temps définis


def test_a_chosen_model_that_was_never_pulled_is_named(client, ollama):
    ollama["pref"] = "gemma4:31b"
    body = client.get("/api/llm/status").json()
    assert body["reason"] == "model_missing"
    assert body["requested_missing"] == "gemma4:31b"
    assert body["model"] == "gemma4:e4b"  # ce qui tourne en attendant
    assert body["available"] is True
    # La commande cite ce qui MANQUE, pas le repli.
    assert body["pull_command"] == "ollama pull gemma4:31b"


def test_a_machine_too_small_is_said_without_blocking_anything(client, ollama):
    """4 Gio et seulement un 31b installé : Clikoda répondra mal, mais
    l'application le DIT au lieu de se taire — et ne désactive rien."""
    ollama["models"] = [{"name": "gemma4:31b", "size": 20_000_000_000}]
    ollama["ram"] = 4.0
    body = client.get("/api/llm/status").json()
    assert body["model"] == "gemma4:31b"
    assert body["reason"] == "model_too_big" and body["fits"] is False
    catalog = {entry["name"]: entry for entry in body["catalog"]}
    assert catalog["gemma4:e2b"]["fits"] is False  # 8 Gio exigés
    assert all("download_gb" in entry for entry in body["catalog"])


def test_an_unknown_ram_is_not_a_refusal(client, ollama):
    ollama["ram"] = None
    body = client.get("/api/llm/status").json()
    assert body["ram_gb"] is None
    assert body["fits"] is True and body["reason"] is None


def test_the_startup_probe_stays_free_of_ollama(client, ollama):
    """`/api/health` est interrogée en boucle AVANT l'ouverture de la fenêtre :
    elle ne doit rien demander à un service tiers."""
    ollama["models"] = None
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "version": res.json()["version"]}
    assert "model" not in res.json()


def test_the_endpoint_takes_no_input(client, ollama):
    """Un endpoint local qui accepterait un nom de modèle serait un second
    chemin d'écriture pour un réglage qui n'en a qu'un (`POST /api/preferences`)."""
    assert client.post("/api/llm/status", json={"model": "x"}).status_code == 405
    body = client.get("/api/llm/status?model=gemma4:31b").json()
    assert body["model"] == "gemma4:e4b"  # le paramètre n'existe pas


def test_the_preference_decides_and_the_status_follows(client, ollama, monkeypatch, reference_model):
    """Bout en bout : l'interface écrit le réglage par le SEUL chemin d'écriture
    (`POST /api/preferences`), et l'état suit. C'est ce que fait l'écran
    Réglages, et c'est pourquoi `/api/llm/status` n'a pas besoin d'entrée."""
    from services import llm_models

    ollama["models"] = [
        {"name": "gemma4:e2b", "size": 7_200_000_000},
        {"name": "gemma4:e4b", "size": 9_600_000_000},
    ]
    # La vraie lecture du réglage, cette fois : c'est tout l'objet du test.
    monkeypatch.setattr(llm_models, "preference", reference_model.preference)
    assert client.get("/api/llm/status").json()["model"] == "gemma4:e4b"  # auto : le mieux classé

    # Le vocabulaire est servi à l'interface sans qu'elle le connaisse.
    choices = client.get("/api/preferences").json()["choices"]["llm_model"]
    assert choices[0] == "auto" and "gemma4:e2b" in choices

    res = client.post("/api/preferences", json={"llm_model": "gemma4:e2b"})
    assert res.status_code == 200
    assert res.json()["preferences"]["llm_model"] == "gemma4:e2b"
    assert client.get("/api/llm/status").json()["model"] == "gemma4:e2b"

    # Une valeur hors du catalogue est refusée, pas persistée en silence.
    assert client.post("/api/preferences", json={"llm_model": "gpt-5"}).status_code == 400
    assert client.get("/api/llm/status").json()["model"] == "gemma4:e2b"


def test_a_4_gb_machine_runs_the_tiny_tier_in_economy(client, ollama):
    """La machine du lot 2 : seul `qwen3:1.7b` tient. Le choix automatique le
    prend, le mode économe s'active de lui-même, et l'état dit pourquoi."""
    ollama["models"] = [
        {"name": "qwen3:1.7b", "size": 1_400_000_000},
        {"name": "gemma4:e4b", "size": 9_600_000_000},
    ]
    ollama["ram"] = 4.0
    body = client.get("/api/llm/status").json()
    assert body["model"] == "qwen3:1.7b" and body["tier"] == "tiny"
    assert body["reason"] is None and body["fits"] is True
    assert body["economy"] is True and body["economy_reason"] == "tiny_model"
    assert body["economy_preference"] == "auto"
    assert body["supports_images"] is False
    catalog = {entry["name"]: entry for entry in body["catalog"]}
    assert catalog["qwen3:1.7b"]["fits"] is True and catalog["gemma4:e2b"]["fits"] is False


def test_economy_is_forced_both_ways_through_the_one_write_path(client, ollama, monkeypatch, reference_model):
    """Une machine de 4 Go qui préfère attendre que perdre l'aide autonome, une
    de 16 Go qui veut économiser : `POST /api/preferences`, et l'état suit."""
    from services import llm_models

    monkeypatch.setattr(llm_models, "economy_preference", reference_model.economy_preference)
    choices = client.get("/api/preferences").json()["choices"]["llm_economy"]
    assert choices == ["auto", "on", "off"]
    assert client.get("/api/llm/status").json()["economy"] is False  # 16 Go, gemma4:e4b

    assert client.post("/api/preferences", json={"llm_economy": "on"}).status_code == 200
    body = client.get("/api/llm/status").json()
    assert body["economy"] is True and body["economy_reason"] == "preference"

    ollama["models"] = [{"name": "qwen3:1.7b", "size": 1_400_000_000}]
    ollama["ram"] = 4.0
    assert client.post("/api/preferences", json={"llm_economy": "off"}).status_code == 200
    body = client.get("/api/llm/status").json()
    assert body["model"] == "qwen3:1.7b" and body["economy"] is False and body["economy_reason"] is None
    assert client.post("/api/preferences", json={"llm_economy": "maybe"}).status_code == 400


def test_the_status_exposes_the_fluency_verdicts(client, ollama):
    body = client.get("/api/llm/status").json()
    assert body["auto_set_aside"] == []
    assert body["auto_min_output_tokens_per_s"] == 15.0
    assert all(entry["too_slow"] is False for entry in body["installed"] + body["catalog"])


# ── « Automatique » = le plus capable qui reste fluide (judge_fluency) ───────
#
# La RAM ne départage pas e4b et 12b (12 Go chacun) : sur le M4 de 16 Go, le
# 12b écrit à 11,9 tokens/s et e4b à 29,7 (2026-10-15). Le calibrage tranche.


def _measured(model: str, output_tps: float, prompt_tps: float = 89.0) -> None:
    """Un calibrage simulé : Ollama a rendu ces durées pour `model`."""
    from llm import throughput

    throughput.record_call({
        "eval_count": 64, "eval_duration": int(64 / output_tps * 1e9),
        "prompt_eval_count": 300, "prompt_eval_duration": int(300 / prompt_tps * 1e9),
    }, model)


@pytest.fixture
def fluency(client, ollama, monkeypatch, reference_model):
    """Les VRAIS verdicts, sur la base isolée de `client` ; le calibrage et le
    déchargement sont des espions (aucun Ollama)."""
    import threading
    from types import SimpleNamespace

    from llm import ollama_client
    from services import llm_models

    # Le démarrage du serveur lance `refresh_active` dans un thread (server/app) :
    # fini avant les espions, il ne s'y mêle pas.
    for thread in threading.enumerate():
        if thread.name == "llm-startup":
            thread.join(timeout=5)
    monkeypatch.setattr(llm_models, "set_aside", reference_model.set_aside)
    monkeypatch.setattr(llm_models, "judge_fluency", reference_model.judge_fluency)
    monkeypatch.setattr(llm_models, "_calibrated", set())
    spies = SimpleNamespace(calibrated=[], unloaded=[])
    monkeypatch.setattr(ollama_client, "calibrate_throughput", lambda: spies.calibrated.append(llm_models.active()))
    monkeypatch.setattr(ollama_client, "unload_model", spies.unloaded.append)
    ollama["models"] = [
        {"name": "qwen3:1.7b", "size": 1_400_000_000},
        {"name": "gemma4:e4b", "size": 9_600_000_000},
        {"name": "gemma4:12b", "size": 8_000_000_000},
    ]
    llm_models.invalidate()
    return spies


def _verdicts() -> dict:
    import json

    from db.app_settings import get_setting

    return json.loads(get_setting("llm_auto_set_aside") or "{}")


def test_a_model_too_slow_here_is_set_aside_and_replaced(client, ollama, fluency):
    from services import llm_models

    assert llm_models.active() == "gemma4:12b"
    _measured("gemma4:12b", 11.9)
    llm_models.judge_fluency("gemma4:12b")

    assert llm_models.active() == "gemma4:e4b"
    assert fluency.calibrated == ["gemma4:e4b"]  # le suivant est calibré à son tour
    assert fluency.unloaded == ["gemma4:12b"]  # 12b et e4b ne tiennent pas ensemble
    verdict = _verdicts()["gemma4:12b"]
    assert verdict["output_tokens_per_s"] == pytest.approx(11.9, abs=0.1)
    assert verdict["ram_gb"] == 16.0

    body = client.get("/api/llm/status").json()
    assert body["model"] == "gemma4:e4b"
    assert [entry["model"] for entry in body["auto_set_aside"]] == ["gemma4:12b"]
    assert body["auto_set_aside"][0]["prompt_tokens_per_s"] == pytest.approx(89.0, abs=1)
    assert body["auto_set_aside"][0]["measured_at"]
    catalog = {entry["name"]: entry for entry in body["catalog"]}
    assert catalog["gemma4:12b"]["too_slow"] is True and catalog["gemma4:e4b"]["too_slow"] is False
    # Au relancement, plus de calibrage du 12b : le verdict est en base.
    assert fluency.calibrated == ["gemma4:e4b"]


def test_a_model_measured_above_the_floor_is_rehabilitated(client, ollama, fluency):
    from services import llm_models

    _measured("gemma4:12b", 11.9)
    llm_models.judge_fluency("gemma4:12b")
    assert llm_models.active() == "gemma4:e4b"

    from llm import throughput

    throughput.reset("gemma4:12b")
    _measured("gemma4:12b", 21.0)  # mesuré branché, hors économie d'énergie
    llm_models.judge_fluency("gemma4:12b")
    assert _verdicts() == {}
    assert llm_models.active() == "gemma4:12b"


def test_an_explicit_choice_is_noted_but_not_switched(client, ollama, fluency):
    from services import llm_models

    ollama["pref"] = "gemma4:12b"
    _measured("gemma4:12b", 11.9)
    llm_models.judge_fluency("gemma4:12b")
    assert "gemma4:12b" in _verdicts()  # le fait est noté…
    assert llm_models.active() == "gemma4:12b"  # …le choix respecté
    assert fluency.calibrated == [] and fluency.unloaded == []

    ollama["pref"] = "auto"  # retour à « Automatique » : e4b
    llm_models.invalidate()
    assert llm_models.active() == "gemma4:e4b"


def test_an_unreadable_database_neither_raises_nor_sets_anything_aside(client, ollama, fluency, monkeypatch):
    from db import app_settings
    from services import llm_models

    def _locked(*_args, **_kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(app_settings, "get_setting", _locked)
    monkeypatch.setattr(app_settings, "set_setting", _locked)
    llm_models.invalidate()
    _measured("gemma4:12b", 11.9)
    llm_models.judge_fluency("gemma4:12b")  # ne lève pas
    assert llm_models.set_aside(16.0) == {}
    assert llm_models.active() == "gemma4:12b"
    assert client.get("/api/llm/status").status_code == 200
