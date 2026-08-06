# services/llm_bridge.py — Pont synchrone pour appeler le LLM depuis un endpoint REST.
#
# Les fonctions LLM sont asynchrones (callbacks on_success/on_error sur le thread
# worker Ollama). Dans un endpoint FastAPI *synchrone* (exécuté dans le threadpool),
# on bloque jusqu'à la réponse via un Event. À ne pas utiliser dans la boucle asyncio.
from __future__ import annotations

import threading
from typing import Any, Callable


def run_llm_sync(call: Callable[[Callable, Callable], None], timeout: float = 90.0) -> Any:
    """`call(on_success, on_error)` lance le LLM ; renvoie le résultat ou lève."""
    box: dict[str, Any] = {}
    done = threading.Event()

    def on_success(result: Any) -> None:
        box["result"] = result
        done.set()

    def on_error(message: Any) -> None:
        box["error"] = str(message)
        done.set()

    call(on_success, on_error)
    if not done.wait(timeout):
        raise TimeoutError("LLM timeout")
    if "error" in box:
        raise RuntimeError(box["error"])
    return box.get("result")
