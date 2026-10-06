# metacog/gauges.py — Jauges temps réel
from __future__ import annotations

from dataclasses import dataclass

from config import question_types
from config.settings import (
    ATTENTION_AWAY_PER_MIN,
    ATTENTION_DRIFT_PER_MIN,
    ATTENTION_IDLE_GRACE_S,
    ATTENTION_PROGRESS_BONUS,
    GAUGE_VERDICT_TARGETS,
    GAUGE_VERDICT_WEIGHT,
)
from db.metacog import CRITERIA

SESSION_INHERITANCE_FACTOR = 0.8
PROFILE_SESSION_WEIGHT = 0.1

# Les seuls critères qu'un verdict (ou un taux de réussite) informe honnêtement.
# Être juste ne dit rien de la curiosité, de la créativité ni de la
# métacognition : sans signal du LLM, ces trois-là ne bougent pas.
VERDICT_CRITERIA: tuple[str, ...] = ("attention", "context_comprehension", "retention")
# Marqueurs de créativité qu'une évaluation peut relever (LLM ou forme de la réponse).
CREATIVITY_FLAGS: tuple[str, ...] = (
    "goes_beyond_prompt", "makes_connections", "uses_analogy", "personal_reformulation", "original_hypothesis",
)
# En deçà, un signal du LLM est un zéro arrondi, pas une information.
_INFORMED_SIGNAL = 0.05

# Jauge(s) principalement pilotée(s) par chaque type de question. Le signal LLM
# de ces dimensions est amplifié, les autres atténués : une question de curiosité
# fait surtout bouger `curiosity`, une de contexte surtout `context_comprehension`.
# Déclaré une seule fois dans config/question_types.py, avec le reste du type.
QUESTION_TYPE_TARGET_GAUGES: dict[str, tuple[str, ...]] = question_types.target_gauges_map()
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


def verdict_target(verdict: str | None) -> float | None:
    """Cible d'un verdict (`GAUGE_VERDICT_TARGETS`), None pour tout le reste."""
    if verdict not in GAUGE_VERDICT_TARGETS:
        return None
    return float(GAUGE_VERDICT_TARGETS[verdict])


def score_target(score: float) -> float:
    """Cible d'un score continu (0..1), sur l'échelle des verdicts : 1 vaut
    « correct », 0,5 « partiel », 0 « incorrect », interpolé entre les trois."""
    s = max(0.0, min(1.0, float(score)))
    low = float(GAUGE_VERDICT_TARGETS["incorrect"])
    mid = float(GAUGE_VERDICT_TARGETS["partial"])
    high = float(GAUGE_VERDICT_TARGETS["correct"])
    if s <= 0.5:
        return low + (mid - low) * s / 0.5
    return mid + (high - mid) * (s - 0.5) / 0.5


def update_gauges_from_verdict(
    gauges: dict[str, GaugeState],
    verdict: str | None,
    targets: tuple[str, ...] | list[str],
    *,
    score: float | None = None,
    response_time_ms: int | None = None,
    consecutive_incorrect: int = 0,
) -> dict[str, float]:
    """Mesure SANS signal du LLM : un verdict (ou un score) et les jauges visées.

    Le modèle du lecteur (`update_gauges_from_evaluation`) suppose des signaux :
    privé d'eux, il ne déplace une jauge que de ±1,5 par réponse, et une séance
    de QCM finirait au ras de son amorce (profil × 0,8) — elle tirerait le profil
    vers le bas par construction. Ici, chaque jauge visée parcourt
    `GAUGE_VERDICT_WEIGHT` du chemin vers la cible du verdict : après quelques
    réponses, elle dit le taux de réussite de la séance, d'où qu'elle parte.

    Seuls les critères de performance (`VERDICT_CRITERIA`) sont visés. L'attention
    paie en plus la lenteur et la série d'erreurs, visée ou non : ce sont des
    observations, pas des déductions. Sans verdict ni score, rien ne bouge — un
    signal absent n'est jamais un succès."""
    target = score_target(score) if score is not None else verdict_target(verdict)
    if target is None:
        return snapshot(gauges)
    weight = max(0.0, min(1.0, float(GAUGE_VERDICT_WEIGHT)))
    for criterion in dict.fromkeys(targets or ()):
        gauge = gauges.get(criterion)
        if criterion not in VERDICT_CRITERIA or gauge is None:
            continue
        gauge.value = _clamp(gauge.value + weight * (target - gauge.value))
    penalty = attention_penalty(response_time_ms, consecutive_incorrect)
    if penalty and "attention" in gauges:
        gauges["attention"].apply_delta(-penalty)
    return snapshot(gauges)


