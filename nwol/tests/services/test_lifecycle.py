"""Mode navigateur : quand le serveur s'arrête (services/lifecycle)."""
from __future__ import annotations

import threading
import time

import pytest

from config.settings import BROWSER_AUTO_STOP_S, BROWSER_LLM_QUIET_S
from llm import ollama_client
from services import lifecycle

IDLE = BROWSER_LLM_QUIET_S  # Gemma au repos depuis juste assez longtemps


@pytest.fixture
def stops() -> list:
    """Active le mode navigateur sans thread de surveillance ; compte les arrêts."""
    calls: list = []
    lifecycle.enable_browser_mode(lambda: calls.append("stop"), watch=False)
    return calls


def _later(seconds: float) -> float:
    return time.monotonic() + seconds


def test_nothing_happens_outside_browser_mode():
    """Fenêtre native, `server.main`, tests : la présence est comptée sans effet."""
    lifecycle.tab_opened()
    lifecycle.tab_closed()
    assert not lifecycle.browser_mode()
    assert not lifecycle.should_stop(_later(10 * BROWSER_AUTO_STOP_S), IDLE)
    assert lifecycle.quit_app() is False


def test_stops_once_no_tab_has_been_open_long_enough(stops):
    lifecycle.tab_opened()
    lifecycle.tab_closed()
    assert not lifecycle.should_stop(_later(BROWSER_AUTO_STOP_S - 5), IDLE), "un rechargement n'arrête rien"
    assert lifecycle.should_stop(_later(BROWSER_AUTO_STOP_S + 1), IDLE)


def test_an_open_tab_keeps_the_server_alive_however_long(stops):
    """Un onglet ouvert, pas un utilisateur actif : lire sans cliquer n'est pas partir."""
    lifecycle.tab_opened()
    assert not lifecycle.should_stop(_later(100 * BROWSER_AUTO_STOP_S), IDLE)


def test_the_last_tab_counts_not_the_first(stops):
    lifecycle.tab_opened()
    lifecycle.tab_opened()
    lifecycle.tab_closed()
    assert not lifecycle.should_stop(_later(BROWSER_AUTO_STOP_S + 1), IDLE)
    lifecycle.tab_closed()
    assert lifecycle.should_stop(_later(BROWSER_AUTO_STOP_S + 1), IDLE)


def test_a_browser_that_never_opens_still_lets_the_server_stop(stops):
    """Aucun onglet n'arrive jamais (pas de navigateur par défaut, pas de
    terminal où lire l'adresse) : le compte à rebours part de l'activation."""
    assert lifecycle.should_stop(_later(BROWSER_AUTO_STOP_S + 1), IDLE)


@pytest.mark.parametrize("llm_idle_for", [None, BROWSER_LLM_QUIET_S - 1])
def test_never_while_gemma_works(stops, llm_idle_for):
    """None : une tâche en file ou en cours. Juste terminée : une génération de
    fond enchaîne plusieurs appels, la file est vide un instant entre deux."""
    assert not lifecycle.should_stop(_later(BROWSER_AUTO_STOP_S + 1), llm_idle_for)


def test_quit_cancels_generations_then_stops(stops, monkeypatch):
    cancelled: list = []
    monkeypatch.setattr(ollama_client, "cancel_pending_generations",
                        lambda domain="default": cancelled.append(domain))
    assert lifecycle.quit_app() is True
    assert sorted(cancelled) == ["default", "lang"], "aucune requête ne doit retenir l'arrêt"
    assert stops == ["stop"]


def test_the_watcher_stops_the_server_by_itself(monkeypatch):
    monkeypatch.setattr(lifecycle, "BROWSER_AUTO_STOP_S", 0.0)
    monkeypatch.setattr(lifecycle, "BROWSER_LLM_QUIET_S", 0.0)
    monkeypatch.setattr(lifecycle, "BROWSER_WATCH_INTERVAL_S", 0.01)
    stopped = threading.Event()
    lifecycle.enable_browser_mode(stopped.set)
    assert stopped.wait(5), "aucun onglet, Gemma au repos : le serveur doit s'arrêter seul"


def test_llm_idle_for_sees_queued_and_running_tasks():
    release = threading.Event()
    running = threading.Event()

    def task():
        running.set()
        release.wait(5)

    ollama_client._LLM_QUEUE.put((0, next(ollama_client._QUEUE_COUNTER), task))
    try:
        assert running.wait(5)
        assert ollama_client.llm_idle_for() is None
    finally:
        release.set()
    ollama_client._LLM_QUEUE.join()
    idle = ollama_client.llm_idle_for()
    assert idle is not None and 0 <= idle < 5
