# llm/schema_json.py — Validation stricte des JSON LLM
from __future__ import annotations

import ast
import json
import logging
import re
import string
import unicodedata
from typing import Any

from config.settings import DOCUMENT_SUMMARY_MAX_CHARS
from core.math_text import repair_common_inline_math_artifacts
from i18n import t
from metacog.reflection import normalize_meta_cognition_questions
from utils.tags import normalize_document_keywords, normalize_flashcard_tags

logger = logging.getLogger("LLM.schema")

CRITERIA = (
    "attention",
    "context_comprehension",
    "creativity",
    "retention",
    "curiosity",
    "meta_cognition",
)

QUESTION_TYPES = (
    "qcm",
    "open",
    "comprehension",
    "application",
    "curiosity",
    "visualization",
    "metacognition",
    "anticipation",
)

_QUESTION_TYPE_ALIASES = {
    "mcq": "qcm",
    "multiple_choice": "qcm",
    "qcm_verification_rapide_de_comprehension": "qcm",
    "question_ouverte": "open",
    "ouverte": "open",
    "open_question": "open",
    "reformulation": "open",
    "question_de_comprehension": "comprehension",
    "question_de_comprehension_textuelle": "comprehension",
    "comprehension_textuelle": "comprehension",
    "textual_comprehension": "comprehension",
    "question_d_application": "application",
    "question_application": "application",
    "application_question": "application",
    "mise_en_pratique": "application",
    "question_de_curiosite": "curiosity",
    "question_de_curiosite_inductive": "curiosity",
    "curiosite": "curiosity",
    "curiosite_inductive": "curiosity",
    "inductive": "curiosity",
    "question_inductive": "curiosity",
    "visualisation": "visualization",
    "exercice_de_visualisation": "visualization",
    "visualization_exercise": "visualization",
    "question_metacognitive": "metacognition",
    "metacognitive": "metacognition",
    "metacognitive_question": "metacognition",
    "anticipation_auto_evaluation": "anticipation",
    "auto_evaluation": "anticipation",
    "self_evaluation": "anticipation",
    "question_d_anticipation": "anticipation",
}

_AMBIGUOUS_JSON_LATEX_ESCAPE_RE = re.compile(
    r"\\(?:"
    r"bar|begin|beta|big|binom|bmatrix|boldsymbol|"
    r"forall|frac|"
    r"nabla|neg|ne|neq|ngeq|nleq|not|notin|nsim|nu|"
    r"rangle|rightarrow|right|"
    r"tan|tau|text|theta|therefore|times|to|top"
    r")\b"
)

# Fragments caractéristiques des questions génériques émises par le LLM
# quand il n'a pas de contexte suffisant pour générer une question ancrée.
_GENERIC_QUESTION_FRAGMENTS: tuple[str, ...] = (
    "la relation ou les données du passage",
    "les données du passage à un cas",
    "du passage à un cas simple",
    "appliquerais-tu la relation",
)


def _is_generic_question(text: str) -> bool:
    t = text.lower()
    return any(frag in t for frag in _GENERIC_QUESTION_FRAGMENTS)


def parse_question(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if isinstance(data, list):
        data = next((item for item in data if isinstance(item, dict)), None)
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("question"), dict):
        data = data["question"]
    elif isinstance(data.get("questions"), list):
        first_question = next((item for item in data["questions"] if isinstance(item, dict)), None)
        if first_question is not None:
            data = first_question

    question_type = _normalize_question_type(data.get("question_type"))
    question = _coerce_text(data.get("question", data.get("prompt")))
    choices = _coerce_str_list(
        data.get("choices", data.get("options", data.get("propositions")))
    )
    expected_answer = _coerce_text(
        data.get("expected_answer", data.get("expectedAnswer", data.get("answer")))
    )
    session_hint = _coerce_text(
        data.get(
            "session_hint",
            data.get("adaptive_hint", data.get("pause_suggestion", "")),
        )
    )
    source_block_id = _coerce_text(
        data.get("source_block_id", data.get("source_id", data.get("block_id", "")))
    )
    paragraph_mask = _parse_paragraph_mask(data.get("paragraph_mask"))

    evaluation_criteria = _coerce_str_list(
        data.get("evaluation_criteria", data.get("criteria", data.get("criteres", [])))
    )

    choices = [choice.strip() for choice in choices if choice.strip()]

    if question_type not in QUESTION_TYPES:
        question_type = "qcm" if len(choices) >= 3 else "open"
    if not _non_empty_str(question) or not _non_empty_str(expected_answer):
        return None
    if not evaluation_criteria:
        evaluation_criteria = [t("qa.criteria_faithful")]
    # gemma4 envoie des choices même pour les questions non-QCM → on normalise
    if question_type != "qcm":
        choices = []
    if question_type == "qcm":
        if len(choices) < 3:
            return None
        choices = choices[:4]  # tronquer si > 4
    if paragraph_mask is None:
        return None

    question_clean = repair_common_inline_math_artifacts(question.strip())
    if _is_generic_question(question_clean):
        logger.debug("Question générique rejetée : %.120s", question_clean)
        return None

    return {
        "question_type": question_type,
        "question": question_clean,
        "choices": [repair_common_inline_math_artifacts(choice.strip()) for choice in choices],
        "expected_answer": repair_common_inline_math_artifacts(expected_answer.strip()),
        "evaluation_criteria": [
            repair_common_inline_math_artifacts(item.strip())
            for item in evaluation_criteria
            if item.strip()
        ],
        "session_hint": session_hint.strip() if isinstance(session_hint, str) else "",
        "source_block_id": source_block_id.strip() if isinstance(source_block_id, str) else "",
        "paragraph_mask": paragraph_mask,
    }


def _normalize_question_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = _normalize_question_type_token(value)
    if token in QUESTION_TYPES:
        return token
    return _QUESTION_TYPE_ALIASES.get(token)


def _normalize_question_type_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", "_", without_accents.lower()).strip("_")