def replay(seed: dict | None, measures: list[dict]) -> list[tuple[float, dict[str, float]]]:
    """Courbe de jauges d'une séance de pratique : l'amorce, puis un point par mesure.

    Une séance de quiz ou de langue n'a pas de canal temps réel : ses mesures
    sont enregistrées là où elles vivent (réponses du quiz, tables `lang_*`) et
    rejouées ici, dans l'ordre. Rejouer les mêmes mesures donne la même courbe.

    Une mesure : ``{"t", "verdict", "targets", "score"?, "evaluation"?,
    "question_type"?, "response_time_ms"?}``. Celle qui porte l'évaluation du LLM
    (`evaluation`, signaux compris) suit le modèle du lecteur ; les autres, le
    modèle du verdict. Dans les deux cas, **une mesure ne fait bouger que les
    jauges qu'elle informe** (`_replay_steps`). La série d'erreurs se compte ici,
    comme le fait le lecteur. Une mesure sans verdict, sans score ni évaluation
    est ignorée."""
    return [(t, values) for t, values, _informed in _replay_steps(seed, measures)]


def informed_counts(seed: dict | None, measures: list[dict]) -> dict[str, int]:
    """Combien de mesures ont informé chaque critère pendant la séance.

    C'est le poids de chaque critère à la finalisation : une curiosité relevée
    par une seule réponse rédigée ne pèse pas comme une rétention éprouvée par
    dix QCM (`compute_confidence`, critère par critère)."""
    counts: dict[str, int] = {}
    for _t, _values, informed in _replay_steps(seed, measures):
        for criterion in informed:
            counts[criterion] = counts.get(criterion, 0) + 1
    return counts


def _replay_steps(seed: dict | None, measures: list[dict]):
    """Le rejeu, pas à pas : (t, jauges, critères informés par cette mesure).

    Le modèle du lecteur fait bouger les six jauges à chaque réponse — bonus de
    verdict partout, dérive de la métacognition. Dans le lecteur, une séance en
    compte beaucoup et ses signaux dominent ; dans une séance de pratique, une
    seule réponse rédigée au milieu de QCM laissait la curiosité ou la
    métacognition à un cheveu de leur amorce (profil × 0,8)… et les comptait
    pour mesurées : le profil glissait vers elles, à la baisse. Une mesure ne
    déplace donc ici que ce qu'elle informe ; le reste reprend sa valeur."""
    seed = seed or {}
    default = 50.0 * SESSION_INHERITANCE_FACTOR
    gauges = {c: GaugeState(c, _clamp(float(seed.get(c, default)))) for c in CRITERIA}
    yield 0.0, snapshot(gauges), set()
    position = 0
    streak = 0
    for measure in measures or []:
        verdict = measure.get("verdict")
        score = measure.get("score")
        evaluation = measure.get("evaluation")
        if not evaluation and verdict_target(verdict) is None and score is None:
            continue
        position += 1
        error = verdict == "incorrect" or (score is not None and float(score) < 0.5)
        streak = streak + 1 if error else 0
        response_time_ms = measure.get("response_time_ms")
        if evaluation:
            question_type = measure.get("question_type") or ""
            before = snapshot(gauges)
            update_gauges_from_evaluation(
                gauges,
                {**evaluation, "verdict": verdict, "question_type": question_type},
                response_time_ms=response_time_ms,
                consecutive_incorrect=streak,
            )
            informed = _informed_by_evaluation(evaluation, question_type)
            for criterion, value in before.items():
                if criterion not in informed:
                    gauges[criterion].value = value
        else:
            targets = measure.get("targets") or ()
            update_gauges_from_verdict(
                gauges, verdict, targets,
                score=score, response_time_ms=response_time_ms, consecutive_incorrect=streak,
            )
            informed = {criterion for criterion in targets if criterion in VERDICT_CRITERIA}
            if attention_penalty(response_time_ms, streak):
                informed.add("attention")
        yield float(measure.get("t", position)), snapshot(gauges), informed


