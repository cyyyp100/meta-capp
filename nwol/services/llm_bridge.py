# services/llm_bridge.py — Pont synchrone pour appeler le LLM depuis un endpoint REST.
#
# Les fonctions LLM sont asynchrones (callbacks on_success/on_error sur le thread
# worker Ollama). Dans un endpoint FastAPI *synchrone* (exécuté dans le threadpool),
# on bloque jusqu'à la réponse via un Event. À ne pas utiliser dans la boucle asyncio.
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from llm.ollama_client import close_caller_slot, open_caller_slot

logger = logging.getLogger("services.llm_bridge")

# Budget d'attente quand la tâche n'en a pas publié (appel qui ne passe pas par
# la file LLM : tests, callbacks immédiats). Le chemin normal reçoit le budget
# réel de sa tâche via le CallerSlot.
DEFAULT_WAIT_S = 90.0


def run_llm_sync(call: Callable[[Callable, Callable], None], timeout: float | None = None) -> Any:
    """`call(on_success, on_error)` lance le LLM ; renvoie le résultat ou lève.

    Le temps d'attente n'est PAS choisi ici : la fonction `*_async` publie dans
    le `CallerSlot` le budget dérivé du `num_predict` de sa tâche
    (`config.settings.task_timeout_s`), qui est aussi le timeout socket. Un seul
    nombre, un seul endroit — attendre moins longtemps que la socket revenait à
    jeter une génération sur le point d'aboutir, attendre plus longtemps était
    une échéance que personne n'atteignait jamais.

    Sur timeout, on lève le drapeau d'abandon : il n'y a qu'UN worker LLM, et
    une tâche encore en file dont plus personne ne veut le résultat retarderait
    tout ce qui suit.
    """
    box: dict[str, Any] = {}
    done = threading.Event()

    def on_success(result: Any) -> None:
        box["result"] = result
        done.set()

    def on_error(message: Any) -> None:
        box["error"] = str(message)
        done.set()

    slot = open_caller_slot()
    try:
        call(on_success, on_error)
    finally:
        close_caller_slot()

    wait_s = slot.timeout_s or timeout or DEFAULT_WAIT_S
    if not done.wait(wait_s):
        slot.abandon.set()
        logger.warning("LLM timeout après %.0f s — tâche abandonnée", wait_s)
        raise TimeoutError("LLM timeout")
    if "error" in box:
        raise RuntimeError(box["error"])
    return box.get("result")
