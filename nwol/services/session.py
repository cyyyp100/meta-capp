# services/session.py — Cycle de vie d'une session de lecture + métriques + finalisation.
#
# start -> (lecture, Q&R persistées) -> end (métriques) -> finalize (réflexions
# + nudge du profil métacognitif vers le score de session).
from __future__ import annotations

import logging
import time

from config.settings import (
    ATTENTION_PASSIVE_FLOOR,
    ATTENTION_PERSIST_EVERY_S,
)
from db.answers import get_answers_for_session
from db.metacog import (
    CRITERIA,
    ensure_profile,
    get_history_by_criterion,
    get_profile,
    insert_history,
    set_general_analysis,
    update_profile_values,
)
from db.questions import count_assistant_questions
from db.session_gauges import get_first_gauges, get_latest_gauges, record_gauges
from db.session_reflections import (
    get_recent_reflection_questions,
    save_session_reflection,
)
from db.sessions import end_session as _end_session
from db.sessions import get_session
from db.sessions import start_session as _start_session
from db.user import DEFAULT_USER_ID, get_streak, record_study_day
from metacog.gauges import (
    clamp_gauge,
    make_gauges,
    reading_attention_delta,
    snapshot,
    update_gauges_from_evaluation,
)
from metacog.profile import compute_alpha, compute_confidence, update_profile
from metacog.reflection import fallback_meta_cognition_analysis, pick_reflection_question

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

# Les questions FIXES du sas de sortie. Il y en a deux : l'étudiant commence à
# écrire immédiatement, pendant que le LLM prépare la troisième (personnalisée,
# livrée avec l'analyse de session — cf. `session_analysis`). Trois questions
# figées faisaient attendre le modèle pour rien ; trois questions générées
# faisaient attendre l'étudiant devant un écran vide.
REFLECTION_QUESTIONS = [
    "Qu'as-tu compris de plus important dans cette session ?",
    "Quel point reste flou et mériterait d'être revu ?",
]

# Critères que le seul taux de réussite informe honnêtement, quand la séance n'a
# pas de canal de jauges temps réel. Les trois autres (curiosité, créativité,
# métacognition) ne sont pas déduisibles d'un score : on les laisse inchangés.
_PROFILE_NUDGE_CRITERIA = ("attention", "context_comprehension", "retention")


