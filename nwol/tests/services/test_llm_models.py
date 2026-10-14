"""Quel modèle fait tourner Clikoda (services/llm_models).

Le modèle était un nom en dur, figé dans 31 valeurs par défaut d'argument
évaluées à l'import : sur une machine qui ne pouvait pas le charger, Clikoda se
taisait sans jamais dire pourquoi. Ces tests figent la politique : le plus
capable de ceux qui sont installés ET que la machine tient, un choix explicite
respecté même mauvais, et JAMAIS de silence — il y a toujours un nom à citer.

La décision se teste sans serveur et sans base : `auto_pick` et `resolve` sont
pures, et c'est délibéré.
"""
from __future__ import annotations

import pytest

from config.settings import LLM_MODEL_AUTO, LLM_MODELS, LLM_REFERENCE_PROFILE, OLLAMA_MODEL
from services import llm_models


# ── La politique, sans HTTP ni base ──────────────────────────────────────────


def test_auto_takes_the_best_ranked_model_the_machine_can_hold():
    installed = ["gemma4:e2b", "gemma4:e4b", "gemma4:12b"]
    # 16 Gio : les trois tiennent -> le mieux classé. Et PAS le plus petit
    # téléchargement : 12b pèse 8,0 Go contre 9,6 à e4b, tout en répondant mieux.
    assert llm_models.auto_pick(installed, 16.0) == "gemma4:12b"
    assert LLM_MODELS["gemma4:12b"].download_gb < LLM_MODELS["gemma4:e4b"].download_gb


def test_auto_refuses_a_model_the_machine_cannot_load():
    """8 Gio : `gemma4:e2b` tient, les deux autres non. Un 12b sur une telle
    machine swappe et son premier token prend des minutes."""
    assert llm_models.auto_pick(["gemma4:e2b", "gemma4:12b"], 8.0) == "gemma4:e2b"


def test_auto_falls_back_to_the_smallest_rather_than_to_silence():
    """Aucun installé ne tient : on prend le plus petit et `status()` dit
    pourquoi c'est lent. Pas de Clikoda du tout serait pire."""
    assert llm_models.auto_pick(["gemma4:e4b", "gemma4:12b"], 8.0) == "gemma4:e4b"
    assert llm_models.resolve("auto", ["gemma4:e4b"], 8.0)["reason"] == "model_too_big"


def test_unknown_ram_is_not_a_refusal():
    """`host_ram_gb()` peut rendre None. Traité comme 0, il refuserait TOUT."""
    assert llm_models.auto_pick(["gemma4:e2b", "gemma4:31b"], None) == "gemma4:31b"
    assert llm_models.fits("gemma4:31b", None) is True
    assert llm_models.resolve("auto", ["gemma4:31b"], None)["reason"] is None


def test_a_model_the_table_ignores_is_not_a_candidate():
    """Un modèle tiré à la main (`llama3:8b`) n'a ni débit ni RAM déclarés : le
    choix automatique ne peut rien en dire, donc il ne le choisit pas."""
    assert llm_models.auto_pick(["llama3:8b"], 16.0) == ""
    resolution = llm_models.resolve("auto", ["llama3:8b"], 16.0)
    assert resolution["model"] == OLLAMA_MODEL
    assert resolution["reason"] == "no_model"


def test_an_explicit_choice_wins_even_when_auto_would_do_better():
    resolution = llm_models.resolve("gemma4:e2b", ["gemma4:e2b", "gemma4:12b"], 16.0)
    assert resolution["model"] == "gemma4:e2b"
    assert resolution["reason"] is None


def test_an_explicit_choice_that_is_not_installed_says_so_and_still_answers():
    """Le cas du premier lancement : la préférence nomme un modèle jamais tiré.
    On replie sur le choix automatique ET on garde le nom manquant — c'est lui
    que la commande `ollama pull` doit citer."""
    resolution = llm_models.resolve("gemma4:31b", ["gemma4:e4b"], 16.0)
    assert resolution["model"] == "gemma4:e4b"
    assert resolution["reason"] == "model_missing"
    assert resolution["requested_missing"] == "gemma4:31b"


def test_resolution_never_answers_auto_nor_nothing():
    for names in ([], ["gemma4:e4b"], ["llama3:8b"]):
        for pref in (LLM_MODEL_AUTO, "gemma4:26b"):
            model = llm_models.resolve(pref, names, 4.0)["model"]
            assert model and model != LLM_MODEL_AUTO


def test_latest_is_not_a_tag():
    """Ollama suffixe `:latest` ce qui n'a pas de tag. Sans normalisation,
    `embeddinggemma:latest` et un futur `x:latest` ne seraient jamais reconnus."""
    assert llm_models.resolve("auto", ["gemma4:e4b:latest"], 16.0)["model"] == "gemma4:e4b"


