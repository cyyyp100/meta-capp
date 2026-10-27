# services/session.py — Cycle de vie d'une session de lecture + métriques + finalisation.
#
# start -> (lecture, Q&R persistées) -> end (métriques) -> finalize (réflexions
# + nudge du profil métacognitif vers le score de session).
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone

from config.settings import (
    ATTENTION_ENGAGEMENT_COOLDOWN_S,
    ATTENTION_ENGAGEMENT_CREDIT,
    ATTENTION_PASSIVE_FLOOR,
    ATTENTION_PERSIST_EVERY_S,
    GAUGE_ASK_CURIOSITY_SCALE,
    PROFILE_SESSION_KIND_WEIGHT,
)
from db.answers import get_answers_for_session
from db.page_dwell import get_page_dwell
from db.metacog import (
    CRITERIA,
    ensure_profile,
    get_history_by_criterion,
    get_profile,
    insert_history,
    set_general_analysis,
    update_profile_values,
)
from db.practice_sessions import get_practice_session, mark_finalized
from db.questions import count_assistant_questions
from db.session_gauges import (
    PRACTICE,
    READING,
    get_first_gauges,
    get_latest_gauges,
    get_session_gauges,
    record_gauges,
)
from db.session_pauses import get_session_pauses
from db.session_reflections import (
    get_recent_reflection_questions,
    save_session_reflection,
)
from db.sessions import (
    close_session,
    get_session,
    list_open_sessions,
    list_unfinalized_sessions,
    mark_session_finalized,
    set_session_analysis,
    update_session_progress,
)
from db.sessions import delete_session as _delete_session
from db.sessions import end_session as _end_session
from db.sessions import start_session as _start_session
from db.user import DEFAULT_USER_ID, get_streak, record_study_day
from i18n import t
from llm.ollama_client import SESSION_SUMMARY_FALLBACK, background_tasks, cancel_pending_generations
from metacog.gauges import (
    VERDICT_CRITERIA,
    clamp_gauge,
    make_gauges,
    reading_attention_delta,
    snapshot,
    update_gauges_from_evaluation,
)
from metacog.profile import compute_alpha, compute_confidence, update_profile
from metacog.reflection import fallback_meta_cognition_analysis, pick_reflection_question
from services import llm_models, session_memory, warmup
from services.pause import summarize as summarize_pauses

logger = logging.getLogger("services.session")

__all__ = [
    "reflection_questions",
    "start_session",
    "end_session",
    "abandon_session",
    "session_metrics",
    "session_analysis",
    "finalize_session",
    "nudge_metacog_profile",
    "close_abandoned_sessions",
    "finalize_pending_sessions",
    "LiveGauges",
]

# Les questions FIXES du sas de sortie. Il y en a deux : l'étudiant commence à
# écrire immédiatement, pendant que le LLM prépare la troisième (personnalisée,
# livrée avec l'analyse de session — cf. `session_analysis`). Trois questions
# figées faisaient attendre le modèle pour rien ; trois questions générées
# faisaient attendre l'étudiant devant un écran vide.
# Elles suivent la langue de l'interface (clés `session.reflection_q*`) : une
# liste figée en français les montrait telles quelles à un sas en anglais.
_REFLECTION_KEYS = ("session.reflection_q1", "session.reflection_q2")


def reflection_questions() -> list[str]:
    return [t(key) for key in _REFLECTION_KEYS]

# Critères que le seul taux de réussite informe honnêtement, quand la séance n'a
# pas de courbe de jauges. Les trois autres (curiosité, créativité, métacognition)
# ne sont pas déduisibles d'un score : on les laisse inchangés. Même liste que
# celle du modèle du verdict (`metacog.gauges.VERDICT_CRITERIA`), par définition.
_PROFILE_NUDGE_CRITERIA = VERDICT_CRITERIA


