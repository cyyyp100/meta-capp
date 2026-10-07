# services/stats.py — Modèle de données du profil métacognitif (stats).
#
# Agrège les lectures DB (profil, historique, matières) et calcule les valeurs
# dérivées (score global, tendance, deltas, recommandations) sous forme de
# catégories neutres. La couche de présentation (page Tk aujourd'hui, frontend
# web demain) mappe ces catégories vers des libellés traduits et des couleurs.
from __future__ import annotations

from config.subjects import canonical_subject, is_language
from db.metacog import CRITERIA, ensure_profile, get_history_by_criterion
from db.subjects import get_all_subjects, get_subject_history_by_subject
from db.user import get_default_user
from services.subjects import describe, language_practice, owned_subjects

__all__ = [
    "CRITERIA",
    "get_metacog_overview",
    "trend_category",
    "subject_recommendation",
]

# Seuil (en points) au-delà duquel une évolution est jugée significative.
_TREND_THRESHOLD = 2.0


def get_metacog_overview(user_id: int | None = None) -> dict:
    """Vue complète du profil métacognitif, prête à afficher.

    Renvoie un dict JSON-sérialisable :
      {
        "user": {"id", "name"},
        "sessions_count": int,
        "updated_at": str,            # ISO brut ("" si absent)
        "global_score": float,        # 0..100
        "trend": {"category", "delta"},
        "criteria": [{"key", "value", "history": [float], "delta"} ...],
        "subjects": [{"subject", "kind", "flag", "level", "history": [float],
                      "delta", "updates", "recommendation",
                      # langues seulement :
                      "cefr", "sessions"} ...],
      }

    `subjects` est la liste de l'apprenant (`services.subjects.owned_subjects`),
    la même que celle du quiz. Une langue jamais jouée en quiz n'a pas de
    maîtrise mesurée : `level` et `recommendation` y valent None, sa carte montre
    son niveau CECR et ses séances.
    """
    user = get_default_user()
    uid = user["id"] if user_id is None else user_id

    profile = ensure_profile(uid)
    history = get_history_by_criterion(uid)
    subject_history = get_subject_history_by_subject(uid)
    subject_rows = get_all_subjects(uid)

    criteria: list[dict] = []
    for key in CRITERIA:
        hist = _history_values(history.get(key) or [])
        value = _clamp(float(profile.get(key, 50.0)))
        criteria.append({
            "key": key,
            "value": value,
            "history": hist,
            "delta": _last_delta(hist),
        })

    global_score = sum(c["value"] for c in criteria) / max(1, len(criteria))
    trend_delta = _global_trend_delta(criteria)

    rows = {canonical_subject(row.get("subject")): row for row in subject_rows}
    practice = language_practice(uid)
    subjects: list[dict] = []
    for subject in owned_subjects(uid):
        row = rows.get(subject) or {}
        entry = describe(subject)
        measured = int(row.get("questions_count") or 0) > 0
        if is_language(subject) and not measured:
            # Rien n'a été mesuré en quiz : pas de 50 de façade.
            entry.update(level=None, history=[], delta=0.0, updates=0, recommendation=None)
        else:
            level = _clamp(float(row.get("level", 50.0)))
            hist = _history_values(subject_history.get(row.get("subject") or subject) or [])
            if not hist:
                hist = [level]
            delta = _last_delta(hist)
            entry.update(
                level=level, history=hist, delta=delta, updates=len(hist),
                recommendation=subject_recommendation(level, delta),
            )
        if is_language(subject):
            entry.update(practice.get(subject) or {"sessions": 0, "cefr": None})
        subjects.append(entry)

    return {
        "user": {"id": user["id"], "name": user["name"]},
        "sessions_count": int(profile.get("sessions_count", 0) or 0),
        "updated_at": profile.get("updated_at") or "",
        "global_score": global_score,
        "trend": {"category": trend_category(trend_delta), "delta": trend_delta},
        "criteria": criteria,
        "subjects": subjects,
        "general_analysis": profile.get("general_analysis") or "",
        "general_analysis_updated_at": profile.get("general_analysis_updated_at") or "",
    }


def trend_category(delta: float) -> str:
    """Catégorie d'évolution : 'in_progress' | 'to_improve' | 'stable'."""
    if delta > _TREND_THRESHOLD:
        return "in_progress"
    if delta < -_TREND_THRESHOLD:
        return "to_improve"
    return "stable"


def subject_recommendation(level: float, delta: float) -> str:
    """Recommandation matière : 'solid' | 'progressing' | 'to_review' | 'to_improve'."""
    if level >= 75:
        return "solid"
    if delta > _TREND_THRESHOLD:
        return "progressing"
    if level < 45:
        return "to_review"
    return "to_improve"


def _global_trend_delta(criteria: list[dict]) -> float:
    deltas = [c["delta"] for c in criteria if len(c["history"]) >= 2]
    if not deltas:
        return 0.0
    return sum(deltas) / len(deltas)


def _history_values(rows: list[tuple[int | None, float, str]]) -> list[float]:
    return [_clamp(float(value)) for _session_id, value, _recorded_at in rows]


def _last_delta(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return values[-1] - values[-2]


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))
