# services/lifecycle.py — Arrêt du serveur quand l'app vit dans un navigateur.
#
# Fenêtre native : la fermer arrête tout, la coque s'en charge. Navigateur
# (desktop/pywebview_main._run_in_browser) : le navigateur et le serveur sont
# deux programmes, fermer l'onglet ne dit rien au serveur, et un binaire lancé
# d'un double-clic n'a pas de terminal où faire Ctrl+C. Le serveur — et le
# modèle qu'Ollama garde chargé pour lui — restaient en mémoire jusqu'au
# redémarrage de la machine.
#
# Deux sorties, une seule fonction d'arrêt (celle que la coque fournit) :
#   * « Quitter Meta-Capp » (`quit_app`) : coupe aussi les générations en cours ;
#   * l'arrêt automatique (`_watch`) : aucun onglet ouvert depuis
#     BROWSER_AUTO_STOP_S, et Clikoda au repos depuis BROWSER_LLM_QUIET_S.
#
# Un onglet ouvert, pas un utilisateur actif : un élève peut lire vingt minutes
# sans rien toucher. Chaque onglet tient un WebSocket de présence
# (`server/routers/shell.py`) — un navigateur bride les minuteries d'un onglet
# en arrière-plan (jusqu'à une par minute dans Chrome), il ne ferme pas ses sockets.
#
# Hors mode navigateur (fenêtre native, `python -m server.main`, tests), rien
# n'est activé : la présence est comptée sans effet, et Quitter est refusé.
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from config.settings import BROWSER_AUTO_STOP_S, BROWSER_LLM_QUIET_S, BROWSER_WATCH_INTERVAL_S

logger = logging.getLogger("services.lifecycle")

_LOCK = threading.Lock()
_stop: Callable[[], None] | None = None
_tabs = 0
# Depuis quand aucun onglet n'est ouvert (horloge monotone).
_alone_since = time.monotonic()


def enable_browser_mode(stop: Callable[[], None], watch: bool = True) -> None:
    """La coque sert l'app au navigateur : `stop` arrête le serveur.

    Le compte à rebours part d'ici : si le navigateur ne s'ouvre jamais (aucun
    navigateur par défaut, pas de terminal où lire l'adresse), le serveur ne
    reste pas indéfiniment en mémoire. `watch=False` : tests."""
    global _stop, _alone_since
    with _LOCK:
        _stop = stop
        _alone_since = time.monotonic()
    if watch:
        threading.Thread(target=_watch, daemon=True, name="browser-auto-stop").start()


def browser_mode() -> bool:
    with _LOCK:
        return _stop is not None


def tab_opened() -> None:
    global _tabs
    with _LOCK:
        _tabs += 1


def tab_closed() -> None:
    global _tabs, _alone_since
    with _LOCK:
        _tabs = max(0, _tabs - 1)
        if _tabs == 0:
            _alone_since = time.monotonic()


def quit_app() -> bool:
    """« Quitter Meta-Capp ». False hors mode navigateur : une fenêtre native se
    ferme elle-même, et arrêter son serveur la laisserait vide.

    Les générations en file et en vol sont coupées d'abord : chaque requête qui
    attend Clikoda reçoit aussitôt une erreur (`ollama_client._run`) au lieu de
    retenir l'arrêt jusqu'à son timeout. Un épisode de langue interrompu est
    remis en file au lancement suivant (`lang_runs.on_startup`)."""
    with _LOCK:
        stop = _stop
    if stop is None:
        return False
    from llm.ollama_client import cancel_pending_generations

    cancel_pending_generations()
    cancel_pending_generations("lang")
    logger.info("Mode navigateur : arrêt demandé (Quitter).")
    stop()
    return True


def should_stop(now: float, llm_idle_for: float | None) -> bool:
    """La règle de l'arrêt automatique, sans horloge ni thread (testable)."""
    with _LOCK:
        if _stop is None or _tabs > 0:
            return False
        alone_for = now - _alone_since
    return (
        alone_for >= BROWSER_AUTO_STOP_S
        and llm_idle_for is not None
        and llm_idle_for >= BROWSER_LLM_QUIET_S
    )


def _watch() -> None:
    from llm.ollama_client import llm_idle_for

    while True:
        time.sleep(BROWSER_WATCH_INTERVAL_S)
        if should_stop(time.monotonic(), llm_idle_for()):
            logger.info("Mode navigateur : aucun onglet ouvert depuis %.0f s — arrêt.", BROWSER_AUTO_STOP_S)
            with _LOCK:
                stop = _stop
            if stop is not None:
                stop()
            return


def reset() -> None:
    """Retour à l'état « hors mode navigateur » (tests)."""
    global _stop, _tabs, _alone_since
    with _LOCK:
        _stop = None
        _tabs = 0
        _alone_since = time.monotonic()