class LiveGauges:
    """Jauges métacognitives live d'une session de lecture web (en mémoire).

    Seed = profil long terme rapproché du neutre (`initialize_session_gauges`),
    puis ces sources de mouvement :

      * `apply` — les `metacog_signals`/`verdict` de l'évaluation d'une réponse,
        plus la série d'erreurs ; `apply_question` — ceux de la réponse de
        Clikoda à une question de l'élève, curiosité freinée ;
      * `apply_reading_behaviour` — la dérive passive du comportement de lecture ;
      * `credit_engagement` — ce que l'élève FAIT de sa lecture (questionner,
        répondre, surligner, annoter) ;
      * `recover_attention` — le crédit d'une pause prise ;
      * `apply_warmup` — l'effet du RYTHME de la révision éclair du sas
        d'entrée (cf. `services.warmup`), versé une fois, à l'entrée en lecture.

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
        # Dernier crédit versé, par geste (`credit_engagement`).
        self._last_engagement: dict[str, float] = {}
        if session_id is not None:
            self.attach_session(session_id)

    def attach_session(self, session_id: int) -> None:
        """Rattache la session et fige son AMORCE en base.

        Le lecteur ouvre son WebSocket avant de connaître le `session_id` : sans
        ce rattachement explicite, la première ligne écrite dans `session_gauges`
        était déjà une mesure, et plus rien ne disait d'où la session était partie.
        La finalisation a besoin de ce repère pour ne remonter au profil que les
        jauges réellement exercées (cf. `nudge_metacog_profile`)."""
        if self.session_id is not None:
            return
        self.session_id = int(session_id)
        self._record()

    def apply(self, evaluation: dict | None, consecutive_incorrect: int = 0) -> dict[str, float]:
        """Intègre l'évaluation d'une réponse puis renvoie l'état courant.

        Le TEMPS mis à répondre n'y coûte rien à l'attention, contrairement à une
        séance de pratique : dans le lecteur, la dérive passive observe déjà ce
        temps-là (fenêtre masquée, aucun geste), et le compter une seconde fois
        coûtait jusqu'à 6 points à chaque réponse rédigée — passé 12 s, c'est-à-
        dire toujours (de 58 s à 14 min sur les séances 59 et 60)."""
        update_gauges_from_evaluation(
            self._gauges,
            evaluation or {},
            consecutive_incorrect=consecutive_incorrect,
        )
        self._record()
        return self.snapshot()

    def apply_question(self, result: dict | None) -> dict[str, float]:
        """Intègre les signaux de la réponse de Clikoda à une question de l'élève.

        Questionner de sa propre initiative est le signal de curiosité par
        excellence, et le prompt exige un signal d'au moins 1,0 : +12,8 points par
        question, la jauge saturait à 100 en quatre questions, à chaque séance.
        La question pèse `GAUGE_ASK_CURIOSITY_SCALE` de ce signal — et toute
        hausse de la curiosité ralentit à l'approche de 100 (`GaugeState.update`)."""
        update_gauges_from_evaluation(
            self._gauges,
            result or {},
            signal_scale={"curiosity": GAUGE_ASK_CURIOSITY_SCALE},
        )
        self._record()
        return self.snapshot()

    def credit_engagement(self, action: str, now: float | None = None) -> dict[str, float]:
        """Crédit d'attention d'un geste de lecture active (`ATTENTION_ENGAGEMENT_CREDIT`).

        Au plus une fois par `ATTENTION_ENGAGEMENT_COOLDOWN_S` et par geste : une
        rafale de surlignages est UN moment d'engagement. Un geste inconnu ne
        crédite rien. Il ne peut que remonter la jauge."""
        points = float(ATTENTION_ENGAGEMENT_CREDIT.get(action, 0.0))
        gauge = self._gauges.get("attention")
        if gauge is None or points <= 0.0:
            return self.snapshot()
        now = time.monotonic() if now is None else float(now)
        last = self._last_engagement.get(action)
        if last is not None and now - last < ATTENTION_ENGAGEMENT_COOLDOWN_S:
            return self.snapshot()
        self._last_engagement[action] = now
        gauge.apply_delta(points)
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

    def recover_attention(self, points: float) -> dict[str, float]:
        """Crédit d'attention d'une pause réellement prise (`services.pause.attention_credit`).

        La dérive passive est suspendue pendant la pause (cf. le ticker du
        lecteur) ; ce crédit-ci est le bénéfice de la pause elle-même, versé une
        fois au retour et au prorata du temps effectivement passé loin de la
        page. Il ne peut que remonter la jauge."""
        gauge = self._gauges.get("attention")
        if gauge is None or float(points) <= 0.0:
            return self.snapshot()
        gauge.apply_delta(float(points))
        self._record()
        return self.snapshot()

    def apply_warmup(self, deltas: dict[str, float]) -> dict[str, float]:
        """Verse l'effet de la révision éclair (deltas de `services.warmup`).

        À appeler APRÈS `attach_session` : l'amorce doit être en base avant,
        sans quoi le warm-up passerait pour le point de départ de la séance et
        `_measured_gauges` ne le verrait jamais."""
        for criterion, delta in (deltas or {}).items():
            gauge = self._gauges.get(criterion)
            if gauge is not None and delta:
                gauge.apply_delta(float(delta))
        self._record()
        return self.snapshot()

    def elapsed_s(self) -> float:
        """Temps de lecture de la séance (pauses reprises exclues) : l'axe `t`
        des mesures, et le battement qui date une séance quittée sans « Terminer »."""
        return max(0.0, time.monotonic() - self._t0)

    def skip(self, seconds: float) -> None:
        """Retire une pause de l'horloge des mesures : le `t` de `session_gauges`
        reste du temps de LECTURE, et la courbe de la séance n'est pas étirée
        d'un plat de la longueur de la pause."""
        self._t0 += max(0.0, float(seconds))

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


