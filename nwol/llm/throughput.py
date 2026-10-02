# llm/throughput.py — Débit RÉEL de Clikoda sur cette machine.
#
# Les budgets temps des générations (`config/settings.task_timeout_s`) partent
# d'un débit de référence mesuré sur la machine de dev (Apple Silicon). Sur un
# PC sans GPU, Clikoda écrit 3 à 6 fois moins vite et lit son prompt 5 à 10 fois
# moins vite : avec des budgets fixes, chaque réponse longue expirait alors que
# le modèle travaillait normalement, et l'assistant semblait en panne.
#
# Ce module observe chaque appel — Ollama renvoie ses propres durées de lecture
# et d'écriture — et en tire deux facteurs de lenteur que les budgets
# appliquent. Ils ne descendent JAMAIS sous 1 : une machine plus rapide que la
# référence garde les budgets d'origine, seule une machine plus lente obtient
# plus de temps. État en mémoire seulement : la mesure de calibrage du
# démarrage (`ollama_client.calibrate_throughput`) le remplit à chaque lancement.
from __future__ import annotations

import threading

from config.settings import (
    OLLAMA_MAX_SLOWDOWN,
    OLLAMA_PROMPT_TOKENS_PER_S,
    OLLAMA_TOKENS_PER_S,
)

# En dessous, la mesure est dominée par les frais fixes de l'appel (et un
# prompt court est souvent servi par le cache de préfixe d'Ollama).
_MIN_OUTPUT_TOKENS = 16
_MIN_PROMPT_TOKENS = 128
# Moyenne glissante asymétrique : une observation plus LENTE est adoptée vite
# (un budget trop court coûte une réponse), une plus rapide lentement (un pic
# isolé ne doit pas raccourcir tous les budgets suivants).
_ALPHA_SLOWER = 0.5
_ALPHA_FASTER = 0.2
# Une tentative expirée prouve que la machine est plus lente que supposé, sans
# dire de combien : on double le temps accordé, dans la limite du plafond.
_TIMEOUT_FACTOR = 2.0

_REFERENCE = {"output": OLLAMA_TOKENS_PER_S, "prompt": OLLAMA_PROMPT_TOKENS_PER_S}

_LOCK = threading.Lock()
_rates: dict[str, float | None] = {"output": None, "prompt": None}


def _rate(count, duration_ns, minimum: int) -> float | None:
    try:
        count = int(count or 0)
        seconds = float(duration_ns or 0) / 1e9
    except (TypeError, ValueError):
        return None
    if count < minimum or seconds <= 0:
        return None
    return count / seconds


def _blend(current: float | None, observed: float) -> float:
    if current is None:
        return observed
    alpha = _ALPHA_SLOWER if observed < current else _ALPHA_FASTER
    return current + alpha * (observed - current)


def _floor(key: str) -> float:
    return _REFERENCE[key] / OLLAMA_MAX_SLOWDOWN


def record_call(data: dict) -> None:
    """Intègre les durées d'une réponse d'Ollama (`eval_*`, `prompt_eval_*`, en ns).

    La lecture du prompt n'apprend que des observations plus LENTES que
    l'estimation : le cache de préfixe d'Ollama compte tout le prompt dans
    `prompt_eval_count` mais ne chronomètre que la partie relue. Un prompt
    qui recommence comme le précédent (même consigne, même page) paraît alors
    bien plus rapide qu'il ne l'est — mesuré : 2 050 tokens/s au lieu de 260.
    Seule une lecture plus lente est une preuve."""
    observed = {
        "output": _rate(data.get("eval_count"), data.get("eval_duration"), _MIN_OUTPUT_TOKENS),
        "prompt": _rate(data.get("prompt_eval_count"), data.get("prompt_eval_duration"), _MIN_PROMPT_TOKENS),
    }
    with _LOCK:
        for key, rate in observed.items():
            if not rate:
                continue
            current = _rates[key]
            if key == "prompt" and current is not None and rate > current:
                continue
            _rates[key] = max(_floor(key), _blend(current, rate))


def record_timeout() -> None:
    """Une tentative a expiré : on double le temps accordé aux suivantes.

    Sans ce repli, une machine très lente dont la PREMIÈRE génération expire
    n'apprendrait jamais rien (une génération expirée ne renvoie pas de durées)
    et chaque tâche suivante expirerait de la même façon."""
    with _LOCK:
        for key in _rates:
            current = _rates[key] if _rates[key] is not None else _REFERENCE[key]
            _rates[key] = max(_floor(key), current / _TIMEOUT_FACTOR)


def _factor(key: str, rate: float | None) -> float:
    if not rate:
        return 1.0
    return min(OLLAMA_MAX_SLOWDOWN, max(1.0, _REFERENCE[key] / rate))


def slowdown() -> tuple[float, float]:
    """(écriture, lecture du prompt) : facteurs appliqués aux budgets, dans [1, OLLAMA_MAX_SLOWDOWN]."""
    with _LOCK:
        output, prompt = _rates["output"], _rates["prompt"]
    return _factor("output", output), _factor("prompt", prompt)


def snapshot() -> dict:
    """Diagnostic (journal, Réglages) : débits estimés et facteur appliqué."""
    with _LOCK:
        output, prompt = _rates["output"], _rates["prompt"]
    gen_slow, prompt_slow = slowdown()
    return {
        "measured": output is not None or prompt is not None,
        "output_tokens_per_s": round(output, 1) if output else None,
        "prompt_tokens_per_s": round(prompt, 1) if prompt else None,
        "slowdown": round(max(gen_slow, prompt_slow), 2),
    }


def reset() -> None:
    """Oublie toute mesure (tests)."""
    with _LOCK:
        _rates["output"] = None
        _rates["prompt"] = None
