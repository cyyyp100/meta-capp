from __future__ import annotations

import re

QUESTION_BANK = [
    "Quel moment de la session t'a semblé le plus clair, et pourquoi ?",
    "Qu'est-ce qui t'a demandé le plus d'effort mental aujourd'hui ?",
    "Quelle stratégie t'a aidé à avancer quand tu étais bloqué ?",
    "Quel point reste fragile dans ta compréhension maintenant ?",
    "À quel moment as-tu senti que ta compréhension progressait ?",
    "Qu'aurais-tu pu faire différemment pour mieux comprendre ?",
    "Comment évalues-tu ton niveau de compréhension à la fin de cette session ?",
    "Quelle partie t'a ralenti, et comment l'as-tu repérée ?",
    "Si tu devais réexpliquer l'idée principale, où hésiterais-tu encore ?",
]

_DEFAULT_QUESTIONS = [
    "Quel est ton ressenti global sur cette session ?",
    "Quels points t'ont le plus bloqué ou ralenti ?",
    "Comment auto-évalues-tu ta compréhension maintenant ?",
]

_QUESTION_WORDS = (
    "pourquoi",
    "comment",
    "peux-tu",
    "tu peux",
    "explique",
    "détaille",
    "detaille",
    "exemple",
    "différence",
    "difference",
    "concrètement",
    "concretement",
    "approfondir",
)

_STRATEGY_WORDS = (
    "relire",
    "reformuler",
    "schéma",
    "schema",
    "exemple",
    "analogie",
    "méthode",
    "methode",
    "stratégie",
    "strategie",
    "décomposer",
    "decomposer",
    "comparer",
)

_DIFFICULTY_WORDS = (
    "bloqué",
    "bloque",
    "difficile",
    "fragile",
    "ralenti",
    "confus",
    "pas compris",
    "j'hésite",
    "j hesite",
    "incertain",
)

_SELF_EVAL_WORDS = (
    "je comprends",
    "j'ai compris",
    "je n'ai pas compris",
    "je maîtrise",
    "je maitrise",
    "niveau",
    "auto",
    "clair",
    "flou",
)


def normalize_meta_cognition_questions(
    questions: list[str] | None,
    previous_questions: list[str] | None = None,
    seed_context: str | int | None = None,
) -> list[str]:
    previous = {_normalize_question(question) for question in previous_questions or []}
    selected: list[str] = []
    seen: set[str] = set()

    for question in questions or []:
        clean = _clean_question(question)
        key = _normalize_question(clean)
        if not clean or key in seen:
            continue
        selected.append(clean)
        seen.add(key)
        if len(selected) == 3:
            return selected

    offset = _offset(seed_context)
    rotated_bank = QUESTION_BANK[offset:] + QUESTION_BANK[:offset]
    for question in rotated_bank + _DEFAULT_QUESTIONS:
        clean = _clean_question(question)
        key = _normalize_question(clean)
        if key in seen:
            continue
        if key in previous and len(selected) + len(previous) < len(QUESTION_BANK):
            continue
        selected.append(clean)
        seen.add(key)
        if len(selected) == 3:
            return selected

    return selected[:3] or _DEFAULT_QUESTIONS


def fallback_meta_cognition_analysis(
    questions: list[str],
    answers: list[str],
    session_context: dict | None = None,
    user_profile: dict | None = None,
) -> dict:
    combined = "\n".join(str(answer or "").strip() for answer in answers)
    words = re.findall(r"\w+", combined.lower(), flags=re.UNICODE)
    non_empty_answers = [answer for answer in answers if str(answer or "").strip()]

    specificity = _ratio_score(min(1.0, len(words) / 55.0))
    awareness = _keyword_score(combined, _DIFFICULTY_WORDS)
    strategy = _keyword_score(combined, _STRATEGY_WORDS)
    self_eval = _keyword_score(combined, _SELF_EVAL_WORDS)
    honesty = max(awareness, min(1.0, specificity * 0.65 + self_eval * 0.35))

    answered_ratio = len(non_empty_answers) / max(1, len(questions) or 3)
    quality = (
        awareness * 0.22
        + strategy * 0.22
        + self_eval * 0.2
        + specificity * 0.2
        + honesty * 0.16
    ) * answered_ratio
    if not non_empty_answers:
        score_delta = -10.0
    else:
        score_delta = round((quality - 0.5) * 18.0, 2)

    return {
        "score_delta": max(-12.0, min(12.0, score_delta)),
        "score": max(0.0, min(100.0, 50.0 + score_delta)),
        "reasoning": "Analyse locale de secours fondée sur la précision, les difficultés citées, les stratégies et l'auto-évaluation.",
        "detected_signals": {
            "awareness_of_difficulties": awareness,
            "strategy_identification": strategy,
            "self_evaluation": self_eval,
            "specificity": specificity,
            "honesty_or_depth": honesty,
        },
    }