def end_session(session_id: int, duration_s: int | None = None) -> dict:
    """Clôt la session et coupe Clikoda — en file ET en vol.

    Le nombre de pages lues ne vient jamais du client : le socket du lecteur
    l'écrit à chaque tick et à sa fermeture (au moins PAGE_READ_MIN_DWELL_S par
    page, cf. services/session_memory.pages_read), et la clôture lit le compte
    EXACT de sa mémoire s'il est encore ouvert — le dernier tick peut avoir 5 s
    de retard, et une page lue juste avant « Terminer » manquerait à l'écran de
    fin.

    « Terminer » arrive souvent pendant qu'une correction ou une intervention
    est en cours : leur résultat n'a plus de destinataire, et il n'y a qu'UN
    worker LLM. Sans cette coupure, le bilan du sas de sortie (`session_analysis`)
    attendait derrière une génération dont plus personne ne voulait. La coupure
    précède l'écriture : le bilan, enfilé après la réponse de cet appel, capture
    un token neuf et n'est pas concerné."""
    cancel_pending_generations()
    _end_session(session_id, duration_s=duration_s)
    live = session_memory.live_pages_read(session_id)
    if live is not None:
        update_session_progress(session_id, pages_read=live)
    return session_metrics(session_id)


def abandon_session(session_id: int) -> dict:
    """Efface une session qui n'a pas eu lieu : mauvais document ouvert, retour
    à la bibliothèque depuis le sas d'entrée.

    Une session est ouverte dès que le lecteur se monte, AVANT le sas ; la clore
    normalement la ferait compter (durée, frise de progression, série) alors
    que rien n'a été lu. On ne touche qu'à une session encore OUVERTE et sans
    réponse : une session close ou déjà jouée est une trace d'apprentissage,
    elle se termine par `end_session`, jamais ici."""
    session = get_session(session_id)
    if session is None:
        return {"abandoned": False}
    if session.get("ended_at") or get_answers_for_session(session_id):
        raise ValueError("Session déjà jouée : à terminer, pas à abandonner.")
    return {"abandoned": _delete_session(session_id)}


