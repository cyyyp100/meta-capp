# services/llm_provider.py — Abstraction du fournisseur LLM.
#
# Point d'insertion UNIQUE : `llm/ollama_client._call_ollama` délègue ici.
# Cette édition est 100 % locale : le seul fournisseur est **Ollama**, sur
# 127.0.0.1 — aucune génération ne sort de la machine.
# Le streaming token-par-token n'existe pas sur cette édition : les 4 fonctions
# *_stream_async d'ollama_client sont du code legacy sans appelant (vérifié) —
# l'abstraction ne couvre donc QUE les générations synchrones.
from __future__ import annotations

import logging

logger = logging.getLogger("services.llm_provider")

PROVIDERS = ("ollama",)

_provider_override: str | None = None


class ProviderNotConfigured(RuntimeError):
    pass


def set_provider(name: str | None) -> None:
    """Force le fournisseur ; None = retour au défaut."""
    global _provider_override
    _provider_override = name if name in PROVIDERS else None


def active_provider() -> str:
    return "ollama"


def generate(
    prompt: str,
    model: str,
    images: list[str] | None = None,
    options: dict | None = None,
    format_json: bool = True,
    task: str = "",
) -> str:
    """Génération synchrone via Ollama local.

    `task` n'est pas que de l'observabilité : il porte le budget temps de la
    tâche (`settings.task_timeout_s`), appliqué au timeout socket."""
    return _ollama_generate(prompt, model=model, images=images, options=options, format_json=format_json, task=task)


def _ollama_generate(prompt: str, model: str, images, options, format_json: bool, task: str = "") -> str:
    # Import au call-time : évite l'import circulaire (ollama_client délègue ici).
    from llm.ollama_client import _call_ollama_http

    return _call_ollama_http(prompt, model, images=images, options=options, format_json=format_json, task=task)
