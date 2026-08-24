# services/session.py — Cycle de vie d'une session de lecture + métriques + finalisation.
#
# start -> (lecture, Q&R persistées) -> end (métriques) -> finalize (réflexions
# + nudge du profil métacognitif vers le score de session).
from __future__ import annotations

import logging
import time

from db.answers import get_answers_for_session
from db.metacog import (
    CRITERIA,
    ensure_profile,
    get_profile,
    insert_history,
    set_general_analysis,
    update_profile_values,
)
from db.session_gauges import get_latest_gauges, record_gauges
from db.session_reflections import save_session_reflection
from db.sessions import end_session as _end_session
from db.sessions import get_session
from db.sessions import start_session as _start_session
from db.user import DEFAULT_USER_ID
from metacog.gauges import (
    clamp_gauge,
    make_gauges,
    snapshot,
    update_gauges_from_evaluation,
)
from metacog.profile import compute_alpha, update_profile

logger = logging.getLogger("services.session")

__all__ = [
    "REFLECTION_QUESTIONS",
    "start_session",
    "end_session",
    "session_metrics",
    "session_analysis",
    "finalize_session",
    "nudge_metacog_profile",
    "LiveGauges",
]

REFLECTION_QUESTIONS = [
    "Qu'as-tu compris de plus important dans cette session ?",
    "Quel point reste flou et mériterait d'être revu ?",
    "Comment pourrais-tu réutiliser ce que tu viens d'apprendre ?",
]

# Critères que le seul taux de réussite informe honnêtement, quand la séance n'a
# pas de canal de jauges temps réel. Les trois autres (curiosité, créativité,
# métacognition) ne sont pas déduisibles d'un score : on les laisse inchangés.
_PROFILE_NUDGE_CRITERIA = ("attention", "context_comprehension", "retention")


class LiveGauges:
    """Jauges métacognitives live d'une session de lecture web (en mémoire).

    Même sémantique que le moteur Tk (`metacog.gauges`) : seed = profil long terme
    × 0.8, mise à jour additive bornée à partir des `metacog_signals`/`verdict` que
    chaque réponse d'assistant ou évaluation renvoie déjà. Persistance best-effort
    dans `session_gauges` dès qu'un `session_id` est connu (alimente le radar de
    stats) — un incident n'interrompt jamais la lecture."""

    def __init__(self, session_id: int | None = None, user_id: int = DEFAULT_USER_ID) -> None:
        self.session_id = session_id
        try:
            profile = ensure_profile(user_id)
        except Exception:
            profile = {}
        self._gauges = make_gauges(profile)
        self._t0 = time.monotonic()
        self._record()

    def apply(self, evaluation: dict | None) -> dict[str, float]:
        """Intègre les signaux d'une réponse/évaluation puis renvoie l'état courant."""
        update_gauges_from_evaluation(self._gauges, evaluation or {})
        self._record()
        return self.snapshot()

    def snapshot(self) -> dict[str, float]:
        return snapshot(self._gauges)

    def _record(self) -> None:
        if self.session_id is None:
            return
        try:
            record_gauges(int(self.session_id), self.snapshot(), t=time.monotonic() - self._t0)
        except Exception:  # persistance best-effort
            logger.debug("Enregistrement des jauges de session ignoré", exc_info=True)


def start_session(doc_id: int, user_id: int = DEFAULT_USER_ID) -> dict:
    return {"session_id": _start_session(doc_id, user_id)}


def end_session(session_id: int, pages_read: int | None = None, duration_s: int | None = None) -> dict:
    _end_session(session_id, pages_read=pages_read, duration_s=duration_s)
    return session_metrics(session_id)


def session_metrics(session_id: int) -> dict:
    session = get_session(session_id) or {}
    answers = get_answers_for_session(session_id)
    total = len(answers)
    correct = sum(1 for a in answers if a.get("verdict") == "correct")
    partial = sum(1 for a in answers if a.get("verdict") == "partial")
    success = round(100 * (correct + 0.5 * partial) / total) if total else 0
    return {
        "session_id": session_id,
        "duration_s": int(session.get("duration_s") or 0),
        "pages_read": int(session.get("pages_read") or 0),
        "questions_answered": total,
        "correct": correct,
        "success_rate": success,
        "reflection_questions": list(REFLECTION_QUESTIONS),
    }