def parse_evaluation(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    for key in ("evaluation", "answer_evaluation", "answerEvaluation", "result"):
        if isinstance(data.get(key), dict):
            data = data[key]
            break

    verdict = _normalize_verdict(
        data.get("verdict", data.get("grade", data.get("status", data.get("result"))))
    )
    if verdict is None:
        verdict = _verdict_from_score(data.get("score", data.get("completion_score")))
    if verdict is None and isinstance(data.get("is_correct"), bool):
        verdict = "correct" if data["is_correct"] else "incorrect"
    if verdict is None:
        return None
    feedback = _coerce_text(
        data.get("feedback", data.get("comment", data.get("explanation", "")))
    )
    completion_raw = data.get("completion", "")
    hint_raw = data.get("hint", "")
    completion_value = _coerce_text(completion_raw)
    hint_value = _coerce_text(hint_raw)
    if feedback is None or completion_value is None or hint_value is None:
        return None
    if not feedback.strip():
        feedback = {
            "correct": "Réponse acceptée.",
            "partial": "Réponse partielle : il manque une précision.",
            "incorrect": "Réponse insuffisante pour valider ce point.",
        }[verdict]

    signals = data.get("metacog_signals")
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    if not isinstance(signals, dict) and analysis:
        signals = {
            "attention": analysis.get("attentionDelta", analysis.get("attention_delta", 0.0)),
            "curiosity": analysis.get("curiosityDelta", analysis.get("curiosity_delta", 0.0)),
            "creativity": analysis.get("creativityDelta", analysis.get("creativity_delta", 0.0)),
            "context_comprehension": 0.0,
            "retention": 0.0,
            "meta_cognition": 0.0,
        }
    if not isinstance(signals, dict):
        signals = {}
    normalized_signals = {}
    for criterion in CRITERIA:
        value = _number_value(signals.get(criterion, 0.0))
        normalized_signals[criterion] = _clamp(float(value if value is not None else 0.0), -2.0, 2.0)

    flashcard = data.get("flashcard")
    if flashcard in (None, False, "", {}):
        flashcard = None
    else:
        flashcard = parse_flashcard(flashcard)

    curiosity_signals = _parse_curiosity_signals(
        data.get("curiosity_signals")
        or data.get("curiositySignals")
        or analysis.get("curiositySignals")
        or analysis.get("curiosity_signals")
        or {}
    )
    creativity_signals = _parse_creativity_signals(
        data.get("creativity_signals")
        or data.get("creativitySignals")
        or analysis.get("creativitySignals")
        or analysis.get("creativity_signals")
        or {}
    )
    answer_to_user_question = data.get("answer_to_user_question", data.get("answerToUserQuestion"))
    answer_to_user_question = _coerce_text(answer_to_user_question)
    completion = completion_value.strip() if verdict == "partial" else ""
    hint = hint_value.strip() if verdict == "incorrect" else ""

    return {
        "verdict": verdict,
        "feedback": feedback.strip(),
        "completion": completion,
        "hint": hint,
        "metacog_signals": normalized_signals,
        "curiosity_signals": curiosity_signals,
        "creativity_signals": creativity_signals,
        "answer_to_user_question": answer_to_user_question.strip() if isinstance(answer_to_user_question, str) and answer_to_user_question.strip() else None,
        "flashcard": flashcard,
        "highlights": parse_highlights(data),
    }


def parse_follow_up(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None

    answer = _coerce_text(data.get("answer", data.get("response", data.get("réponse"))))
    if not _non_empty_str(answer):
        return None

    signals = data.get("metacog_signals")
    if not isinstance(signals, dict):
        signals = {}
    normalized_signals = {}
    for criterion in CRITERIA:
        value = _number_value(signals.get(criterion, 0.0))
        normalized_signals[criterion] = _clamp(float(value if value is not None else 0.0), -2.0, 2.0)
    normalized_signals["curiosity"] = max(1.0, normalized_signals["curiosity"])
    normalized_signals["meta_cognition"] = 0.0

    curiosity_signals = _parse_curiosity_signals(
        data.get("curiosity_signals")
        or data.get("curiositySignals")
        or {}
    )
    curiosity_signals["asked_follow_up_question"] = True

    return {
        "answer": answer.strip(),
        "metacog_signals": normalized_signals,
        "curiosity_signals": curiosity_signals,
        "highlights": parse_highlights(data),
    }


def parse_intervention(raw: str | dict) -> dict | None:
    """Décision d'intervention autonome de l'assistant bulle."""
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None

    should = data.get("should_intervene", data.get("shouldIntervene"))
    if isinstance(should, str):
        should = should.strip().lower() in {"true", "1", "yes", "oui"}
    should = bool(should)

    kind = str(data.get("kind") or "").strip().lower()
    if kind not in {"offer_help", "ask_question", "suggest_pause", "rephrase_offer", "review_flashcard"}:
        kind = "offer_help"

    message = _coerce_text(data.get("message")) or ""
    question = _coerce_text(data.get("question")) or ""

    if should and not message.strip() and not question.strip():
        # Une intervention sans contenu n'a pas de sens : ne pas déranger.
        should = False

    return {
        "should_intervene": should,
        "kind": kind,
        "message": message.strip(),
        "question": question.strip(),
        "highlights": parse_highlights(data),
    }


def parse_rephrasing(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    rephrased = data.get("rephrased_paragraph") or data.get("reformulation") or data.get("text") or ""
    if not _non_empty_str(rephrased):
        return None
    return {
        "rephrasing_angle": (data.get("rephrasing_angle") or data.get("angle") or "").strip(),
        "rephrased_paragraph": rephrased.strip(),
        "note": (data.get("note") or "").strip(),
        "highlights": parse_highlights(data),
    }


def parse_session_summary(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    summary = data.get("session_summary")
    if not isinstance(summary, dict):
        summary = data

    int_fields = ("duration_s", "paragraphs_read", "flashcards_created", "rephrasings_count")
    parsed_ints: dict[str, int] = {}
    for field in int_fields:
        value = _int_value(summary.get(field, 0))
        if value is None or value < 0:
            return None
        parsed_ints[field] = value

    success_rate = _number_value(summary.get("success_rate", summary.get("successRate", 0.0)))
    if success_rate is None:
        return None
    if success_rate > 1.0:
        success_rate = success_rate / 100.0
    qualitative_summary = _coerce_text(
        summary.get("qualitative_summary", summary.get("summary", summary.get("overview")))
    )
    if not _non_empty_str(qualitative_summary):
        return None
    questions = _coerce_str_list(
        summary.get("metacognitive_questions", summary.get("questions", []))
    )
    questions = normalize_meta_cognition_questions(questions)
    if len(questions) != 3:
        return None

    return {
        "session_summary": {
            "duration_s": parsed_ints["duration_s"],
            "paragraphs_read": parsed_ints["paragraphs_read"],
            "flashcards_created": parsed_ints["flashcards_created"],
            "rephrasings_count": parsed_ints["rephrasings_count"],
            "success_rate": _clamp(float(success_rate), 0.0, 1.0),
            "qualitative_summary": qualitative_summary.strip(),
            "metacognitive_questions": questions,
        }
    }


def parse_meta_cognition_questions(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if isinstance(data, list):
        questions = _coerce_str_list(data)
        normalized = normalize_meta_cognition_questions(questions)
        return {"questions": normalized} if len(normalized) == 3 else None
    if not isinstance(data, dict):
        return None
    questions = _coerce_str_list(
        data.get("questions", data.get("metacognitive_questions", data.get("metacognition_questions", [])))
    )
    normalized = normalize_meta_cognition_questions(questions)
    if len(normalized) != 3:
        return None
    return {"questions": normalized}


def parse_meta_cognition_analysis(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("analysis"), dict):
        data = data["analysis"]

    raw_delta = data.get("score_delta", data.get("scoreDelta"))
    delta = _number_value(raw_delta)
    if delta is None:
        delta = 0.0
    raw_score = data.get("score", 50.0)
    score = _number_value(raw_score)
    if score is None:
        score = 50.0
    reasoning = _coerce_text(data.get("reasoning", data.get("rationale", "")))
    if reasoning is None:
        reasoning = ""

    signals = data.get("detected_signals", data.get("detectedSignals"))
    if not isinstance(signals, dict):
        signals = {}
    parsed_signals = {
        "awareness_of_difficulties": _clamp(float(_number_value(_signal_value(signals, "awareness_of_difficulties", "awarenessOfDifficulties")) or 0.0), 0.0, 1.0),
        "strategy_identification": _clamp(float(_number_value(_signal_value(signals, "strategy_identification", "strategyIdentification")) or 0.0), 0.0, 1.0),
        "self_evaluation": _clamp(float(_number_value(_signal_value(signals, "self_evaluation", "selfEvaluation")) or 0.0), 0.0, 1.0),
        "specificity": _clamp(float(_number_value(_signal_value(signals, "specificity")) or 0.0), 0.0, 1.0),
        "honesty_or_depth": _clamp(float(_number_value(_signal_value(signals, "honesty_or_depth", "honestyOrDepth")) or 0.0), 0.0, 1.0),
    }

    return {
        "score_delta": _clamp(float(delta), -20.0, 20.0),
        "score": _clamp(float(score), 0.0, 100.0),
        "reasoning": reasoning.strip(),
        "detected_signals": parsed_signals,
    }


def parse_profile_analysis(raw: str | dict) -> dict | None:
    """Analyse générale de l'apprenant : {"analysis": "texte"} (item profil)."""
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    analysis = _coerce_text(data.get("analysis", data.get("summary", data.get("text"))))
    if not _non_empty_str(analysis):
        return None
    return {"analysis": analysis.strip()}


def parse_chapter_summary(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    summary = data.get("chapter_summary")
    if not isinstance(summary, dict):
        summary = data

    title = _coerce_text(summary.get("title", ""))
    overview = _coerce_text(summary.get("overview", summary.get("summary", "")))
    recap = summary.get("recap_qa", summary.get("recap", summary.get("qa", [])))
    if not isinstance(title, str) or not _non_empty_str(overview):
        return None
    if not isinstance(recap, list):
        return None

    parsed_recap = []
    for item in recap[:3]:
        if not isinstance(item, dict):
            continue
        question = _coerce_text(item.get("question", item.get("q")))
        answer = _coerce_text(item.get("answer", item.get("a")))
        if not _non_empty_str(question) or not _non_empty_str(answer):
            continue
        parsed_recap.append({
            "question": question.strip(),
            "answer": answer.strip(),
        })
    while len(parsed_recap) < 3:
        idx = len(parsed_recap) + 1
        parsed_recap.append({
            "question": f"Quel point clé retenir ({idx}) ?",
            "answer": overview.strip(),
        })

    return {
        "chapter_summary": {
            "title": title.strip(),
            "overview": overview.strip(),
            "recap_qa": parsed_recap,
        }
    }


def parse_curiosity_hook(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    curiosity_hook = _coerce_text(
        data.get("curiosity_hook", data.get("hook", data.get("message")))
    )
    if not _non_empty_str(curiosity_hook):
        return None
    tone = _normalize_curiosity_tone(data.get("tone"))
    if tone not in {"calm", "intriguing", "concrete", "playful"}:
        tone = "concrete"
    link_with_chapter = _coerce_text(
        data.get("link_with_chapter", data.get("linkWithChapter", ""))
    )
    if link_with_chapter is None:
        link_with_chapter = ""
    accessibility = _number_value(
        data.get("estimated_accessibility", data.get("estimatedAccessibility", 0.6))
    )
    if accessibility is None:
        accessibility = 0.6
    if accessibility > 1.0:
        accessibility = accessibility / 100.0
    return {
        "curiosity_hook": curiosity_hook.strip(),
        "tone": tone,
        "link_with_chapter": link_with_chapter.strip(),
        "estimated_accessibility": _clamp(float(accessibility), 0.0, 1.0),
    }


def parse_quiz_session_analysis(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None

    analysis = data.get("analysis", "")
    if not isinstance(analysis, str):
        analysis = ""

    weak_subjects = data.get("weak_subjects", [])
    if not isinstance(weak_subjects, list):
        weak_subjects = []
    weak_subjects = [str(s).strip() for s in weak_subjects if s]

    courses_raw = data.get("courses_to_review", [])
    if not isinstance(courses_raw, list):
        courses_raw = []

    courses = []
    for item in courses_raw[:3]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("subject") or "").strip()
        subject = str(item.get("subject") or "").strip()
        reason = str(item.get("reason") or "").strip()
        document = str(item.get("document") or "").strip()
        chapter_title = str(item.get("chapter_title") or "").strip()
        if title or subject:
            courses.append({
                "title": title or subject,
                "subject": subject,
                "reason": reason,
                "document": document,
                "chapter_title": chapter_title,
            })

    return {
        "analysis": analysis.strip(),
        "weak_subjects": weak_subjects,
        "courses_to_review": courses,
    }


def parse_quiz_distractors(raw: str | dict) -> dict | None:
    """Parse la sortie batch des distracteurs de QCM.

    Renvoie ``{question_id: {"answer": str, "distractors": [3 str]}}``. Les items
    sans 3 distracteurs non vides sont ignorés (le service repliera sur la question).
    """
    data = _load_json(raw)
    if isinstance(data, dict):
        items = data.get("items", data.get("questions", data.get("results")))
        if items is None and "distractors" in data:
            items = [data]
    elif isinstance(data, list):
        items = data
    else:
        return None
    if not isinstance(items, list):
        return None

    parsed: dict[int, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        qid = _int_value(item.get("id"))
        if qid is None:
            continue
        answer = (_coerce_text(item.get("answer")) or "").strip()
        # Distracteurs uniques, non vides, distincts de la réponse.
        distractors: list[str] = []
        seen = {answer.lower()} if answer else set()
        for cand in _coerce_str_list(item.get("distractors", item.get("wrong_answers"))):
            cand = cand.strip()
            key = cand.lower()
            if cand and key not in seen:
                seen.add(key)
                distractors.append(cand)
        if len(distractors) < 3:
            continue
        parsed[qid] = {"answer": answer, "distractors": distractors[:3]}

    return parsed or None


def parse_latex_paragraph_render(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    rendered = _coerce_text(data.get("rendered", data.get("text", data.get("paragraph"))))
    if not _non_empty_str(rendered) or len(rendered.strip()) < 8:
        return None
    return {"rendered": rendered.strip()}


def parse_flashcard_tags(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if isinstance(data, list):
        tags = _coerce_str_list(data)
        normalized = normalize_flashcard_tags(tags)
        if not (2 <= len(normalized) <= 6):
            return None
        return {"tags": normalized[:6]}
    if not isinstance(data, dict):
        return None
    tags = _coerce_str_list(data.get("tags", data.get("labels", data.get("keywords", []))))
    normalized = normalize_flashcard_tags(tags)
    if not (2 <= len(normalized) <= 6):
        return None
    return {"tags": normalized[:6]}


def parse_flashcard(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    front = _coerce_text(data.get("front", data.get("recto")))
    back = _coerce_text(data.get("back", data.get("verso")))
    if not _non_empty_str(front) or not _non_empty_str(back):
        return None
    tags = _coerce_str_list(data.get("tags", []))
    difficulty = _int_value(data.get("difficulty", 2))
    if difficulty not in (1, 2, 3):
        return None
    return {
        "front": front.strip(),
        "back": back.strip(),
        "tags": normalize_flashcard_tags(tags),
        "difficulty": difficulty,
    }


HIGHLIGHT_PURPOSES = ("key", "explain", "reference")
_HIGHLIGHT_MIN_CHARS = 15  # citations plus courtes = trop ambiguës à localiser
_HIGHLIGHT_MAX_ITEMS = 3


def parse_highlights(data: dict) -> list[dict]:
    """Citations à surligner dans la page PDF (champ optionnel, défaut [])."""
    if not isinstance(data, dict):
        return []
    raw = data.get("highlights", data.get("highlighted_quotes", data.get("quotes")))
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    items: list[dict] = []
    for entry in raw:
        if isinstance(entry, str):
            entry = {"quote": entry}
        if not isinstance(entry, dict):
            continue
        quote = _coerce_text(entry.get("quote", entry.get("text", entry.get("citation"))))
        if not isinstance(quote, str) or len(quote.strip()) < _HIGHLIGHT_MIN_CHARS:
            continue
        purpose = str(entry.get("purpose") or "").strip().lower()
        if purpose not in HIGHLIGHT_PURPOSES:
            purpose = "explain"
        items.append({"quote": quote.strip(), "purpose": purpose})
        if len(items) >= _HIGHLIGHT_MAX_ITEMS:
            break
    return items


def _parse_curiosity_signals(raw: dict) -> dict[str, bool]:
    if not isinstance(raw, dict):
        raw = {}
    return {
        "asked_follow_up_question": _bool_value(raw, "asked_follow_up_question", "askedFollowUpQuestion"),
        "asked_for_clarification": _bool_value(raw, "asked_for_clarification", "askedForClarification"),
        "asked_for_example": _bool_value(raw, "asked_for_example", "askedForExample"),
        "explored_beyond_required_answer": _bool_value(raw, "explored_beyond_required_answer", "exploredBeyondRequiredAnswer"),
    }


def _parse_creativity_signals(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    depth = _signal_value(raw, "depth_of_reflection", "depthOfReflection")
    if not isinstance(depth, (int, float)):
        depth = 0.0
    return {
        "goes_beyond_prompt": _bool_value(raw, "goes_beyond_prompt", "goesBeyondPrompt"),
        "makes_connections": _bool_value(raw, "makes_connections", "makesConnections"),
        "uses_analogy": _bool_value(raw, "uses_analogy", "usesAnalogy"),
        "personal_reformulation": _bool_value(raw, "personal_reformulation", "personalReformulation"),
        "original_hypothesis": _bool_value(raw, "original_hypothesis", "originalHypothesis"),
        "depth_of_reflection": _clamp(float(depth), 0.0, 1.0),
    }


def _bool_value(raw: dict, *keys: str) -> bool:
    value = _signal_value(raw, *keys)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "oui"}
    return bool(value)


def _signal_value(raw: dict, *keys: str):
    for key in keys:
        if key in raw:
            return raw[key]
    return 0.0


def _parse_paragraph_mask(value) -> dict | None:
    if value is None:
        return {"enabled": False}
    if not isinstance(value, dict):
        return None

    enabled = value.get("enabled", False)
    if isinstance(enabled, int) and not isinstance(enabled, bool):
        enabled = bool(enabled)
    elif isinstance(enabled, str):
        enabled = enabled.lower() in ("true", "1", "yes")
    elif not isinstance(enabled, bool):
        enabled = False  # fallback safe
    if not enabled:
        return {"enabled": False}

    start_char = value.get("start_char")
    end_char = value.get("end_char")
    if not isinstance(start_char, int) or not isinstance(end_char, int):
        return None
    if start_char < 0 or end_char <= start_char:
        return None

    placeholder = value.get("placeholder", t("qa.mask_placeholder"))
    if not _non_empty_str(placeholder):
        return None

    return {
        "enabled": True,
        "start_char": start_char,
        "end_char": end_char,
        "placeholder": placeholder.strip(),
    }


def _load_json(raw: str | dict) -> Any:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None

    text = _strip_markdown_fence(raw.strip())
    for candidate in _json_candidates(text):
        for variant in _json_parse_variants(candidate):
            try:
                return json.loads(variant)
            except json.JSONDecodeError:
                pass
            parsed = _load_python_literal(variant)
            if parsed is not None:
                return parsed
    logger.debug("JSON LLM invalide: %s", raw[:200])
    return None


def _strip_markdown_fence(text: str) -> str:
    fenced = re.findall(r"```(?:json|JSON)?\s*(.*?)```", text, flags=re.DOTALL)
    if fenced:
        return "\n".join(block.strip() for block in fenced if block.strip()).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start:end + 1]


def _json_candidates(text: str) -> list[str]:
    candidates = [text]
    extracted = _extract_json_object(text)
    if extracted is not None and extracted != text:
        candidates.append(extracted)
    candidates.extend(_extract_balanced_json_values(text))
    return _dedupe_strings(candidates)


def _json_parse_variants(text: str) -> list[str]:
    repaired = _escape_invalid_json_backslashes(text)
    roots = [repaired, text] if repaired != text and _AMBIGUOUS_JSON_LATEX_ESCAPE_RE.search(text) else [text]
    if repaired != text and repaired not in roots:
        roots.append(repaired)

    variants: list[str] = []
    for root in roots:
        variants.append(root)
        no_trailing = _remove_trailing_json_commas(root)
        variants.append(no_trailing)
        normalized_literals = _normalize_json_literals_outside_strings(no_trailing)
        variants.append(normalized_literals)
        variants.append(_quote_unquoted_json_keys(normalized_literals))
        variants.append(_complete_truncated_json(no_trailing))
    return _dedupe_strings(variants)


def _load_python_literal(text: str) -> Any:
    variants = [
        text,
        _python_literals_outside_strings(text),
        _quote_unquoted_json_keys(_python_literals_outside_strings(text)),
    ]
    for variant in _dedupe_strings(variants):
        try:
            return ast.literal_eval(variant)
        except (SyntaxError, ValueError, TypeError):
            continue
    return None


def _extract_balanced_json_values(text: str) -> list[str]:
    values: list[str] = []
    for start, char in enumerate(text):
        if char not in "{[":
            continue
        stack: list[str] = []
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            current = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                stack.append("}")
            elif current == "[":
                stack.append("]")
            elif current in "}]":
                if not stack or stack[-1] != current:
                    break
                stack.pop()
                if not stack:
                    values.append(text[start:index + 1])
                    break
    return values


def _remove_trailing_json_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _quote_unquoted_json_keys(text: str) -> str:
    return re.sub(
        r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:',
        lambda match: f'{match.group(1)}"{match.group(2)}":',
        text,
    )


def _complete_truncated_json(text: str) -> str:
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in "}]":
            if stack and stack[-1] == char:
                stack.pop()

    suffix = ""
    if in_string:
        if escaped:
            suffix += "\\"
        suffix += '"'
    while stack:
        suffix += stack.pop()
    return text + suffix


def _normalize_json_literals_outside_strings(text: str) -> str:
    return _replace_literals_outside_strings(
        text,
        {"True": "true", "False": "false", "None": "null"},
    )


def _python_literals_outside_strings(text: str) -> str:
    return _replace_literals_outside_strings(
        text,
        {"true": "True", "false": "False", "null": "None"},
    )


def _replace_literals_outside_strings(text: str, replacements: dict[str, str]) -> str:
    result: list[str] = []
    in_string = False
    escaped = False
    index = 0
    keys = tuple(sorted(replacements, key=len, reverse=True))
    while index < len(text):
        char = text[index]
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        replaced = False
        for key in keys:
            if text.startswith(key, index) and _literal_boundary(text, index, len(key)):
                result.append(replacements[key])
                index += len(key)
                replaced = True
                break
        if not replaced:
            result.append(char)
            index += 1
    return "".join(result)


def _literal_boundary(text: str, start: int, length: int) -> bool:
    before = text[start - 1] if start > 0 else ""
    after = text[start + length] if start + length < len(text) else ""
    return not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_")


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result


def _escape_invalid_json_backslashes(text: str) -> str:
    r"""Repair common LLM JSON errors such as LaTeX ``\sim`` inside strings."""
    valid_escapes = {'"', "\\", "/", "b", "f", "n", "r", "t", "u"}
    hex_digits = set(string.hexdigits)
    repaired: list[str] = []
    in_string = False
    pending_backslash = False
    i = 0
    while i < len(text):
        char = text[i]

        if not in_string:
            repaired.append(char)
            if char == '"':
                in_string = True
            i += 1
            continue

        if pending_backslash:
            next_char = text[i + 1] if i + 1 < len(text) else ""
            is_valid_unicode_escape = char == "u" and len(text[i + 1 : i + 5]) == 4 and all(
                item in hex_digits for item in text[i + 1 : i + 5]
            )
            looks_like_latex_command = (
                char.isalpha()
                and not is_valid_unicode_escape
                and (char not in valid_escapes or next_char.isalpha())
            )
            if char in valid_escapes and not looks_like_latex_command and (char != "u" or is_valid_unicode_escape):
                repaired.append("\\")
                repaired.append(char)
            else:
                repaired.append("\\\\")
                repaired.append(char)
            pending_backslash = False
            i += 1
            continue

        if char == "\\":
            pending_backslash = True
            i += 1
            continue

        if char == '"':
            in_string = False
            repaired.append(char)
            i += 1
            continue

        if char == "\n":
            repaired.append("\\n")
        elif char == "\r":
            repaired.append("\\r")
        elif char == "\t":
            repaired.append("\\t")
        else:
            repaired.append(char)
        i += 1

    if pending_backslash:
        repaired.append("\\\\")
    return "".join(repaired)


def _normalize_verdict(value) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[\s_-]+", " ", value.strip().lower())
    aliases = {
        "correct": "correct",
        "correcte": "correct",
        "correct answer": "correct",
        "bonne réponse": "correct",
        "bonne reponse": "correct",
        "réponse correcte": "correct",
        "reponse correcte": "correct",
        "juste": "correct",
        "valid": "correct",
        "valide": "correct",
        "partial": "partial",
        "partiel": "partial",
        "partielle": "partial",
        "partiellement correct": "partial",
        "partiellement correcte": "partial",
        "partly correct": "partial",
        "incomplete": "partial",
        "incomplet": "partial",
        "incomplète": "partial",
        "incomplete answer": "partial",
        "à compléter": "partial",
        "a completer": "partial",
        "incorrect": "incorrect",
        "incorrecte": "incorrect",
        "réponse incorrecte": "incorrect",
        "reponse incorrecte": "incorrect",
        "faux": "incorrect",
        "fausse": "incorrect",
        "wrong": "incorrect",
        "hors sujet": "incorrect",
    }
    return aliases.get(normalized)


def _coerce_text(value) -> str | None:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return " ".join(item.strip() for item in value if item.strip())
    return None


def _coerce_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, (int, float, bool)):
                result.append(str(item))
            elif isinstance(item, dict):
                text = _coerce_text(
                    item.get("text", item.get("label", item.get("answer", item.get("value"))))
                )
                if text:
                    result.append(text)
        return result
    if isinstance(value, dict):
        return [
            str(item).strip()
            for _key, item in sorted(value.items())
            if isinstance(item, (str, int, float, bool)) and str(item).strip()
        ]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        parts = re.split(r"\n+|(?:^|\s)[-•]\s+|;\s*", stripped)
        return [part.strip(" -•") for part in parts if part.strip(" -•")]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    return []


def _verdict_from_score(value) -> str | None:
    score = _number_value(value)
    if score is None:
        return None
    if score > 1.0:
        score = score / 100.0
    if score >= 0.75:
        return "correct"
    if score >= 0.30:
        return "partial"
    return "incorrect"


def _number_value(value) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _int_value(value) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    number = _number_value(value)
    if number is None:
        return None
    return int(number)


def _non_empty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_fields(data: dict, fields: tuple[str, ...]) -> bool:
    return all(isinstance(data.get(field, ""), str) for field in fields)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


_KNOWN_SUBJECTS: frozenset[str] = frozenset({
    "mathématiques", "physique", "chimie", "biologie", "sciences",
    "informatique", "technologie", "histoire", "géographie", "français",
    "philosophie", "littérature", "langues", "économie", "sciences-sociales",
    "droit", "gestion", "psychologie", "sociologie", "arts",
    "musique", "médecine", "sport", "religion", "culture",
})

# Les clés sont normalisées (minuscule, sans accent, séparateur "_") par
# `_normalize_subject_token` avant lookup ; on utilise donc ici cette forme.
_SUBJECT_ALIASES: dict[str, str] = {
    "math": "mathématiques",
    "maths": "mathématiques",
    "mathematics": "mathématiques",
    "mathematiques": "mathématiques",
    "algebre": "mathématiques",
    "analyse": "mathématiques",
    "geometrie": "mathématiques",
    "statistiques": "mathématiques",
    "physique": "physique",
    "physics": "physique",
    "mecanique": "physique",
    "chimie": "chimie",
    "chemistry": "chimie",
    "biologie": "biologie",
    "biology": "biologie",
    "svt": "biologie",
    "science": "sciences",
    "sciences": "sciences",
    "informatique": "informatique",
    "informatics": "informatique",
    "computing": "informatique",
    "computer_science": "informatique",
    "programmation": "informatique",
    "technologie": "technologie",
    "technology": "technologie",
    "ingenierie": "technologie",
    "engineering": "technologie",
    "history": "histoire",
    "histoire": "histoire",
    "geography": "géographie",
    "geographie": "géographie",
    "french": "français",
    "francais": "français",
    "philosophie": "philosophie",
    "philosophy": "philosophie",
    "litterature": "littérature",
    "literature": "littérature",
    "langues": "langues",
    "langue": "langues",
    "languages": "langues",
    "language": "langues",
    "anglais": "langues",
    "english": "langues",
    "espagnol": "langues",
    "allemand": "langues",
    "economie": "économie",
    "economics": "économie",
    "eco": "économie",
    "ses": "économie",
    "sciences_sociales": "sciences-sociales",
    "social_sciences": "sciences-sociales",
    "sciences_humaines": "sciences-sociales",
    "droit": "droit",
    "law": "droit",
    "gestion": "gestion",
    "management": "gestion",
    "comptabilite": "gestion",
    "psychologie": "psychologie",
    "psychology": "psychologie",
    "sociologie": "sociologie",
    "sociology": "sociologie",
    "arts": "arts",
    "art": "arts",
    "art_plastique": "arts",
    "arts_plastiques": "arts",
    "musique": "musique",
    "music": "musique",
    "medecine": "médecine",
    "medicine": "médecine",
    "sante": "médecine",
    "health": "médecine",
    "sport": "sport",
    "sports": "sport",
    "eps": "sport",
    "religion": "religion",
    "theologie": "religion",
    "theology": "religion",
    "culture": "culture",
    "general": "culture",
    "général": "culture",
    "generale": "culture",
    "culture_generale": "culture",
}


def parse_subject_detection(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return {"subject": "culture"}
    subject = _normalize_subject_token(data.get("subject", data.get("matiere", data.get("matière", ""))))
    subject = _SUBJECT_ALIASES.get(subject, subject)
    if subject in _KNOWN_SUBJECTS:
        return {"subject": subject}
    return {"subject": "culture"}


def parse_document_digest(raw: str | dict) -> dict | None:
    """Fiche d'un document : {"subject", "summary", "keywords"}.

    Ne renvoie JAMAIS None : un import ne doit pas échouer parce que le modèle a
    bavardé. Chaque champ dégrade indépendamment — une matière valide avec un
    résumé vide reste utile pour le classement.
    """
    data = _load_json(raw)
    if not isinstance(data, dict):
        data = {}
    subject = (parse_subject_detection(data) or {}).get("subject") or "culture"
    summary_raw = _coerce_text(
        data.get("summary", data.get("resume", data.get("résumé", "")))
    ) or ""
    keywords_raw = _coerce_str_list(
        data.get(
            "keywords",
            data.get("mots_cles", data.get("mots-clés", data.get("tags", []))),
        )
    )
    return {
        "subject": subject,
        "summary": _clean_document_summary(summary_raw),
        "keywords": normalize_document_keywords(keywords_raw),
    }


# Ouverture creuse que le modèle produit malgré la consigne du prompt (essayée en
# formulation négative PUIS avec un exemple positif : gemma la remet quand même).
# Elle mange une douzaine de caractères sur les 220 affichables et n'apprend rien
# au lecteur, qui sait déjà qu'il regarde un document.
_SUMMARY_FILLER_OPENING = re.compile(
    r"^(?:ce document|ce cours|this document)\s+"
    r"(?:explique|présente|presente|traite\s+de|traite|aborde|décrit|decrit|couvre|"
    r"porte\s+sur|expose|explains|presents|covers|describes|discusses|introduces)\s+",
    flags=re.I,
)


def _clean_document_summary(text: str) -> str:
    """Une phrase propre : ni Markdown, ni préfixe « Résumé : », ni guillemet
    orphelin, tronquée sur un mot à DOCUMENT_SUMMARY_MAX_CHARS."""
    clean = " ".join(str(text or "").split())
    clean = re.sub(r"^[*_`#>\s]+|[*_`\s]+$", "", clean)
    clean = re.sub(r"^(résumé|resume|summary)\s*[:\-–]\s*", "", clean, flags=re.I)
    clean = clean.strip(' "“”')
    stripped = _SUMMARY_FILLER_OPENING.sub("", clean)
    # On ne garde le retrait que s'il laisse une phrase, pas un moignon.
    if len(stripped) >= 20:
        clean = stripped[0].upper() + stripped[1:]
    if len(clean) <= DOCUMENT_SUMMARY_MAX_CHARS:
        return clean
    cut = clean[:DOCUMENT_SUMMARY_MAX_CHARS]
    space = cut.rfind(" ")
    return (cut[:space] if space > 40 else cut).rstrip(" ,;:") + "…"


def _normalize_subject_token(value: Any) -> str:
    text = str(value or "").lower().strip()
    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", "_", without_accents).strip("_")


def parse_brainstorm_search_decision(raw: str | dict) -> dict | None:
    """Décision de recherche du brainstorming : {"search": bool, "queries": [str]}.

    Tolérant : en cas d'échec, on renvoie un repli « pas de recherche » plutôt que
    None, pour que la conversation continue sans bloquer.
    """
    data = _load_json(raw)
    if not isinstance(data, dict):
        return {"search": False, "queries": []}
    search = bool(data.get("search"))
    queries_raw = data.get("queries") or []
    if isinstance(queries_raw, str):
        queries_raw = [queries_raw]
    queries = []
    for q in queries_raw if isinstance(queries_raw, list) else []:
        text = str(q or "").strip()
        if text:
            queries.append(text[:120])
    queries = queries[:3]
    if not queries:
        search = False
    return {"search": search, "queries": queries}


# ── Parsers module langue ──────────────────────────────────────────────────────

def parse_lang_curriculum(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    lessons_raw = data.get("lessons")
    if not isinstance(lessons_raw, list) or len(lessons_raw) < 10:
        return None
    lessons = []
    for item in lessons_raw:
        if not isinstance(item, dict):
            continue
        n = item.get("lesson_n")
        theme = _coerce_text(item.get("theme", ""))
        if not isinstance(n, int) or not _non_empty_str(theme):
            continue
        lessons.append({
            "lesson_n": int(n),
            "theme": (theme or "").strip(),
            "grammar_point": (_coerce_text(item.get("grammar_point", "")) or "").strip(),
            "vocabulary": _coerce_str_list(item.get("vocabulary", [])),
            "level": str(item.get("level", "A1")),
            "reuses": [
                int(x) for x in (item.get("reuses") or [])
                if isinstance(x, (int, float))
            ],
        })
    if len(lessons) < 10:
        return None
    return {"lessons": lessons}


def parse_lang_curiosity(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    hook = _coerce_text(data.get("curiosity_hook", ""))
    if not _non_empty_str(hook):
        return None
    tone = _normalize_curiosity_tone(data.get("tone"))
    if tone not in {"calm", "intriguing", "concrete", "playful"}:
        tone = "concrete"
    return {
        "curiosity_hook": (hook or "").strip(),
        "cultural_note": (_coerce_text(data.get("cultural_note", "")) or "").strip(),
        "tone": tone,
    }


def parse_lang_lesson(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    dialogue_raw = data.get("dialogue")
    if not isinstance(dialogue_raw, list) or len(dialogue_raw) < 3:
        return None
    dialogue = []
    for line in dialogue_raw:
        if not isinstance(line, dict):
            continue
        target = _coerce_text(line.get("target", ""))
        if not _non_empty_str(target):
            continue
        dialogue.append({
            "speaker": str(line.get("speaker", "A")),
            "target": (target or "").strip(),
            "phonetic": (_coerce_text(line.get("phonetic", "")) or "").strip(),
            "translation": (_coerce_text(line.get("translation", "")) or "").strip(),
        })
    if len(dialogue) < 3:
        return None
    notes_raw = data.get("notes") or {}
    notes = {
        "grammar": (_coerce_text(notes_raw.get("grammar", "")) or "").strip(),
        "pronunciation": (_coerce_text(notes_raw.get("pronunciation", "")) or "").strip(),
        "cultural": (_coerce_text(notes_raw.get("cultural", "")) or "").strip(),
    }
    vocabulary = []
    for v in (data.get("vocabulary") or []):
        if not isinstance(v, dict):
            continue
        word = _coerce_text(v.get("word", ""))
        if _non_empty_str(word):
            vocabulary.append({
                "word": (word or "").strip(),
                "translation": (_coerce_text(v.get("translation", "")) or "").strip(),
                "example": (_coerce_text(v.get("example", "")) or "").strip(),
            })
    return {"dialogue": dialogue, "notes": notes, "vocabulary": vocabulary}


def parse_lang_exercises(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    exercises_raw = data.get("exercises")
    if not isinstance(exercises_raw, list) or not exercises_raw:
        return None
    exercises = []
    for ex in exercises_raw:
        if not isinstance(ex, dict):
            continue
        question = _coerce_text(ex.get("question", ""))
        choices = _coerce_str_list(ex.get("choices", []))
        correct = str(ex.get("correct", "A")).strip().upper()
        if not _non_empty_str(question) or len(choices) < 2:
            continue
        if correct not in {"A", "B", "C", "D"}:
            correct = "A"
        exercises.append({
            "type": "qcm",
            "question": (question or "").strip(),
            "choices": choices[:4],
            "correct": correct,
            "explanation": (_coerce_text(ex.get("explanation", "")) or "").strip(),
        })
    return {"exercises": exercises} if exercises else None


def parse_lang_correction(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    verdict = str(data.get("verdict", "incorrect")).lower().strip()
    if verdict not in {"correct", "partial", "incorrect"}:
        verdict = "incorrect"
    corrections = []
    for c in (data.get("corrections") or []):
        if not isinstance(c, dict):
            continue
        original = _coerce_text(c.get("original", ""))
        if _non_empty_str(original):
            corrections.append({
                "original": (original or "").strip(),
                "corrected": (_coerce_text(c.get("corrected", "")) or "").strip(),
                "error_type": (_coerce_text(c.get("error_type", "")) or "").strip(),
                "reason": (_coerce_text(c.get("reason", "")) or "").strip(),
            })
    score_raw = _number_value(data.get("score", 0.5))
    score = _clamp(float(score_raw or 0.5), 0.0, 1.0)
    return {
        "verdict": verdict,
        "corrections": corrections,
        "feedback": (_coerce_text(data.get("feedback", "")) or "").strip(),
        "score": score,
    }


def parse_lang_revision_quiz(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    exercises = []
    for ex in (data.get("exercises") or []):
        if not isinstance(ex, dict):
            continue
        prompt_fr = _coerce_text(ex.get("prompt_fr", ""))
        expected = _coerce_text(ex.get("expected", ""))
        if _non_empty_str(prompt_fr) and _non_empty_str(expected):
            item = {
                "type": "translation",
                "prompt_fr": (prompt_fr or "").strip(),
                "expected": (expected or "").strip(),
                "target_word": (_coerce_text(ex.get("target_word", "")) or "").strip(),
                "hint": (_coerce_text(ex.get("hint", "")) or "").strip(),
            }
            # card_id : présent uniquement quand l'item vient d'une carte SR (repli
            # déterministe) — permet le bouclage exact d'échéance sans LLM.
            card_id = _int_value(ex.get("card_id"))
            if card_id is not None:
                item["card_id"] = card_id
            exercises.append(item)
    return {"exercises": exercises} if exercises else None


# ── Séquenceur adaptatif : choix de type + contenu par render_kind ────────────

def parse_session_choice(raw: str | dict) -> dict | None:
    """JSON minuscule du sélecteur : {chosen_type, reason}."""
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    chosen = _coerce_text(data.get("chosen_type", ""))
    if not _non_empty_str(chosen):
        return None
    return {
        "chosen_type": (chosen or "").strip(),
        "reason": (_coerce_text(data.get("reason", "")) or "").strip(),
    }


def _parse_qcm_list(items) -> list[dict]:
    out = []
    for ex in (items or []):
        if not isinstance(ex, dict):
            continue
        question = _coerce_text(ex.get("question", ""))
        choices = _coerce_str_list(ex.get("choices", []))
        if not _non_empty_str(question) or len(choices) < 2:
            continue
        correct = str(ex.get("correct", "A")).strip().upper()
        if correct not in {"A", "B", "C", "D"}:
            correct = "A"
        depth = str(ex.get("depth", "")).strip().lower()
        out.append({
            "question": (question or "").strip(),
            "choices": choices[:4],
            "correct": correct,
            "explanation": (_coerce_text(ex.get("explanation", "")) or "").strip(),
            "depth": "inference" if depth == "inference" else "literal",
        })
    return out


def parse_session_dialogue(raw: str | dict) -> dict | None:
    """render_kind=dialogue : réutilise la forme de parse_lang_lesson + thème."""
    base = parse_lang_lesson(raw)
    if not base:
        return None
    data = _load_json(raw)
    theme = _coerce_text(data.get("theme", "")) if isinstance(data, dict) else ""
    return {"kind": "dialogue", "theme": (theme or "").strip(), **base}


def parse_session_reading(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    text_target = _coerce_text(data.get("text_target", ""))
    if not _non_empty_str(text_target):
        return None
    glossary = []
    for g in (data.get("glossary") or []):
        if not isinstance(g, dict):
            continue
        word = _coerce_text(g.get("word", ""))
        if _non_empty_str(word):
            glossary.append({
                "word": (word or "").strip(),
                "translation": (_coerce_text(g.get("translation", "")) or "").strip(),
            })
    return {
        "kind": "reading",
        "title": (_coerce_text(data.get("title", "")) or "").strip(),
        "text_target": (text_target or "").strip(),
        "text_translation": (_coerce_text(data.get("text_translation", "")) or "").strip(),
        "glossary": glossary,
        "questions": _parse_qcm_list(data.get("questions")),
    }


def parse_session_vocabulary(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    items = []
    for it in (data.get("items") or []):
        if not isinstance(it, dict):
            continue
        word = _coerce_text(it.get("word", ""))
        if not _non_empty_str(word):
            continue
        items.append({
            "word": (word or "").strip(),
            "translation": (_coerce_text(it.get("translation", "")) or "").strip(),
            # Translittération/ton optionnels (scripts non-latins / langues tonales).
            "phonetic": (_coerce_text(it.get("phonetic", "")) or "").strip(),
            "tone": (_coerce_text(it.get("tone", "")) or "").strip(),
            "example_target": (_coerce_text(it.get("example_target", "")) or "").strip(),
            "example_translation": (_coerce_text(it.get("example_translation", "")) or "").strip(),
        })
    if not items:
        return None
    return {"kind": "vocabulary", "items": items, "questions": _parse_qcm_list(data.get("questions"))}


def parse_session_phonetics(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    focus = _coerce_text(data.get("focus_sound", ""))
    if not _non_empty_str(focus):
        return None
    pairs = []
    for p in (data.get("minimal_pairs") or []):
        if not isinstance(p, dict):
            continue
        a = _coerce_text(p.get("a", ""))
        b = _coerce_text(p.get("b", ""))
        if _non_empty_str(a) and _non_empty_str(b):
            pairs.append({
                "a": (a or "").strip(),
                "b": (b or "").strip(),
                "note": (_coerce_text(p.get("note", "")) or "").strip(),
            })
    drills = []
    for d in (data.get("drills") or []):
        if not isinstance(d, dict):
            continue
        kind = str(d.get("kind", "")).strip().lower()
        translation = (_coerce_text(d.get("translation", "")) or "").strip()
        if kind == "stress":
            # Placer l'accent tonique : correction côté client (index attendu connu).
            word = _coerce_text(d.get("word", ""))
            syllables = _coerce_str_list(d.get("syllables", []))
            idx = _int_value(d.get("stressed_index"))
            if _non_empty_str(word) and len(syllables) >= 2 and idx is not None and 0 <= idx < len(syllables):
                drills.append({
                    "kind": "stress", "word": (word or "").strip(),
                    "syllables": syllables, "stressed_index": idx, "translation": translation,
                })
        elif kind == "spell_to_sound":
            # Associer graphie ↔ transcription : QCM corrigé côté client.
            written = _coerce_text(d.get("written", ""))
            options = _coerce_str_list(d.get("options", []))
            ans = _int_value(d.get("answer"))
            if _non_empty_str(written) and len(options) >= 2 and ans is not None and 0 <= ans < len(options):
                drills.append({
                    "kind": "spell_to_sound", "written": (written or "").strip(),
                    "options": options[:4], "answer": ans, "translation": translation,
                })
        else:
            target = _coerce_text(d.get("target", ""))
            if _non_empty_str(target):
                drills.append({
                    "kind": "read",
                    "target": (target or "").strip(),
                    "phonetic": (_coerce_text(d.get("phonetic", "")) or "").strip(),
                    # Ton optionnel (langues tonales) ; vide sinon.
                    "tone": (_coerce_text(d.get("tone", "")) or "").strip(),
                    "translation": translation,
                })
    if not pairs and not drills:
        return None
    return {
        "kind": "phonetics",
        "focus_sound": (focus or "").strip(),
        "explanation": (_coerce_text(data.get("explanation", "")) or "").strip(),
        "minimal_pairs": pairs,
        "drills": drills,
    }


def parse_session_translation(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    items = []
    for it in (data.get("items") or []):
        if not isinstance(it, dict):
            continue
        prompt_fr = _coerce_text(it.get("prompt_fr", ""))
        expected = _coerce_text(it.get("expected", ""))
        if _non_empty_str(prompt_fr) and _non_empty_str(expected):
            items.append({
                "prompt_fr": (prompt_fr or "").strip(),
                "expected": (expected or "").strip(),
                "hint": (_coerce_text(it.get("hint", "")) or "").strip(),
            })
    if not items:
        return None
    return {"kind": "translation", "items": items}


def parse_session_dictation(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    segments = []
    for s in (data.get("segments") or []):
        if not isinstance(s, dict):
            continue
        target = _coerce_text(s.get("target", ""))
        if _non_empty_str(target):
            segments.append({
                "target": (target or "").strip(),
                "phonetic": (_coerce_text(s.get("phonetic", "")) or "").strip(),
                "translation": (_coerce_text(s.get("translation", "")) or "").strip(),
            })
    if not segments:
        return None
    return {"kind": "dictation", "segments": segments}


def _parse_production_step(obj, ref_key: str) -> dict | None:
    """Un palier de production (guided/free) : {prompt, <ref_key>, hint}."""
    if not isinstance(obj, dict):
        return None
    prompt = _coerce_text(obj.get("prompt", ""))
    if not _non_empty_str(prompt):
        return None
    return {
        "prompt": (prompt or "").strip(),
        ref_key: (_coerce_text(obj.get(ref_key, "")) or "").strip(),
        "hint": (_coerce_text(obj.get("hint", "")) or "").strip(),
    }


def parse_session_production(raw: str | dict) -> dict | None:
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    instructions = (_coerce_text(data.get("instructions", "")) or "").strip()

    # Forme « 2 paliers » (guidé → libre) : échafaudage avant production réelle.
    if "guided" in data or "free" in data:
        guided = _parse_production_step(data.get("guided"), "expected")
        free = _parse_production_step(data.get("free"), "reference")
        if free:  # le palier libre est le cœur ; le guidé est optionnel
            return {
                "kind": "production", "mode": "two_step",
                "instructions": instructions, "guided": guided, "free": free,
            }

    # Forme historique : liste de tâches one-shot.
    tasks = []
    for tk in (data.get("tasks") or []):
        if not isinstance(tk, dict):
            continue
        prompt = _coerce_text(tk.get("prompt", ""))
        if not _non_empty_str(prompt):
            continue
        tasks.append({
            "prompt": (prompt or "").strip(),
            "context": (_coerce_text(tk.get("context", "")) or "").strip(),
            "reference": (_coerce_text(tk.get("reference", "")) or "").strip(),
            "hint": (_coerce_text(tk.get("hint", "")) or "").strip(),
        })
    if not tasks:
        return None
    return {"kind": "production", "mode": "tasks", "instructions": instructions, "tasks": tasks}


def parse_session_revision(raw: str | dict) -> dict | None:
    """render_kind=revision : réutilise le quiz de révision existant."""
    base = parse_lang_revision_quiz(raw)
    if not base:
        return None
    return {"kind": "revision", **base}


def parse_session_writing(raw: str | dict) -> dict | None:
    """render_kind=writing : intégration de l'écriture (signes + lecture + drill)."""
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    signs = []
    for s in (data.get("signs") or []):
        if not isinstance(s, dict):
            continue
        sign = _coerce_text(s.get("sign", ""))
        if not _non_empty_str(sign):
            continue
        signs.append({
            "sign": (sign or "").strip(),
            "name": (_coerce_text(s.get("name", "")) or "").strip(),
            "sound": (_coerce_text(s.get("sound", "")) or "").strip(),
            "translit": (_coerce_text(s.get("translit", "")) or "").strip(),
            # Ton optionnel (langues tonales : mandarin, thaï…) ; vide sinon.
            "tone": (_coerce_text(s.get("tone", "")) or "").strip(),
            "example_word": (_coerce_text(s.get("example_word", "")) or "").strip(),
            "example_translit": (_coerce_text(s.get("example_translit", "")) or "").strip(),
            "example_translation": (_coerce_text(s.get("example_translation", "")) or "").strip(),
        })
    reading = []
    for r in (data.get("reading") or []):
        if not isinstance(r, dict):
            continue
        target = _coerce_text(r.get("target", ""))
        if _non_empty_str(target):
            reading.append({
                "target": (target or "").strip(),
                "translit": (_coerce_text(r.get("translit", "")) or "").strip(),
                "translation": (_coerce_text(r.get("translation", "")) or "").strip(),
            })
    if not signs and not reading:
        return None
    return {
        "kind": "writing",
        "intro": (_coerce_text(data.get("intro", "")) or "").strip(),
        "signs": signs,
        "reading": reading,
        "drill": _parse_qcm_list(data.get("drill")),
    }


def parse_lesson_plan(raw: str | dict) -> dict | None:
    """Plan de séance : {theme, intro} (le reste de l'arc est construit côté code)."""
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    theme = _coerce_text(data.get("theme", ""))
    if not _non_empty_str(theme):
        return None
    return {
        "theme": (theme or "").strip(),
        "intro": (_coerce_text(data.get("intro", "")) or "").strip(),
    }


def parse_placement_test(raw: str | dict) -> dict | None:
    """Test de niveau : liste d'items (qcm/translation) de difficulté croissante."""
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    items = []
    for i, it in enumerate(data.get("items") or []):
        if not isinstance(it, dict):
            continue
        question = _coerce_text(it.get("question", ""))
        if not _non_empty_str(question):
            continue
        fmt = str(it.get("format", "qcm")).strip().lower()
        fmt = "translation" if fmt == "translation" else "qcm"
        level = str(it.get("level", "A1")).strip().upper()
        if level not in {"A1", "A2", "B1", "B2", "C1", "C2"}:
            level = "A1"
        item = {
            "id": it.get("id", i + 1),
            "level": level,
            "skill": (_coerce_text(it.get("skill", "")) or "comprehension").strip(),
            "format": fmt,
            "question": (question or "").strip(),
        }
        if fmt == "qcm":
            choices = _coerce_str_list(it.get("choices", []))
            if len(choices) < 2:
                continue
            correct = str(it.get("correct", "A")).strip().upper()
            item["choices"] = choices[:4]
            item["correct"] = correct if correct in {"A", "B", "C", "D"} else "A"
        else:
            item["expected"] = (_coerce_text(it.get("expected", "")) or "").strip()
        items.append(item)
    return {"items": items} if items else None


def parse_placement_eval(raw: str | dict) -> dict | None:
    """Estimation CEFR à partir des réponses : {cefr, can_read_script, comment}."""
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    cefr = str(data.get("cefr", "A1")).strip().upper()
    if cefr not in {"A1", "A2", "B1", "B2", "C1", "C2"}:
        cefr = "A1"
    return {
        "cefr": cefr,
        "can_read_script": bool(data.get("can_read_script", False)),
        "comment": (_coerce_text(data.get("comment", "")) or "").strip(),
    }


# ── Types interactifs (correction côté client) : validation STRICTE ────────────
#
# Un exercice dont la correction automatique est fausse est PIRE que pas
# d'exercice. Les parseurs rejettent donc tout item dont la solution est
# incohérente (blank absent de la phrase, tokens != solution, answer hors borne).

def _fold_token(s: str) -> str:
    """Comparaison de tokens insensible à la casse/accents/espaces (validation ordering)."""
    import unicodedata
    norm = unicodedata.normalize("NFD", (s or "").strip().lower())
    return "".join(c for c in norm if unicodedata.category(c) != "Mn")


def parse_session_cloze(raw: str | dict) -> dict | None:
    """render_kind=cloze : complétion à trous, mode 'bank' (banque) ou 'free' (saisie)."""
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    mode = str(data.get("mode", "")).strip().lower()
    mode = "bank" if mode == "bank" else "free"
    sentences = []
    for s in (data.get("sentences") or []):
        if not isinstance(s, dict):
            continue
        text = _coerce_text(s.get("text", ""))
        blanks = _coerce_str_list(s.get("blanks", []))
        if not _non_empty_str(text) or not blanks:
            continue
        n_holes = text.count("___")
        if n_holes != len(blanks):  # cohérence trous ↔ réponses
            continue
        item = {
            "text": (text or "").strip(),
            "blanks": [b.strip() for b in blanks],
            "translation": (_coerce_text(s.get("translation", "")) or "").strip(),
        }
        if mode == "bank":
            options = _coerce_str_list(s.get("options", []))
            folded = {_fold_token(o) for o in options}
            # Chaque réponse DOIT figurer dans la banque, sinon non corrigeable.
            if not options or any(_fold_token(b) not in folded for b in item["blanks"]):
                continue
            item["options"] = [o.strip() for o in options]
        sentences.append(item)
    if not sentences:
        return None
    return {"kind": "cloze", "mode": mode,
            "instructions": (_coerce_text(data.get("instructions", "")) or "").strip(),
            "sentences": sentences}


def parse_session_ordering(raw: str | dict) -> dict | None:
    """render_kind=ordering : remise en ordre / construction depuis fragments."""
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    items = []
    for it in (data.get("items") or []):
        if not isinstance(it, dict):
            continue
        tokens = _coerce_str_list(it.get("tokens", []))
        solution = _coerce_str_list(it.get("solution", []))
        if len(tokens) < 2 or len(solution) < 2:
            continue
        # tokens DOIT être un réarrangement exact de solution (même multiset).
        if sorted(_fold_token(t) for t in tokens) != sorted(_fold_token(t) for t in solution):
            continue
        items.append({
            "tokens": [t.strip() for t in tokens],
            "solution": [t.strip() for t in solution],
            "translation": (_coerce_text(it.get("translation", "")) or "").strip(),
        })
    if not items:
        return None
    return {"kind": "ordering",
            "task": (_coerce_text(data.get("task", "")) or "").strip(),
            "items": items}


def parse_session_matching(raw: str | dict) -> dict | None:
    """render_kind=matching : appariement (relier paires)."""
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    pairs = []
    seen_left: set[str] = set()
    for p in (data.get("pairs") or []):
        if not isinstance(p, dict):
            continue
        left = _coerce_text(p.get("left", ""))
        right = _coerce_text(p.get("right", ""))
        if not _non_empty_str(left) or not _non_empty_str(right):
            continue
        key = _fold_token(left)
        if key in seen_left:  # pas de gauche en double (appariement ambigu)
            continue
        seen_left.add(key)
        pairs.append({"left": (left or "").strip(), "right": (right or "").strip()})
    if len(pairs) < 2:
        return None
    return {"kind": "matching",
            "task": (_coerce_text(data.get("task", "")) or "").strip(),
            "pairs": pairs}


def parse_session_transform(raw: str | dict) -> dict | None:
    """render_kind=transform : conjugaison / transformation guidée."""
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    items = []
    for it in (data.get("items") or []):
        if not isinstance(it, dict):
            continue
        source = _coerce_text(it.get("source", ""))
        expected = _coerce_text(it.get("expected", ""))
        if not _non_empty_str(source) or not _non_empty_str(expected):
            continue
        items.append({
            "source": (source or "").strip(),
            "expected": (expected or "").strip(),
            "focus": (_coerce_text(it.get("focus", "")) or "").strip(),
            "hint": (_coerce_text(it.get("hint", "")) or "").strip(),
        })
    if not items:
        return None
    return {"kind": "transform",
            "task": (_coerce_text(data.get("task", "")) or "").strip(),
            "items": items}


# render_kind -> parser de contenu. Source de vérité du dispatch côté LLM.
LANG_CONTENT_PARSERS: dict = {
    "dialogue": parse_session_dialogue,
    "reading": parse_session_reading,
    "vocabulary": parse_session_vocabulary,
    "phonetics": parse_session_phonetics,
    "translation": parse_session_translation,
    "dictation": parse_session_dictation,
    "production": parse_session_production,
    "revision": parse_session_revision,
    "writing": parse_session_writing,
    "cloze": parse_session_cloze,
    "ordering": parse_session_ordering,
    "matching": parse_session_matching,
    "transform": parse_session_transform,
}


def _normalize_curiosity_tone(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = _normalize_subject_token(value)
    aliases = {
        "calme": "calm",
        "calm": "calm",
        "intriguant": "intriguing",
        "intrigant": "intriguing",
        "intriguing": "intriguing",
        "concret": "concrete",
        "concrete": "concrete",
        "ludique": "playful",
        "playful": "playful",
    }
    return aliases.get(token)
