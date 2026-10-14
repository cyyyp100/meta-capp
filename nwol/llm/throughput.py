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

# Le MODULE et non la constante : `max_slowdown()` change avec le mode économe,
# et une valeur importée à l'import serait figée au plafond normal. Le plancher
# des débits (ici) et le plafond des budgets (config/settings) divergeraient
# alors d'un facteur 2,5 — la panne exacte que décrit settings.py.
from config import settings

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

# Mesures PAR MODÈLE, et la référence avec elles. Un seul jeu de mesures et une
# seule référence (celles du modèle de dev) donnaient à `gemma4:31b` un facteur
# de lenteur de 18/6 = 3 avant même d'avoir rien mesuré : le plafond prévu pour
# une machine lente était dépensé pour la TAILLE DU MODÈLE, et il ne restait
# rien pour la machine. Ici, `slowdown()` ne mesure plus que machine-contre-
# attente-de-ce-modèle ; le coût du modèle est un facteur à part
# (`settings._model_factors`). Changer de modèle ne jette rien : son entrée
# cesse d'être consultée, et y revenir réutilise ce qu'on savait de lui. Le dict
# est borné par le vocabulaire fermé de la préférence (config/settings.LLM_MODELS).
_LOCK = threading.Lock()
_rates: dict[str, dict[str, float | None]] = {}


def _reference(model: str) -> dict[str, float]:
    """Débit ATTENDU de CE modèle sur la machine de référence. Import tardif :
    la table des profils est une politique (cf. services/llm_models)."""
    from services.llm_models import profile

    p = profile(model)
    return {"output": p.tokens_per_s, "prompt": p.prompt_tokens_per_s}


def _resolved(model: str) -> str:
    """Modèle visé ; vide = le modèle actif."""
    if model:
        return model
    from services.llm_models import active

    return active()


def _entry(model: str) -> dict[str, float | None]:
    """Sous `_LOCK`."""
    return _rates.setdefault(model, {"output": None, "prompt": None})


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


def record_call(data: dict, model: str = "") -> None:
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
    model = _resolved(model)
    reference = _reference(model)
    ceiling = settings.max_slowdown()
    with _LOCK:
        rates = _entry(model)
        for key, rate in observed.items():
            if not rate:
                continue
            current = rates[key]
            if key == "prompt" and current is not None and rate > current:
                continue
            rates[key] = max(reference[key] / ceiling, _blend(current, rate))


def record_timeout(model: str = "") -> None:
    """Une tentative a expiré : on double le temps accordé aux suivantes.

    Sans ce repli, une machine très lente dont la PREMIÈRE génération expire
    n'apprendrait jamais rien (une génération expirée ne renvoie pas de durées)
    et chaque tâche suivante expirerait de la même façon."""
    model = _resolved(model)
    reference = _reference(model)
    ceiling = settings.max_slowdown()
    with _LOCK:
        rates = _entry(model)
        for key in rates:
            current = rates[key] if rates[key] is not None else reference[key]
            rates[key] = max(reference[key] / ceiling, current / _TIMEOUT_FACTOR)


def _factor(reference: float, rate: float | None, ceiling: float) -> float:
    if not rate:
        return 1.0
    return min(ceiling, max(1.0, reference / rate))


def slowdown(model: str = "") -> tuple[float, float]:
    """(écriture, lecture du prompt) : facteurs appliqués aux budgets, dans
    [1, settings.max_slowdown()]. Lenteur de la MACHINE face à ce qu'on attend
    de ce modèle — la taille du modèle, elle, est comptée ailleurs.

    Le plafond est relu à chaque appel : une mesure prise en mode économe (un
    débit jusqu'à 20 fois sous la référence) n'est pas jetée quand le mode
    s'arrête, elle est simplement bornée au plafond normal."""
    model = _resolved(model)
    reference = _reference(model)
    ceiling = settings.max_slowdown()
    with _LOCK:
        rates = dict(_entry(model))
    return (_factor(reference["output"], rates["output"], ceiling),
            _factor(reference["prompt"], rates["prompt"], ceiling))


def snapshot(model: str = "") -> dict:
    """Diagnostic (journal, Réglages) : débits estimés et facteur appliqué."""
    model = _resolved(model)
    with _LOCK:
        rates = dict(_entry(model))
    output, prompt = rates["output"], rates["prompt"]
    gen_slow, prompt_slow = slowdown(model)
    return {
        "model": model,
        "measured": output is not None or prompt is not None,
        "output_tokens_per_s": round(output, 1) if output else None,
        "prompt_tokens_per_s": round(prompt, 1) if prompt else None,
        "slowdown": round(max(gen_slow, prompt_slow), 2),
    }


def reset(model: str | None = None) -> None:
    """Oublie les mesures d'un modèle, ou de tous (tests)."""
    with _LOCK:
        if model is None:
            _rates.clear()
        else:
            _rates.pop(model, None)
