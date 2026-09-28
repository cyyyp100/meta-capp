# services/lang_inflight.py — Registre des générations de langue en cours.
#
# Défaut n° 4 de architecture/18-pipeline-lang.md : quand l'apprenant arrivait
# sur un exercice avant la fin de son préchargement, une seconde génération
# identique partait en file derrière la première — attente doublée et un appel
# LLM jeté. Le registre donne à chaque clé un propriétaire unique ; les suivants
# attendent son résultat au lieu de le refaire.
#
# Mono-processus par conception (cf. CLAUDE.md) : un verrou suffit.
from __future__ import annotations

import threading
from typing import Hashable


class InflightRegistry:
    """Une génération à la fois par clé (ex. (profile_id, episode_n))."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[Hashable, threading.Event] = {}

    def claim(self, key: Hashable) -> threading.Event | None:
        """`None` : l'appelant devient propriétaire et DOIT appeler `release`.
        Sinon : l'événement qui sera levé quand le propriétaire aura fini."""
        with self._lock:
            event = self._events.get(key)
            if event is not None:
                return event
            self._events[key] = threading.Event()
            return None

    def release(self, key: Hashable) -> None:
        with self._lock:
            event = self._events.pop(key, None)
        if event is not None:
            event.set()

    def is_running(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._events

    def running_keys(self) -> list[Hashable]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        """Tests uniquement : libère tout (chaque attente est réveillée)."""
        with self._lock:
            events = list(self._events.values())
            self._events.clear()
        for event in events:
            event.set()