class LiveGauges:
    """Jauges métacognitives live d'une session de lecture web (en mémoire).

    Seed = profil long terme × 0.8, puis deux sources de mouvement :

      * `apply` — les `metacog_signals`/`verdict` que chaque réponse d'assistant
        ou évaluation renvoie déjà, plus le temps de réponse et la série
        d'erreurs (le modèle d'attention les attendait depuis toujours) ;
      * `apply_reading_behaviour` — la dérive passive du comportement de lecture,
        seul chemin par lequel `attention` bouge sans LLM.

    Persistance best-effort dans `session_gauges` dès qu'un `session_id` est connu
    (alimente le radar de stats) — un incident n'interrompt jamais la lecture."""

    def __init__(self, session_id: int | None = None, user_id: int = DEFAULT_USER_ID) -> None:
        self.session_id = None
        try:
            profile = ensure_profile(user_id)
        except Exception:
            profile = {}
        self._gauges = make_gauges(profile)
        self._t0 = time.monotonic()
        self._last_passive_record = 0.0
        if session_id is not None:
            self.attach_session(session_id)

    def attach_session(self, session_id: int) -> None:
        """Rattache la session et fige son AMORCE (profil × 0,8) en base.

        Le lecteur ouvre son WebSocket avant de connaître le `session_id` : sans
        ce rattachement explicite, la première ligne écrite dans `session_gauges`
        était déjà une mesure, et plus rien ne disait d'où la session était partie.
        La finalisation a besoin de ce repère pour ne remonter au profil que les
        jauges réellement exercées (cf. `nudge_metacog_profile`)."""
        if self.session_id is not None:
            return
        self.session_id = int(session_id)
        self._record()

    def apply(
        self,
        evaluation: dict | None,
        response_time_ms: int | None = None,
        consecutive_incorrect: int = 0,
    ) -> dict[str, float]:
        """Intègre les signaux d'une réponse/évaluation puis renvoie l'état courant."""
        update_gauges_from_evaluation(
            self._gauges,
            evaluation or {},
            response_time_ms=response_time_ms,
            consecutive_incorrect=consecutive_incorrect,
        )
        self._record()
        return self.snapshot()

    def apply_reading_behaviour(
        self,
        elapsed_s: float,
        stagnant_s: float,
        pages_progressed: int,
        away: bool,
    ) -> dict[str, float]:
        """Dérive passive de l'attention (appelée à chaque tick du lecteur).

        La dérive NÉGATIVE s'arrête à `ATTENTION_PASSIVE_FLOOR` : ne rien faire
        pendant une lecture ne doit pas pouvoir vider la jauge, seulement la faire
        descendre sous le seuil d'intervention. Un crédit positif, lui, s'applique
        toujours. Persistance limitée à une écriture par minute : le tick tourne
        toutes les 5 s, et six lignes par tick noieraient la table."""
        delta = reading_attention_delta(elapsed_s, stagnant_s, pages_progressed, away)
        gauge = self._gauges.get("attention")
        if gauge is None or not delta:
            return self.snapshot()
        if delta < 0:
            delta = max(delta, ATTENTION_PASSIVE_FLOOR - gauge.value)
            if delta >= 0:
                return self.snapshot()
        gauge.apply_delta(delta)

        now = time.monotonic()
        if now - self._last_passive_record >= ATTENTION_PERSIST_EVERY_S:
            self._last_passive_record = now
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
    """Analyse LLM de la session + LA question de réflexion personnalisée.

    Best-effort : renvoie une analyse vide et une question de la banque locale si
    le LLM est indisponible. Les deux voyagent ensemble parce qu'ils s'affichent
    ensemble — le sas montre déjà ses deux questions fixes pendant ce temps."""
    metrics = session_metrics(session_id)
    # Mêmes jauges que la finalisation : une jauge restée à son amorce n'a rien
    # mesuré, et le prompt la commenterait comme un « net retrait » sur le profil.
    session_gauges = _measured_gauges(session_id)
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

    summary: dict = {}
    try:
        from llm.ollama_client import generate_session_summary_async
        from services.llm_bridge import run_llm_sync

        result = run_llm_sync(
            lambda ok, err: generate_session_summary_async(context, ok, err),
        )
        summary = (result or {}).get("session_summary") or {}
    except Exception:  # pragma: no cover - best-effort, LLM indisponible
        logger.debug("Analyse de session ignorée (LLM indisponible)", exc_info=True)

    recent = _safe(lambda: get_recent_reflection_questions(user_id), [])
    return {
        "analysis": str(summary.get("qualitative_summary") or ""),
        "question": pick_reflection_question(
            summary.get("metacognitive_questions") or [],
            avoid=list(REFLECTION_QUESTIONS) + list(recent),
            seed_context=session_id,
        ),
    }


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _reflection_pairs(questions: list[str] | None, responses: list[str] | None) -> list[dict]:
    """Apparie chaque réponse avec l'intitulé RÉELLEMENT posé.

    Le sas envoie ses questions avec les réponses : la troisième est générée, on
    ne peut donc plus la retrouver dans une constante. `questions` absent (appel
    interne, séance de langue) -> on retombe sur les questions fixes."""
    questions = list(questions or [])
    pairs: list[dict] = []
    for order, response in enumerate(responses or []):
        if order < len(questions) and str(questions[order] or "").strip():
            label = str(questions[order]).strip()
        elif order < len(REFLECTION_QUESTIONS):
            label = REFLECTION_QUESTIONS[order]
        else:
            label = f"Réflexion {order + 1}"
        pairs.append({"question": label, "answer": str(response or "")})
    return pairs


def _measure_meta_cognition(
    pairs: list[dict],
    metrics: dict,
    profile_gauges: dict,
) -> float | None:
    """Score de métacognition (0-100) tiré des réponses du sas de sortie.

    C'est la mesure que les prompts d'évaluation annoncent depuis toujours
    (« meta_cognition sera évaluée dans le sas de fin de session ») et qui
    n'existait nulle part : `meta_cognition` ne bougeait que par micro-deltas.
    Renvoie None si l'étudiant n'a rien écrit — on ne note pas un silence."""
    questions = [pair["question"] for pair in pairs]
    answers = [pair["answer"] for pair in pairs]
    if not any(answer.strip() for answer in answers):
        return None

    context = {
        "questions": questions,
        "answers": answers,
        "session_context": metrics or {},
        "user_profile": profile_gauges or {},
    }
    analysis: dict | None = None
    try:
        from llm.ollama_client import analyze_meta_cognition_answers_async
        from services.llm_bridge import run_llm_sync

        analysis = run_llm_sync(
            lambda ok, err: analyze_meta_cognition_answers_async(context, ok, err),
        )
    except Exception:  # LLM indisponible : l'analyse locale suffit à noter
        logger.debug("Analyse métacognitive LLM ignorée", exc_info=True)
    if not analysis:
        analysis = fallback_meta_cognition_analysis(
            questions, answers, metrics or {}, profile_gauges or {}
        )
    try:
        return clamp_gauge(float(analysis.get("score", 50.0)))
    except (TypeError, ValueError):
        return None