def session_analysis(session_id: int, user_id: int = DEFAULT_USER_ID) -> dict:
    """Analyse LLM de la session : stats + jauges de session + jauges de profil.

    Best-effort : renvoie {"analysis": ""} si le LLM est indisponible. Réutilise le
    « session summary » du moteur métacog (on n'en garde que le résumé qualitatif)."""
    metrics = session_metrics(session_id)
    session_gauges = get_latest_gauges(session_id)
    try:
        profile = ensure_profile(user_id)
    except Exception:
        profile = {}
    profile_gauges = {k: float(profile.get(k, 50.0)) for k in CRITERIA}
    stats = {
        "duration_s": metrics["duration_s"],
        "pages_read": metrics["pages_read"],
        "questions_answered": metrics["questions_answered"],
        "correct": metrics["correct"],
        "success_rate": metrics["success_rate"],
    }
    session_data = {**stats, "gauges": session_gauges, "profile": profile_gauges}
    context = {"session_data": session_data, "metacog_profile": profile_gauges}
    try:
        from llm.ollama_client import generate_session_summary_async
        from services.llm_bridge import run_llm_sync

        result = run_llm_sync(
            lambda ok, err: generate_session_summary_async(context, ok, err),
        )
        summary = (result or {}).get("session_summary") or {}
        return {"analysis": str(summary.get("qualitative_summary") or "")}
    except Exception:  # pragma: no cover - best-effort, LLM indisponible
        return {"analysis": ""}


def _update_general_analysis(
    session_id: int,
    responses: list[str],
    metrics: dict,
    session_gauges: dict,
    user_id: int,
) -> None:
    """Met à jour l'analyse générale (évolutive) de l'apprenant — best-effort."""
    try:
        profile = get_profile(user_id) or {}
        profile_gauges = {k: float(profile.get(k, 50.0)) for k in CRITERIA}
        reflections = [
            {
                "question": REFLECTION_QUESTIONS[i] if i < len(REFLECTION_QUESTIONS) else f"Réflexion {i + 1}",
                "answer": str(r),
            }
            for i, r in enumerate(responses or [])
        ]
        context = {
            "profile": profile_gauges,
            "session_metrics": metrics,
            "session_gauges": session_gauges or {},
            "reflections": reflections,
            "previous_analysis": str(profile.get("general_analysis") or ""),
        }
        from llm.ollama_client import generate_profile_analysis_async
        from services.llm_bridge import run_llm_sync

        result = run_llm_sync(
            lambda ok, err: generate_profile_analysis_async(context, ok, err),
        )
        analysis = str((result or {}).get("analysis") or "").strip()
        if analysis:
            set_general_analysis(user_id, analysis)
    except Exception:  # best-effort : conserve l'analyse précédente
        logger.debug("Analyse de profil ignorée (analyse précédente conservée)", exc_info=True)


def nudge_metacog_profile(
    user_id: int,
    score: float,
    responses: list[str],
    metrics: dict,
    session_id: int | None = None,
    session_gauges: dict | None = None,
) -> dict:
    """Finalisation métacognitive partagée (lecture PDF *et* séance de langue).

    Persiste les réflexions, fait glisser le profil long terme vers le score de la
    session (jauges live si dispo, sinon EMA des 3 critères clés vers le taux de
    réussite), et régénère l'analyse générale de l'apprenant. `session_id=None` pour
    une séance de langue (colonnes FK nullables) — la séance compte alors comme une
    session normale dans le profil. Renvoie les nouvelles valeurs des critères.
    """
    for order, response in enumerate(responses or []):
        question = REFLECTION_QUESTIONS[order] if order < len(REFLECTION_QUESTIONS) else f"Réflexion {order + 1}"
        save_session_reflection(session_id, question, str(response), user_id, order)

    profile = ensure_profile(user_id)
    if session_gauges is None and session_id is not None:
        session_gauges = get_latest_gauges(session_id)

    # Poids adaptatif : les premières sessions pèsent plus, puis l'apprentissage
    # ralentit (plancher ALPHA_MIN). Un seul modèle pour tout le produit.
    alpha = compute_alpha(int(profile.get("sessions_count") or 0))

    if session_gauges:
        # Canal temps réel disponible : tout le profil (6 critères) glisse vers les
        # jauges live via le moteur unique `metacog.profile.update_profile`
        # (historique par critère + incrément du compteur de sessions inclus).
        updated = update_profile(user_id, session_gauges, session_id)
        new_values: dict[str, float] = {c: float(updated.get(c, 50.0)) for c in CRITERIA}
    else:
        # Repli (séance sans canal temps réel) : le taux de réussite n'informe
        # honnêtement que ces trois critères. On ne bouge pas les autres plutôt que
        # d'inventer une mesure — mais on utilise le MÊME alpha adaptatif.
        new_values = {}
        for criterion in _PROFILE_NUDGE_CRITERIA:
            before = float(profile.get(criterion, 50.0))
            after = clamp_gauge(before * (1 - alpha) + score * alpha)
            new_values[criterion] = after
            insert_history(user_id, session_id, criterion, before, after, score, alpha)
        update_profile_values(user_id, new_values, increment_sessions=True)

    # Analyse générale de l'apprenant (best-effort, après le nudge profil).
    _update_general_analysis(session_id, responses, metrics, session_gauges, user_id)
    return new_values


def finalize_session(session_id: int, responses: list[str], user_id: int = DEFAULT_USER_ID) -> dict:
    metrics = session_metrics(session_id)
    score = float(metrics["success_rate"])
    nudge_metacog_profile(user_id, score, responses, metrics, session_id=session_id)
    return {"ok": True, "score": score}