def test_an_unknown_model_keeps_the_reference_profile():
    """Jamais None : les budgets temps d'un modèle inconnu doivent rester définis."""
    assert llm_models.profile("llama3:8b") is LLM_REFERENCE_PROFILE
    assert llm_models.tier("llama3:8b") == LLM_REFERENCE_PROFILE.tier


# ── La machine ───────────────────────────────────────────────────────────────


def test_host_ram_is_a_number_or_an_honest_unknown(reference_model):
    # La VRAIE mesure : la fixture autouse la fige à « inconnue » pour le reste
    # de la suite (le mode économe en dépend).
    ram = reference_model.host_ram_gb()
    assert ram is None or (isinstance(ram, float) and ram > 0.5)
    assert reference_model.host_ram_gb() == ram  # mémoïsé, une mesure par processus


# ── Le catalogue d'Ollama ────────────────────────────────────────────────────


def test_the_catalog_is_asked_once_per_ttl(monkeypatch):
    """`active()` est appelé à CHAQUE génération et à chaque calcul de budget :
    un aller-retour HTTP par appel serait payé par l'étudiant qui attend."""
    from llm import ollama_client

    calls = []

    def fake_tags():
        calls.append(1)
        return [{"name": "gemma4:e4b", "size": 9_600_000_000, "details": {"parameter_size": "8.0B"}}]

    monkeypatch.setattr(ollama_client, "list_models", fake_tags)
    llm_models.invalidate()
    for _ in range(5):
        assert llm_models.active() == "gemma4:e4b"
    assert len(calls) == 1
    assert llm_models.installed()[0]["known"] is True
    assert llm_models.installed()[0]["size_gb"] == pytest.approx(8.9, abs=0.1)  # Gio, pas Go
    # `refresh_active()` est la seule à redemander (après une écriture du réglage).
    llm_models.refresh_active()
    assert len(calls) == 2


def test_nothing_raises_when_ollama_is_off(monkeypatch):
    """Un budget temps, une génération et l'écran de réglages n'ont pas le droit
    d'échouer parce qu'Ollama est éteint."""
    from llm import ollama_client

    monkeypatch.setattr(ollama_client, "list_models", lambda: None)
    llm_models.invalidate()
    state = llm_models.status()
    assert state["ollama_up"] is False
    assert state["available"] is False
    assert state["reason"] == "ollama_down"
    assert state["model"] == OLLAMA_MODEL  # un nom à citer, et des budgets définis
    assert state["pull_command"] == f"ollama pull {OLLAMA_MODEL}"
    assert llm_models.active() == OLLAMA_MODEL
    assert llm_models.active_profile() is LLM_REFERENCE_PROFILE


def test_ollama_up_without_any_model_is_not_the_same_failure(monkeypatch):
    """Deux pannes, deux phrases : « Ollama ne répond pas » et « aucun modèle
    installé » n'appellent pas le même geste."""
    from llm import ollama_client

    monkeypatch.setattr(ollama_client, "list_models", lambda: [])
    llm_models.invalidate()
    state = llm_models.status()
    assert state["ollama_up"] is True
    assert state["available"] is False
    assert state["reason"] == "no_model"


def test_status_describes_the_catalog_for_the_settings_screen(monkeypatch):
    from llm import ollama_client

    monkeypatch.setattr(ollama_client, "list_models", lambda: [{"name": "gemma4:e2b", "size": 7_200_000_000}])
    monkeypatch.setattr(llm_models, "host_ram_gb", lambda: 8.0)
    monkeypatch.setattr(llm_models, "preference", lambda: "gemma4:e2b")
    llm_models.invalidate()
    state = llm_models.status()
    assert state["model"] == "gemma4:e2b" and state["available"] is True
    assert state["preference"] == "gemma4:e2b" and state["reason"] is None
    assert state["tier"] == "small" and state["supports_images"] is True
    assert state["ram_gb"] == 8.0 and state["fits"] is True
    # Le catalogue entier est servi : un modèle non installé reste CHOISISSABLE
    # (rien n'est bloqué), avec ce qu'il coûterait et s'il tiendrait.
    catalog = {entry["name"]: entry for entry in state["catalog"]}
    assert set(catalog) == set(LLM_MODELS)
    assert catalog["gemma4:31b"]["installed"] is False
    assert catalog["gemma4:31b"]["fits"] is False
    assert catalog["gemma4:e2b"]["fits"] is True
    assert state["throughput"]["model"] == "gemma4:e2b"