def _informed_by_evaluation(evaluation: dict, question_type: str) -> set[str]:
    """Les jauges qu'une évaluation du LLM informe vraiment : celles que vise le
    type de question, celles qu'un signal non nul désigne (LLM ou forme de la
    réponse), et l'attention — que chaque réponse observe (temps, verdict, série).
    Le bonus de verdict seul n'informe pas une curiosité ; la dérive de la
    métacognition n'est pas une mesure (elle se note au sas de sortie)."""
    informed = set(QUESTION_TYPE_TARGET_GAUGES.get(question_type, ())) | {"attention"}
    signals = evaluation.get("metacog_signals") or {}
    for criterion in CRITERIA:
        try:
            value = float(signals.get(criterion, 0.0))
        except (TypeError, ValueError):
            value = 0.0
        if abs(value) >= _INFORMED_SIGNAL:
            informed.add(criterion)
    curiosity = evaluation.get("curiosity_signals") or {}
    if isinstance(curiosity, dict) and any(bool(value) for value in curiosity.values()):
        informed.add("curiosity")
    creativity = evaluation.get("creativity_signals") or {}
    if isinstance(creativity, dict) and any(creativity.get(key) for key in CREATIVITY_FLAGS):
        informed.add("creativity")
    return informed & set(CRITERIA)


def _type_signal_scale(criterion: str, target_gauges: tuple[str, ...]) -> float:
    """Facteur appliqué au signal selon le type de question.

    Sans type ciblé, facteur neutre (1.0). Sinon, amplifie la dimension visée et
    atténue les autres pour différencier l'effet d'une curiosité vs un contexte."""
    if not target_gauges:
        return 1.0
    return _TYPE_TARGET_SCALE if criterion in target_gauges else _TYPE_OTHER_SCALE


def reading_attention_delta(
    elapsed_s: float,
    stagnant_s: float,
    pages_progressed: int,
    away: bool,
) -> float:
    """Dérive d'attention imputable au COMPORTEMENT de lecture, sur `elapsed_s`.

    C'est le seul endroit du produit où `attention` bouge sans passer par le LLM.
    Trois observations, et rien d'autre :

      * fenêtre masquée ou application au second plan -> l'étudiant n'est pas là ;
      * plus de `ATTENTION_IDLE_GRACE_S` d'immobilité réelle — même page ET aucun
        geste (défilement, souris, clavier ; cf. `SessionMemory.stagnant_since`)
        -> décrochage probable. Rester longtemps sur une page en la parcourant
        (deuxième colonne, retour sur un schéma) n'est PAS de la stagnation ;
      * pages nouvellement lues -> la lecture avance, petit crédit.

    Renvoie un delta signé, à borner par l'appelant (cf. `LiveGauges`)."""
    minutes = max(0.0, float(elapsed_s)) / 60.0
    delta = 0.0
    if away:
        delta -= ATTENTION_AWAY_PER_MIN * minutes
    elif float(stagnant_s) > ATTENTION_IDLE_GRACE_S:
        delta -= ATTENTION_DRIFT_PER_MIN * minutes
    delta += ATTENTION_PROGRESS_BONUS * max(0, int(pages_progressed))
    return delta


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
            positives = sum(1 for key in CREATIVITY_FLAGS if creativity_signals.get(key))
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


def attention_penalty(response_time_ms: int | None, consecutive_incorrect: int = 0) -> float:
    """Ce que coûtent à l'attention une réponse lente et une série d'erreurs.

    Une seule définition pour les deux modèles (lecteur et verdict)."""
    return _slow_answer_penalty(response_time_ms) + _error_streak_penalty(consecutive_incorrect)


def _slow_answer_penalty(response_time_ms: int | None) -> float:
    if response_time_ms is not None and response_time_ms > 12000:
        return min(6.0, (response_time_ms - 12000) / 2000.0)
    return 0.0


def _error_streak_penalty(consecutive_incorrect: int) -> float:
    return max(0, consecutive_incorrect - 1) * 1.0


def _update_attention(
    value: float,
    signal: float,
    verdict: str | None,
    response_time_ms: int | None,
    consecutive_incorrect: int,
) -> float:
    delta = max(-2.0, min(2.0, float(signal))) * 5.0
    delta -= _slow_answer_penalty(response_time_ms)
    if verdict == "correct":
        delta += 1.0
    elif verdict == "incorrect":
        delta -= 2.0
    delta -= _error_streak_penalty(consecutive_incorrect)
    return _clamp(value + delta)


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))
