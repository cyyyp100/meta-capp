# metacog/profile.py — Mise à jour du profil permanent
from __future__ import annotations

from db.metacog import CRITERIA, ensure_profile, insert_history, update_profile_values
from metacog.gauges import clamp_gauge, update_profile_gauges_from_session

K = 5
ALPHA_MIN = 0.05
QUIZ_RETENTION_WEIGHT = 0.08


def compute_alpha(sessions_count: int, k: int = K, alpha_min: float = ALPHA_MIN) -> float:
    return max(alpha_min, k / (k + max(0, sessions_count)))


def update_profile(
    user_id: int,
    session_score: dict[str, float],
    session_id: int | None,
) -> dict:
    profile = ensure_profile(user_id)
    # Poids adaptatif : les premières sessions pèsent plus, puis l'apprentissage
    # ralentit avec sessions_count (plancher ALPHA_MIN).
    alpha = compute_alpha(int(profile.get("sessions_count") or 0))
    updates = update_profile_gauges_from_session(profile, session_score, session_weight=alpha)

    for criterion in CRITERIA:
        current_value = clamp_gauge(float(profile.get(criterion, 50.0)))
        score = clamp_gauge(float((session_score or {}).get(criterion, current_value)))
        next_value = updates[criterion]
        insert_history(
            user_id=user_id,
            session_id=session_id,
            criterion=criterion,
            value_before=current_value,
            value_after=next_value,
            session_score=score,
            alpha=alpha,
        )

    update_profile_values(user_id, updates, increment_sessions=True)
    return ensure_profile(user_id)


def update_retention_from_quiz(
    user_id: int,
    verdict: str | None,
    session_id: int | None = None,
    alpha: float = QUIZ_RETENTION_WEIGHT,
) -> dict:
    """Met à jour la rétention permanente après une question de quiz de révision."""
    profile = ensure_profile(user_id)
    current = clamp_gauge(float(profile.get("retention", 50.0)))
    target = _quiz_retention_target(verdict)
    weight = max(0.0, min(1.0, float(alpha)))
    next_value = clamp_gauge(current * (1.0 - weight) + target * weight)
    insert_history(
        user_id=user_id,
        session_id=session_id,
        criterion="retention",
        value_before=current,
        value_after=next_value,
        session_score=target,
        alpha=weight,
    )
    update_profile_values(user_id, {"retention": next_value})
    return ensure_profile(user_id)


def _quiz_retention_target(verdict: str | None) -> float:
    if verdict == "correct":
        return 100.0
    if verdict == "partial":
        return 60.0
    if verdict == "incorrect":
        return 15.0
    return 50.0


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))
