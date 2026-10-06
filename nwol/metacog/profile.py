# metacog/profile.py — Mise à jour du profil permanent
from __future__ import annotations

from db.metacog import CRITERIA, ensure_profile, insert_history, update_profile_values
from metacog.gauges import clamp_gauge, update_profile_gauges_from_session

K = 5
ALPHA_MIN = 0.05
# Nombre de mesures (réponses évaluées + questions posées à l'assistant) au-delà
# duquel une session pèse de tout son poids. En dessous, elle pèse au prorata :
# une session de deux réponses ne doit pas déplacer le profil autant qu'une
# session de dix, sinon une séance courte tire durablement le profil vers son
# amorce (profil × 0,8).
FULL_CONFIDENCE_MEASURES = 4


def compute_alpha(sessions_count: int, k: int = K, alpha_min: float = ALPHA_MIN) -> float:
    return max(alpha_min, k / (k + max(0, sessions_count)))


def compute_confidence(measures: int | None, full: int = FULL_CONFIDENCE_MEASURES) -> float:
    """Part du poids de session réellement méritée par la quantité de mesure.

    `None` = l'appelant ne sait pas compter (il affirme ses jauges) -> 1.0.
    0 mesure -> 0.0 : le profil ne doit alors PAS bouger, et l'appelant est
    censé s'arrêter avant (cf. `services.session.nudge_metacog_profile`)."""
    if measures is None:
        return 1.0
    return max(0.0, min(1.0, float(measures) / max(1, int(full))))


def update_profile(
    user_id: int,
    session_score: dict[str, float],
    session_id: int | None,
    confidence: float | dict[str, float] = 1.0,
    practice_session_id: int | None = None,
) -> dict:
    """Fait glisser le profil vers les jauges d'une séance (EMA, α adaptatif).

    `confidence` corrige le poids par la quantité de mesure de CETTE séance : un
    nombre pour toute la séance (lecture), ou un poids par critère (séance de
    pratique, dont le rejeu sait combien de mesures ont informé chaque critère —
    un critère absent du dict n'a rien mesuré et ne bouge pas)."""
    profile = ensure_profile(user_id)
    # Poids adaptatif : les premières sessions pèsent plus, puis l'apprentissage
    # ralentit avec sessions_count (plancher ALPHA_MIN). `confidence` corrige
    # ensuite par la quantité de mesure de CETTE session (cf. compute_confidence).
    base_alpha = compute_alpha(int(profile.get("sessions_count") or 0))
    if isinstance(confidence, dict):
        alphas = {
            criterion: max(0.0, min(1.0, base_alpha * max(0.0, min(1.0, float(confidence.get(criterion, 0.0))))))
            for criterion in CRITERIA
        }
        updates = {
            criterion: update_profile_gauges_from_session(
                profile, session_score, session_weight=alphas[criterion],
            )[criterion]
            for criterion in CRITERIA
        }
    else:
        alpha = max(0.0, min(1.0, base_alpha * max(0.0, min(1.0, float(confidence)))))
        alphas = {criterion: alpha for criterion in CRITERIA}
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
            alpha=alphas[criterion],
            practice_session_id=practice_session_id,
        )

    update_profile_values(user_id, updates, increment_sessions=True)
    return ensure_profile(user_id)
