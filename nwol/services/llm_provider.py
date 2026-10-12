# services/llm_provider.py — Abstraction du fournisseur LLM.
#
# Point d'insertion UNIQUE : `llm/ollama_client._call_ollama` délègue ici.
# Cette édition est 100 % locale : le seul fournisseur est **Ollama**, sur
# 127.0.0.1 — aucune génération ne sort de la machine. L'abstraction ne couvre
# que les générations synchrones (aucun streaming token par token).
from __future__ import annotations


def generate(
    prompt: str,
    model: str,
    images: list[str] | None = None,
    options: dict | None = None,
    format_json: bool | dict = True,
    task: str = "",
) -> str:
    """Génération synchrone via Ollama local.

    `task` n'est pas que de l'observabilité : il porte le budget temps de la
    tâche (`settings.task_timeout_s`), appliqué au timeout socket."""
    return _ollama_generate(prompt, model=model, images=images, options=options, format_json=format_json, task=task)


def _ollama_generate(prompt: str, model: str, images, options, format_json: bool | dict, task: str = "") -> str:
    # Import au call-time : évite l'import circulaire (ollama_client délègue ici).
    from llm.ollama_client import _call_ollama_http

    return _call_ollama_http(prompt, model, images=images, options=options, format_json=format_json, task=task)