def detect_curiosity_signals(text: str) -> dict[str, bool]:
    raw = (text or "").strip()
    lower = raw.lower()
    has_question = "?" in raw or any(word in lower for word in _QUESTION_WORDS)
    asked_for_example = any(word in lower for word in ("exemple", "cas concret", "autre cas"))
    asked_for_clarification = any(
        word in lower
        for word in ("pas compris", "je n'ai pas compris", "clarifier", "détailler", "detaille", "explique")
    )
    explored = any(
        word in lower
        for word in ("et si", "différence", "difference", "pourquoi", "comment ça marche", "comment ca marche")
    )
    return {
        "asked_follow_up_question": bool(has_question),
        "asked_for_clarification": bool(asked_for_clarification),
        "asked_for_example": bool(asked_for_example),
        "explored_beyond_required_answer": bool(explored),
    }


def detect_creativity_signals(text: str) -> dict:
    lower = (text or "").lower()
    words = re.findall(r"\w+", lower, flags=re.UNICODE)
    makes_connections = any(token in lower for token in ("comme", "lien", "rapport", "contrairement", "par rapport"))
    uses_analogy = any(token in lower for token in ("analogie", "on dirait", "c'est comme", "comme si"))
    reformulation = any(token in lower for token in ("autrement dit", "avec mes mots", "je reformule", "en gros"))
    hypothesis = any(token in lower for token in ("peut-être", "peut etre", "j'imagine", "je suppose", "hypothèse", "hypothese"))
    depth = min(1.0, len(words) / 65.0)
    goes_beyond = len(words) >= 35 or any(token in lower for token in ("aussi", "donc", "cela implique", "conséquence", "consequence"))
    return {
        "goes_beyond_prompt": bool(goes_beyond),
        "makes_connections": bool(makes_connections),
        "uses_analogy": bool(uses_analogy),
        "personal_reformulation": bool(reformulation),
        "original_hypothesis": bool(hypothesis),
        "depth_of_reflection": depth,
    }


def augment_evaluation_with_response_signals(evaluation: dict, answer_text: str) -> dict:
    evaluation = dict(evaluation or {})
    signals = dict(evaluation.get("metacog_signals") or {})

    curiosity = _merge_bool_dict(
        evaluation.get("curiosity_signals") or {},
        detect_curiosity_signals(answer_text),
    )
    creativity = _merge_creativity_dict(
        evaluation.get("creativity_signals") or {},
        detect_creativity_signals(answer_text),
    )

    curiosity_bonus = 0.0
    if curiosity.get("asked_follow_up_question"):
        curiosity_bonus += 0.35
    if curiosity.get("asked_for_clarification"):
        curiosity_bonus += 0.35
    if curiosity.get("asked_for_example"):
        curiosity_bonus += 0.25
    if curiosity.get("explored_beyond_required_answer"):
        curiosity_bonus += 0.25

    creativity_bonus = 0.0
    for key in ("goes_beyond_prompt", "makes_connections", "uses_analogy", "personal_reformulation", "original_hypothesis"):
        if creativity.get(key):
            creativity_bonus += 0.16
    creativity_bonus += max(0.0, min(1.0, float(creativity.get("depth_of_reflection") or 0.0))) * 0.25

    signals["curiosity"] = max(-2.0, min(2.0, float(signals.get("curiosity", 0.0)) + curiosity_bonus))
    signals["creativity"] = max(-2.0, min(2.0, float(signals.get("creativity", 0.0)) + creativity_bonus))
    evaluation["metacog_signals"] = signals
    evaluation["curiosity_signals"] = curiosity
    evaluation["creativity_signals"] = creativity
    return evaluation


def _merge_bool_dict(primary: dict, secondary: dict) -> dict[str, bool]:
    keys = set(primary) | set(secondary)
    return {key: bool(primary.get(key) or secondary.get(key)) for key in keys}


def _merge_creativity_dict(primary: dict, secondary: dict) -> dict:
    merged = _merge_bool_dict(primary, secondary)
    try:
        merged["depth_of_reflection"] = max(
            float(primary.get("depth_of_reflection", 0.0) or 0.0),
            float(secondary.get("depth_of_reflection", 0.0) or 0.0),
        )
    except (TypeError, ValueError):
        merged["depth_of_reflection"] = float(secondary.get("depth_of_reflection", 0.0) or 0.0)
    return merged


def _clean_question(question: str) -> str:
    clean = " ".join(str(question or "").strip().split())
    if not clean:
        return ""
    return clean if clean.endswith("?") else f"{clean} ?"


def _normalize_question(question: str) -> str:
    return re.sub(r"\W+", "", (question or "").lower(), flags=re.UNICODE)


def _offset(seed_context: str | int | None) -> int:
    if seed_context is None:
        return 0
    return sum(ord(char) for char in str(seed_context)) % max(1, len(QUESTION_BANK))


def _ratio_score(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 2)


def _keyword_score(text: str, keywords: tuple[str, ...]) -> float:
    lower = (text or "").lower()
    hits = sum(1 for keyword in keywords if keyword in lower)
    return _ratio_score(hits / 2.0)