def _criteria_trends(user_id: int) -> dict[str, dict]:
    """Tendance longitudinale par critère, sur TOUT l'historique du profil.

    L'analyse de profil décrivait la dernière séance parce qu'elle ne recevait
    que la dernière séance. Ce résumé lui donne la trajectoire : d'où part
    chaque critère, où il en est, et sur combien de sessions mesurées."""
    trends: dict[str, dict] = {}
    for criterion, rows in get_history_by_criterion(user_id).items():
        values = [float(value) for (_sid, value, _at) in rows]
        if not values:
            continue
        recent = values[-5:]
        trends[criterion] = {
            "first": round(values[0], 1),
            "current": round(values[-1], 1),
            "delta_total": round(values[-1] - values[0], 1),
            "recent": [round(v, 1) for v in recent],
            "sessions_measured": len(values),
        }
    return trends


def _update_general_analysis(
    session_id: int | None,
    pairs: list[dict],
    metrics: dict,
    session_gauges: dict,
    user_id: int,
) -> None:
    """Met à jour l'analyse générale (évolutive) de l'apprenant — best-effort.

    Le portrait porte sur l'apprenant, pas sur la séance : la séance qui vient de
    s'achever n'est qu'un indice de plus, versé à côté de l'historique complet."""
    try:
        profile = get_profile(user_id) or {}
        profile_gauges = {k: float(profile.get(k, 50.0)) for k in CRITERIA}
        context = {
            "profile": profile_gauges,
            "sessions_count": int(profile.get("sessions_count") or 0),
            "criteria_trends": _safe(lambda: _criteria_trends(user_id), {}) or {},
            "session_metrics": metrics,
            "session_gauges": session_gauges or {},
            "reflections": list(pairs),
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


def _measured_gauges(session_id: int) -> dict[str, float]:
    """Jauges de fin de session, AMPUTÉES de celles qui n'ont jamais bougé.

    Une session démarre à profil × 0,8. Une jauge que la séance n'a pas exercée
    finit donc exactement à son amorce — 20 % sous le profil — et la remonter
    telle quelle tirait le profil vers le bas à chaque session, sans qu'aucune
    mesure ne le justifie. On ne remonte que ce qui a bougé ; le moteur de profil
    laisse les autres critères intacts (`update_profile_gauges_from_session`
    retombe sur la valeur courante quand un critère est absent)."""
    latest = get_latest_gauges(session_id)
    seed = get_first_gauges(session_id)
    measured = {
        criterion: value
        for criterion, value in latest.items()
        if abs(value - seed.get(criterion, value)) > 1e-9
    }
    untouched = sorted(set(latest) - set(measured))
    if untouched:
        logger.info("Session %s : critères restés à l'amorce, non remontés : %s", session_id, untouched)
    return measured


def _session_measures(session_id: int | None, metrics: dict) -> int | None:
    """Combien de fois cette séance a réellement MESURÉ l'apprenant.

    Une mesure = une réponse évaluée ou une question posée à l'assistant, c'est-à-dire
    un passage par le LLM qui a bougé les jauges. La dérive passive d'attention
    n'en est pas une : elle observe la lecture, elle ne teste rien.

    `None` quand l'appelant ne fournit rien à compter (il affirme alors ses jauges,
    cf. `metacog.profile.compute_confidence`)."""
    answered = metrics.get("questions_answered")
    if session_id is None:
        return int(answered) if answered is not None else None
    total = int(answered or 0)
    total += _safe(lambda: count_assistant_questions(int(session_id)), 0)
    return total


def nudge_metacog_profile(
    user_id: int,
    score: float,
    responses: list[str],
    metrics: dict,
    session_id: int | None = None,
    session_gauges: dict | None = None,
    questions: list[str] | None = None,
    measures: int | None = None,
) -> dict:
    """Finalisation métacognitive partagée (lecture PDF *et* séance de langue).

    Persiste les réflexions, note la métacognition à partir de ces réflexions,
    fait glisser le profil long terme vers le score de la session (jauges live si
    dispo, sinon EMA des 3 critères clés vers le taux de réussite), et régénère
    l'analyse générale de l'apprenant. `session_id=None` pour une séance de langue
    (colonnes FK nullables). Renvoie les nouvelles valeurs des critères.

    **Le profil ne bouge qu'à hauteur de ce qui a été mesuré** : une séance sans
    aucune mesure n'y touche pas (elle compte quand même comme une session), une
    séance courte pèse au prorata (`compute_confidence`). Sans ce garde-fou, une
    session où l'étudiant n'a répondu à rien tirait trois critères vers 0 — vers
    exactement 0 à la première session, où alpha vaut 1.
    """
    pairs = _reflection_pairs(questions, responses)
    for order, pair in enumerate(pairs):
        save_session_reflection(session_id, pair["question"], pair["answer"], user_id, order)

    # La série d'étude avance ICI, à l'unique point par lequel passent les trois
    # finalisations (lecture, séance de langue, quiz) — et pas dans un `GET`.
    # Best-effort : une série non enregistrée ne doit pas faire échouer une
    # finalisation qui, elle, a bien eu lieu.
    _safe(lambda: record_study_day(user_id), None)

    profile = ensure_profile(user_id)
    profile_gauges = {c: float(profile.get(c, 50.0)) for c in CRITERIA}
    if session_gauges is None and session_id is not None:
        session_gauges = _measured_gauges(session_id)
    if measures is None:
        measures = _session_measures(session_id, metrics or {})

    if measures == 0:
        # Rien n'a été mesuré : la session a eu lieu (elle compte), mais elle n'a
        # aucune raison de déplacer le profil.
        logger.info("Session %s finalisée sans aucune mesure : profil inchangé", session_id)
        update_profile_values(user_id, {}, increment_sessions=True)
        _update_general_analysis(session_id, pairs, metrics, session_gauges or {}, user_id)
        return {}

    confidence = compute_confidence(measures)
    # La métacognition se mesure ici, et nulle part ailleurs : sur ce que
    # l'étudiant écrit dans le sas de sortie.
    meta_score = _measure_meta_cognition(pairs, metrics, profile_gauges)

    if session_gauges:
        # Canal temps réel disponible : tout le profil (6 critères) glisse vers les
        # jauges live via le moteur unique `metacog.profile.update_profile`
        # (historique par critère + incrément du compteur de sessions inclus).
        session_score = dict(session_gauges)
        if meta_score is not None:
            session_score["meta_cognition"] = meta_score
        updated = update_profile(user_id, session_score, session_id, confidence=confidence)
        new_values: dict[str, float] = {c: float(updated.get(c, 50.0)) for c in CRITERIA}
    else:
        # Repli (séance sans canal temps réel) : le taux de réussite n'informe
        # honnêtement que ces trois critères — plus la métacognition quand le sas
        # a été rempli. On ne bouge pas les autres plutôt que d'inventer une
        # mesure — mais on utilise le MÊME alpha adaptatif.
        alpha = compute_alpha(int(profile.get("sessions_count") or 0)) * confidence
        targets = {criterion: float(score) for criterion in _PROFILE_NUDGE_CRITERIA}
        if meta_score is not None:
            targets["meta_cognition"] = meta_score
        new_values = {}
        for criterion, target in targets.items():
            before = float(profile.get(criterion, 50.0))
            after = clamp_gauge(before * (1 - alpha) + target * alpha)
            new_values[criterion] = after
            insert_history(user_id, session_id, criterion, before, after, target, alpha)
        update_profile_values(user_id, new_values, increment_sessions=True)

    # Analyse générale de l'apprenant (best-effort, après le nudge profil).
    _update_general_analysis(session_id, pairs, metrics, session_gauges or {}, user_id)
    return new_values


def finalize_session(
    session_id: int,
    responses: list[str],
    questions: list[str] | None = None,
    user_id: int = DEFAULT_USER_ID,
) -> dict:
    metrics = session_metrics(session_id)
    score = float(metrics["success_rate"])
    nudge_metacog_profile(
        user_id, score, responses, metrics,
        session_id=session_id, questions=questions,
    )
    # La série a déjà avancé dans `nudge_metacog_profile` : on la relit pour que
    # le sas de sortie puisse l'annoncer sans un aller-retour de plus.
    return {"ok": True, "score": score, "streak": _safe(lambda: get_streak(user_id), {})}
