# metacog/signals.py — Agrégation des signaux bruts de session
from __future__ import annotations

from db.metacog import CRITERIA


def compute_session_score(answers: list[dict], gauges: list[dict] | dict | None = None) -> dict[str, float]:
    gauge_scores = _gauge_scores(gauges)
    if not answers:
        return {
            criterion: _clamp(gauge_scores.get(criterion, 50.0))
            for criterion in CRITERIA
        }

    success_score = _success_score(answers)
    time_score = _response_time_score(answers)
    signal_scores = _llm_signal_scores(answers)

    scores = {
        "attention": _mix(_mix(time_score, success_score, 0.55), signal_scores["attention"], 0.8),
        "context_comprehension": _mix(success_score, signal_scores["context_comprehension"], 0.7),
        "creativity": _mix(signal_scores["creativity"], success_score, 0.8),
        "retention": _mix(signal_scores["retention"], success_score, 0.75),
        "curiosity": _mix(signal_scores["curiosity"], success_score, 0.75),
        "meta_cognition": signal_scores["meta_cognition"],
    }

    for criterion, gauge_value in gauge_scores.items():
        scores[criterion] = _mix(scores[criterion], gauge_value, 0.75)

    return {criterion: _clamp(value) for criterion, value in scores.items()}


def _success_score(answers: list[dict]) -> float:
    verdict_values = {
        "correct": 1.0,
        "partial": 0.55,
        "incorrect": 0.0,
    }
    values = [verdict_values.get(answer.get("verdict"), 0.0) for answer in answers]
    return 100.0 * (sum(values) / len(values))


def _response_time_score(answers: list[dict]) -> float:
    response_times = [
        int(answer["response_time_ms"])
        for answer in answers
        if answer.get("response_time_ms") is not None
    ]
    if not response_times:
        return 70.0
    avg_ms = sum(response_times) / len(response_times)
    # 2s ou moins : très fluide ; 20s ou plus : attention probablement basse.
    return _clamp(100.0 - max(0.0, avg_ms - 2000.0) / 180.0)


def _llm_signal_scores(answers: list[dict]) -> dict[str, float]:
    totals = {criterion: 0.0 for criterion in CRITERIA}
    counts = {criterion: 0 for criterion in CRITERIA}

    for answer in answers:
        signals = answer.get("metacog_signals") or {}
        if not isinstance(signals, dict):
            continue
        for criterion in CRITERIA:
            value = signals.get(criterion)
            if isinstance(value, (int, float)):
                totals[criterion] += max(-2.0, min(2.0, float(value)))
                counts[criterion] += 1

    scores = {}
    for criterion in CRITERIA:
        if counts[criterion] == 0:
            scores[criterion] = 50.0
        else:
            avg_signal = totals[criterion] / counts[criterion]
            # signal dans [-2, +2] → score dans [0, 100]
            scores[criterion] = 50.0 + avg_signal * 25.0
    return scores


def _gauge_scores(gauges: list[dict] | dict | None) -> dict[str, float]:
    if not gauges:
        return {}
    if isinstance(gauges, dict):
        return {
            key: _clamp(value)
            for key, value in gauges.items()
            if key in CRITERIA and isinstance(value, (int, float))
        }

    latest = {}
    for row in gauges:
        name = row.get("gauge_name")
        if name in CRITERIA and isinstance(row.get("value"), (int, float)):
            latest[name] = _clamp(float(row["value"]))
    return latest


def _mix(primary: float, secondary: float, primary_weight: float) -> float:
    return primary * primary_weight + secondary * (1.0 - primary_weight)


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))
