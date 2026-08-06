# metacog/gauges.py — Jauges temps réel
from __future__ import annotations

from dataclasses import dataclass

from db.metacog import CRITERIA

SESSION_INHERITANCE_FACTOR = 0.8
PROFILE_SESSION_WEIGHT = 0.1

# Jauge(s) principalement pilotée(s) par chaque type de question. Le signal LLM
# de ces dimensions est amplifié, les autres atténués : une question de curiosité
# fait surtout bouger `curiosity`, une de contexte surtout `context_comprehension`.
# Source canonique partagée avec le prompt d'évaluation (prompts._EVAL_TYPE_DIMENSIONS).
QUESTION_TYPE_TARGET_GAUGES: dict[str, tuple[str, ...]] = {
    "qcm": ("retention", "attention"),
    "open": ("context_comprehension", "creativity"),
    "comprehension": ("context_comprehension",),
    "application": ("context_comprehension", "retention"),
    "curiosity": ("curiosity",),
    "visualization": ("creativity", "context_comprehension"),
    "metacognition": ("meta_cognition",),
    "anticipation": ("meta_cognition", "attention"),
}
_TYPE_TARGET_SCALE = 1.5  # amplification du signal sur la dimension visée
_TYPE_OTHER_SCALE = 0.5   # atténuation des autres dimensions


@dataclass
class GaugeState:
    name: str
    value: float

    def update(
        self,
        signal: float = 0.0,
        verdict: str | None = None,
        response_time_ms: int | None = None,
        consecutive_incorrect: int = 0,
    ) -> float:
        if self.name == "attention":
            self.value = _update_attention(
                self.value,
                signal,
                verdict,
                response_time_ms,
                consecutive_incorrect,
            )
        elif self.name == "meta_cognition":
            self.value = _clamp(self.value)
        else:
            delta = max(-2.0, min(2.0, float(signal))) * 8.0
            if verdict == "correct":
                delta += 1.5
            elif verdict == "partial":
                delta += 0.3
            elif verdict == "incorrect":
                delta -= 1.5
            self.value = _clamp(self.value + delta)
        return self.value

    def apply_delta(self, delta: float) -> float:
        self.value = _clamp(self.value + float(delta))
        return self.value


def make_gauges(profile: dict | None = None) -> dict[str, GaugeState]:
    values = initialize_session_gauges(profile or {})
    return {
        criterion: GaugeState(criterion, values[criterion])
        for criterion in CRITERIA
    }


def initialize_session_gauges(profile_gauges: dict | None) -> dict[str, float]:
    profile_gauges = profile_gauges or {}
    values: dict[str, float] = {}
    for criterion in CRITERIA:
        values[criterion] = _clamp(float(profile_gauges.get(criterion, 50.0)) * SESSION_INHERITANCE_FACTOR)
    return values


def update_profile_gauges_from_session(
    profile_gauges: dict | None,
    session_gauges: dict | None,
    session_weight: float = PROFILE_SESSION_WEIGHT,
) -> dict[str, float]:
    profile_gauges = profile_gauges or {}
    session_gauges = session_gauges or {}
    weight = max(0.0, min(1.0, float(session_weight)))
    profile_weight = 1.0 - weight
    updates: dict[str, float] = {}
    for criterion in CRITERIA:
        current = _clamp(float(profile_gauges.get(criterion, 50.0)))
        session_value = _clamp(float(session_gauges.get(criterion, current)))
        updates[criterion] = _clamp(current * profile_weight + session_value * weight)
    return updates


def update_gauges_from_evaluation(
    gauges: dict[str, GaugeState],
    evaluation: dict,
    response_time_ms: int | None = None,
    consecutive_incorrect: int = 0,
) -> dict[str, float]:
    signals = evaluation.get("metacog_signals") or {}
    verdict = evaluation.get("verdict")
    # Type de question : oriente quelles jauges la réponse fait bouger en priorité.
    # Absent (ex. question libre) -> comportement uniforme historique.
    question_type = str(evaluation.get("question_type") or "")
    target_gauges = QUESTION_TYPE_TARGET_GAUGES.get(question_type, ())
    values = {}
    for criterion, gauge in gauges.items():
        if criterion == "meta_cognition":
            # Dérive pendant la session. Renforcée pour les questions justement
            # ciblées sur la métacognition (sinon dérive légère, score fin de
            # session restant la MAJ principale via build_meta_cognition_analysis_prompt).
            meta_targeted = "meta_cognition" in target_gauges
            if verdict == "correct":
                gauge.apply_delta(2.0 if meta_targeted else 0.6)
            elif verdict == "partial":
                gauge.apply_delta(0.8 if meta_targeted else 0.2)
            elif verdict == "incorrect" and meta_targeted:
                gauge.apply_delta(-0.6)
            values[criterion] = gauge.value
            continue
        signal = _effective_signal(criterion, signals, evaluation)
        signal *= _type_signal_scale(criterion, target_gauges)
        values[criterion] = gauge.update(
            signal=signal,
            verdict=verdict,
            response_time_ms=response_time_ms,
            consecutive_incorrect=consecutive_incorrect,
        )
    return values


def _type_signal_scale(criterion: str, target_gauges: tuple[str, ...]) -> float:
    """Facteur appliqué au signal selon le type de question.

    Sans type ciblé, facteur neutre (1.0). Sinon, amplifie la dimension visée et
    atténue les autres pour différencier l'effet d'une curiosité vs un contexte."""
    if not target_gauges:
        return 1.0
    return _TYPE_TARGET_SCALE if criterion in target_gauges else _TYPE_OTHER_SCALE


def snapshot(gauges: dict[str, GaugeState]) -> dict[str, float]:
    return {name: gauge.value for name, gauge in gauges.items()}


def clamp_gauge(value: float) -> float:
    return _clamp(value)


def _effective_signal(criterion: str, signals: dict, evaluation: dict) -> float:
    try:
        signal = float(signals.get(criterion, 0.0))
    except (TypeError, ValueError):
        signal = 0.0

    if criterion == "curiosity":
        curiosity_signals = evaluation.get("curiosity_signals") or {}
        if isinstance(curiosity_signals, dict) and any(bool(value) for value in curiosity_signals.values()):
            signal += 0.6
    elif criterion == "creativity":
        creativity_signals = evaluation.get("creativity_signals") or {}
        if isinstance(creativity_signals, dict):
            positives = sum(
                1
                for key in ("goes_beyond_prompt", "makes_connections", "uses_analogy", "personal_reformulation", "original_hypothesis")
                if creativity_signals.get(key)
            )
            try:
                depth = float(creativity_signals.get("depth_of_reflection", 0.0))
            except (TypeError, ValueError):
                depth = 0.0
            if positives:
                signal += min(0.7, positives * 0.18)
            if depth >= 0.65:
                signal += 0.25
            elif depth <= 0.2:
                signal -= 0.15

    return max(-2.0, min(2.0, signal))


def _update_attention(
    value: float,
    signal: float,
    verdict: str | None,
    response_time_ms: int | None,
    consecutive_incorrect: int,
) -> float:
    delta = max(-2.0, min(2.0, float(signal))) * 5.0
    if response_time_ms is not None and response_time_ms > 12000:
        delta -= min(6.0, (response_time_ms - 12000) / 2000.0)
    if verdict == "correct":
        delta += 1.0
    elif verdict == "incorrect":
        delta -= 2.0
    delta -= max(0, consecutive_incorrect - 1) * 1.0
    return _clamp(value + delta)


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))