def session_metrics(session_id: int) -> dict:
    session = get_session(session_id) or {}
    answers = get_answers_for_session(session_id)
    total = len(answers)
    correct = sum(1 for a in answers if a.get("verdict") == "correct")
    partial = sum(1 for a in answers if a.get("verdict") == "partial")
    success = round(100 * (correct + 0.5 * partial) / total) if total else 0
    try:
        pauses = summarize_pauses(get_session_pauses(session_id))
    except Exception:  # best-effort : une séance sans pause lisible reste une séance
        pauses = summarize_pauses([])
    return {
        "session_id": session_id,
        # Temps de LECTURE : les pauses en sont exclues (cf. `pause_s`).
        "duration_s": int(session.get("duration_s") or 0),
        "pages_read": int(session.get("pages_read") or 0),
        "questions_answered": total,
        "correct": correct,
        "success_rate": success,
        # pauses, pause_s, pauses_after_recommendation (services/pause.summarize)
        **pauses,
        "reflection_questions": reflection_questions(),
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
        # Les pauses et ce qui les a précédées : le bilan distingue le repos
        # conseillé suivi (autorégulation) d'un simple arrêt.
        "pauses": metrics["pauses"],
        "pause_s": metrics["pause_s"],
        "pauses_after_recommendation": metrics["pauses_after_recommendation"],
    }
    # Le rythme de la révision éclair (temps par carte, par face, au total) :
    # absent quand la séance n'en a pas eu, pour ne pas commenter un vide.
    warmup_summary = _safe(lambda: warmup.summary(session_id), None)
    if warmup_summary:
        stats["warmup"] = warmup_summary
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

    analysis = str(summary.get("qualitative_summary") or "").strip()
    if analysis and analysis != SESSION_SUMMARY_FALLBACK:
        # Relu dans « Ma progression », comme le bilan d'un quiz : celui d'une
        # séance reprise au démarrage n'a été affiché nulle part ailleurs. Le
        # texte générique du repli (Ollama absent) n'est pas un bilan.
        _safe(lambda: set_session_analysis(session_id, analysis), None)
    recent = _safe(lambda: get_recent_reflection_questions(user_id), [])
    return {
        "analysis": analysis,
        "question": pick_reflection_question(
            summary.get("metacognitive_questions") or [],
            avoid=reflection_questions() + list(recent),
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
        elif order < len(_REFLECTION_KEYS):
            label = t(_REFLECTION_KEYS[order])
        else:
            label = t("session.reflection_n", n=order + 1)
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


def _measured_gauges(session_id: int, scope: str = READING) -> dict[str, float]:
    """Jauges de fin de session, AMPUTÉES de celles qui n'ont jamais bougé.

    Une session démarre à son amorce (le profil rapproché du neutre). Une jauge
    que la séance n'a pas exercée finit donc exactement là, et la remonter telle
    quelle tirait le profil vers cette amorce à chaque session, sans qu'aucune
    mesure ne le justifie. On ne remonte que ce qui a bougé ; le moteur de profil
    laisse les autres critères intacts (`update_profile_gauges_from_session`
    retombe sur la valeur courante quand un critère est absent).

    `scope` : une lecture (`session_gauges`) ou une séance de pratique, quiz ou
    langue (`practice_session_gauges`) — la règle est la même."""
    latest = get_latest_gauges(session_id, scope=scope)
    seed = get_first_gauges(session_id, scope=scope)
    measured = {
        criterion: value
        for criterion, value in latest.items()
        if abs(value - seed.get(criterion, value)) > 1e-9
    }
    untouched = sorted(set(latest) - set(measured))
    if untouched:
        logger.info("Session %s : critères restés à l'amorce, non remontés : %s", session_id, untouched)
    return measured


def _measured_by(practice: dict | None) -> dict[str, int]:
    """Mesures par critère d'une séance de pratique (`services.practice.record`)."""
    counts = ((practice or {}).get("details") or {}).get("measured_by") or {}
    return {str(criterion): int(n) for criterion, n in counts.items() if int(n) > 0}


def _session_kind(session_id: int | None, practice: dict | None) -> str:
    """Catégorie de la séance finalisée : celle de la séance de pratique, ou une lecture."""
    if practice:
        return str(practice.get("kind") or "")
    return "reading" if session_id is not None else ""


def _kind_weight(kind: str) -> float:
    """Poids de la catégorie dans l'évolution du profil (`PROFILE_SESSION_KIND_WEIGHT`).

    Une catégorie inconnue garde le plein poids : on ne réduit pas en silence
    l'effet d'une séance qu'on ne sait pas nommer."""
    return max(0.0, min(1.0, float(PROFILE_SESSION_KIND_WEIGHT.get(kind, 1.0))))


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
    practice_session_id: int | None = None,
    measure_meta: bool = True,
    kind: str | None = None,
    meta_delta: float | None = None,
    study_day: date | None = None,
    refresh_analysis: bool = True,
) -> dict:
    """Finalisation métacognitive partagée : lecture, quiz, séance de langue.

    Persiste les réflexions, note la métacognition à partir de ces réflexions,
    fait glisser le profil long terme vers les jauges de la séance, et régénère
    l'analyse générale de l'apprenant. Renvoie les nouvelles valeurs des critères.

    La séance est une lecture (`session_id`, jauges live) ou une séance de
    pratique, quiz ou langue (`practice_session_id`, jauges rejouées depuis ses
    mesures — cf. `services.practice`). Sans aucune des deux (ancien client), le
    repli fait glisser les 3 critères de performance vers le taux de réussite.

    **Le profil ne bouge qu'à hauteur de ce qui a été mesuré** : une séance sans
    aucune mesure n'y touche pas (elle compte quand même comme une session), une
    séance courte pèse au prorata (`compute_confidence`). Sans ce garde-fou, une
    session où l'étudiant n'a répondu à rien tirait trois critères vers 0 — vers
    exactement 0 à la première session, où alpha vaut 1.

    Une séance de pratique ne se finalise qu'UNE fois (`finalized_at`) : un quiz
    quitté puis clos, une clôture renvoyée, ne font pas glisser le profil deux fois.
    `measure_meta=False` : les réponses sont gardées sans être notées (le ressenti
    à choix du feuilleton n'est pas une réflexion écrite). `meta_delta` : la
    métacognition de la séance vaut alors le profil + ce pas, sans LLM — le
    feuilleton le donne selon que son ressenti a eu une réponse ou non. C'est une
    mesure à part entière : elle déplace la métacognition même quand rien
    d'autre n'a été mesuré, d'une part α, sans prorata du nombre de mesures.

    **Une séance pèse selon sa catégorie** (`PROFILE_SESSION_KIND_WEIGHT`) : une
    lecture et une séance de langue font apprendre, un quiz vérifie ce qui a été
    appris et déplace moins le profil. La catégorie se déduit de la séance
    (lecture, ou celle de la séance de pratique) ; `kind` la donne quand il n'y a
    pas de séance (ancien client du quiz, leçon close avant les séances de pratique).

    `study_day` : le jour d'étude à compter (aujourd'hui par défaut) — celui de
    la séance quand elle est finalisée le lendemain, au démarrage.
    `refresh_analysis=False` : le portrait de l'apprenant n'est pas régénéré
    (aucun appel au LLM — reprise en mode économe).
    """
    if practice_session_id is not None and not mark_finalized(int(practice_session_id)):
        logger.info("Séance de pratique %s déjà finalisée : profil inchangé", practice_session_id)
        return {}

    pairs = _reflection_pairs(questions, responses)
    for order, pair in enumerate(pairs):
        save_session_reflection(
            session_id, pair["question"], pair["answer"], user_id, order,
            practice_session_id=practice_session_id,
        )

    # La série d'étude avance ICI, à l'unique point par lequel passent les trois
    # finalisations (lecture, séance de langue, quiz) — et pas dans un `GET`.
    # Best-effort : une série non enregistrée ne doit pas faire échouer une
    # finalisation qui, elle, a bien eu lieu.
    _safe(lambda: record_study_day(user_id, day=study_day), None)

    profile = ensure_profile(user_id)
    profile_gauges = {c: float(profile.get(c, 50.0)) for c in CRITERIA}
    if session_gauges is None and session_id is not None:
        session_gauges = _measured_gauges(session_id)
    elif session_gauges is None and practice_session_id is not None:
        session_gauges = _measured_gauges(int(practice_session_id), scope=PRACTICE)
        if not session_gauges:
            # Une séance de pratique a sa courbe : si rien n'y a bougé, rien n'a
            # été mesuré. Surtout pas de repli vers le taux de réussite, qui
            # tirerait trois critères vers un score que personne n'a obtenu.
            measures = 0
    if measures is None:
        measures = _session_measures(session_id, metrics or {})

    practice = (
        _safe(lambda: get_practice_session(int(practice_session_id)), None)
        if practice_session_id is not None else None
    )
    kind_weight = _kind_weight(kind or _session_kind(session_id, practice))

    if measures == 0:
        if meta_delta is not None:
            # Seule la question de métacognition a mesuré la séance : elle seule bouge.
            meta_target = clamp_gauge(profile_gauges["meta_cognition"] + float(meta_delta))
            updated = update_profile(
                user_id, {"meta_cognition": meta_target}, session_id,
                confidence={"meta_cognition": kind_weight}, practice_session_id=practice_session_id,
            )
            if refresh_analysis:
                _update_general_analysis(session_id, pairs, metrics, session_gauges or {}, user_id)
            return {c: float(updated.get(c, 50.0)) for c in CRITERIA}
        # Rien n'a été mesuré : la session a eu lieu (elle compte), mais elle n'a
        # aucune raison de déplacer le profil.
        logger.info("Session %s finalisée sans aucune mesure : profil inchangé", session_id)
        update_profile_values(user_id, {}, increment_sessions=True)
        if refresh_analysis:
            _update_general_analysis(session_id, pairs, metrics, session_gauges or {}, user_id)
        return {}

    confidence = compute_confidence(measures)
    # La métacognition se mesure ici, et nulle part ailleurs : sur ce que
    # l'étudiant écrit dans le sas de sortie — ou, sans rien d'écrit à noter, sur
    # le fait qu'il ait répondu à la question qui la sollicite (`meta_delta`).
    meta_weight = confidence * kind_weight
    if meta_delta is not None:
        meta_score = clamp_gauge(profile_gauges["meta_cognition"] + float(meta_delta))
        meta_weight = kind_weight
    elif measure_meta:
        meta_score = _measure_meta_cognition(pairs, metrics, profile_gauges)
    else:
        meta_score = None
    if meta_score is not None and session_id is not None:
        # Une révision éclair cliquée sans lire a déjà coûté de la métacognition
        # à la jauge live ; la note du sas de sortie REMPLACE cette jauge, elle
        # reprend donc ce coût — sinon il s'effaçait dès qu'on écrivait.
        warmup_meta = _safe(lambda: warmup.session_deltas(int(session_id)), {}).get("meta_cognition", 0.0)
        meta_score = clamp_gauge(meta_score + warmup_meta)

    if session_gauges:
        # Courbe de jauges disponible : tout le profil (6 critères) glisse vers les
        # jauges de la séance via le moteur unique `metacog.profile.update_profile`
        # (historique par critère + incrément du compteur de sessions inclus).
        session_score = dict(session_gauges)
        weights: float | dict[str, float] = confidence * kind_weight
        measured_by = _measured_by(practice)
        if measured_by:
            # Séance de pratique : chaque critère pèse à hauteur des mesures qui
            # l'ont informé — une curiosité relevée une fois ne pèse pas comme une
            # rétention éprouvée dix fois.
            weights = {
                criterion: compute_confidence(n) * kind_weight for criterion, n in measured_by.items()
            }
        if meta_score is not None:
            session_score["meta_cognition"] = meta_score
            if isinstance(weights, dict):
                weights["meta_cognition"] = meta_weight
        updated = update_profile(
            user_id, session_score, session_id,
            confidence=weights, practice_session_id=practice_session_id,
        )
        new_values: dict[str, float] = {c: float(updated.get(c, 50.0)) for c in CRITERIA}
    else:
        # Repli (séance sans canal temps réel) : le taux de réussite n'informe
        # honnêtement que ces trois critères — plus la métacognition quand le sas
        # a été rempli. On ne bouge pas les autres plutôt que d'inventer une
        # mesure — mais on utilise le MÊME alpha adaptatif, et le même poids de catégorie.
        alpha = compute_alpha(int(profile.get("sessions_count") or 0)) * confidence * kind_weight
        targets = {criterion: float(score) for criterion in _PROFILE_NUDGE_CRITERIA}
        if meta_score is not None:
            targets["meta_cognition"] = meta_score
        new_values = {}
        for criterion, target in targets.items():
            before = float(profile.get(criterion, 50.0))
            after = clamp_gauge(before * (1 - alpha) + target * alpha)
            new_values[criterion] = after
            insert_history(
                user_id, session_id, criterion, before, after, target, alpha,
                practice_session_id=practice_session_id,
            )
        update_profile_values(user_id, new_values, increment_sessions=True)

    # Analyse générale de l'apprenant (best-effort, après le nudge profil).
    if refresh_analysis:
        _update_general_analysis(session_id, pairs, metrics, session_gauges or {}, user_id)
    return new_values


def finalize_session(
    session_id: int,
    responses: list[str],
    questions: list[str] | None = None,
    user_id: int = DEFAULT_USER_ID,
    *,
    study_day: date | None = None,
    refresh_analysis: bool = True,
) -> dict:
    """Fin du sas de sortie : réflexions, profil, série d'étude — une seule fois.

    Une seconde finalisation (double envoi, ou la reprise au démarrage d'une
    séance que le sas avait déjà finalisée) ne fait pas glisser le profil deux
    fois : `finalized_at` ne se pose qu'une fois."""
    metrics = session_metrics(session_id)
    score = float(metrics["success_rate"])
    if not mark_session_finalized(session_id):
        logger.info("Session %s déjà finalisée : profil inchangé", session_id)
        return {"ok": True, "score": score, "streak": _safe(lambda: get_streak(user_id), {})}
    nudge_metacog_profile(
        user_id, score, responses, metrics,
        session_id=session_id, questions=questions,
        study_day=study_day, refresh_analysis=refresh_analysis,
    )
    # La série a déjà avancé dans `nudge_metacog_profile` : on la relit pour que
    # le sas de sortie puisse l'annoncer sans un aller-retour de plus.
    return {"ok": True, "score": score, "streak": _safe(lambda: get_streak(user_id), {})}


# ── Séances quittées en fermant le logiciel ─────────────────────────────────
#
# Une lecture n'était close que par « Terminer ». Fermer la fenêtre en pleine
# lecture la laissait ouverte pour toujours : « Session en cours » dans la frise
# de « Ma progression », jamais mesurée dans le profil. Au démarrage suivant,
# elle est close à l'heure de sa dernière trace, puis finalisée comme si l'élève
# avait passé les questions du sas de sortie — avec le bilan de Clikoda, que
# personne n'a lu et qui se relit dans le détail de la séance.


def close_abandoned_sessions() -> dict[str, list[int]]:
    """Démarrage, AVANT toute requête : clôt les lectures restées ouvertes.

    Aucun lecteur ne peut encore y être rattaché (instance unique, serveur qui
    démarre). Une séance où rien n'a été lu — quittée depuis le sas d'entrée —
    est effacée, comme `abandon_session` l'aurait fait. Les autres sont closes
    à l'heure de leur dernière trace : départ + temps de lecture (le battement
    du socket, à défaut la courbe de jauges ou le temps par page) + pauses.
    Uniquement la base : la finalisation, qui peut appeler le LLM, est
    `finalize_pending_sessions`, en thread."""
    closed: list[int] = []
    deleted: list[int] = []
    for session in _safe(list_open_sessions, []):
        sid = int(session["id"])
        try:
            if not _was_read(session):
                if _delete_session(sid):
                    deleted.append(sid)
                continue
            duration = _reading_time_s(session)
            pause_s = summarize_pauses(get_session_pauses(sid))["pause_s"]
            if close_session(sid, _ended_at(session, duration + pause_s), duration):
                closed.append(sid)
        except Exception:  # jamais bloquant au démarrage : la séance attendra
            logger.exception("Clôture de la séance abandonnée %s impossible", sid)
    if closed or deleted:
        logger.info("Séances abandonnées : %s close(s), %s effacée(s) sans lecture", closed, deleted)
    return {"closed": closed, "deleted": deleted}


def finalize_pending_sessions(user_id: int = DEFAULT_USER_ID) -> list[int]:
    """Démarrage, en thread : finalise les lectures closes jamais finalisées.

    Celles que `close_abandoned_sessions` vient de clore, et celles dont le sas
    de sortie a été fermé avec le logiciel. Pour chacune, comme au sas : le
    bilan de Clikoda (persisté), puis la finalisation SANS réponse — « Passer ».
    Le jour d'étude compté est celui de la séance, pas celui du démarrage ; le
    portrait de l'apprenant n'est régénéré qu'une fois, après la dernière. En
    mode économe, rien n'est demandé au LLM (pas de travail de fond) : le profil
    glisse, le bilan reste vide.

    Personne n'attend ces bilans : ils partent en TRAVAIL DE FOND
    (`ollama_client.background_tasks`), après tout ce que le lecteur demande.
    À la priorité du sas de sortie, chacun passait devant les questions et les
    interventions de la lecture qu'on venait d'ouvrir."""
    economy = _safe(llm_models.economy, False)
    pending = _safe(list_unfinalized_sessions, [])
    done: list[int] = []
    for index, session in enumerate(pending):
        sid = int(session["id"])
        try:
            with background_tasks():
                if not economy and not str(session.get("analysis") or "").strip():
                    session_analysis(sid, user_id)
                finalize_session(
                    sid, [], user_id=user_id,
                    study_day=_local_day(session.get("started_at")),
                    # Le portrait de l'apprenant porte sur tout l'historique : une
                    # fois, après la dernière séance reprise, suffit.
                    refresh_analysis=not economy and index == len(pending) - 1,
                )
            done.append(sid)
        except Exception:
            logger.exception("Finalisation de la séance %s impossible", sid)
    if done:
        logger.info("Séances finalisées au démarrage : %s", done)
    return done


def _was_read(session: dict) -> bool:
    """Quelque chose a-t-il eu lieu ? Une page lue, une réponse, une question."""
    sid = int(session["id"])
    return (
        int(session.get("pages_read") or 0) > 0
        or bool(get_answers_for_session(sid))
        or count_assistant_questions(sid) > 0
    )


def _reading_time_s(session: dict) -> int:
    """Le temps de lecture d'une séance quittée sans « Terminer » : le plus long
    de ce qu'elle a laissé (battement, courbe de jauges, temps par page)."""
    sid = int(session["id"])
    heartbeat = float(session.get("duration_s") or 0)
    curve = max((float(row["t"]) for row in get_session_gauges(sid)), default=0.0)
    dwell = sum(float(row.get("dwell_s") or 0.0) for row in get_page_dwell(sid))
    return int(round(max(heartbeat, curve, dwell)))


def _started(started_at: str | None) -> datetime | None:
    """Départ d'une séance, à l'heure locale (SQLite le date en UTC)."""
    try:
        return datetime.fromisoformat(str(started_at)).replace(tzinfo=timezone.utc).astimezone()
    except (TypeError, ValueError):
        return None


def _ended_at(session: dict, elapsed_s: float) -> str:
    """Heure de clôture, au format de `db.sessions.end_session` (locale, naïve)."""
    started = _started(session.get("started_at"))
    if started is None:
        return datetime.now().isoformat()
    return (started + timedelta(seconds=max(0.0, elapsed_s))).replace(tzinfo=None).isoformat()


def _local_day(started_at: str | None) -> date | None:
    started = _started(started_at)
    return started.date() if started else None

