# llm/ollama_client.py — Client HTTP Ollama local
from __future__ import annotations

import base64
import itertools
import json
import logging
import queue
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable
from config import question_types
from config.settings import (
    OLLAMA_KEEP_ALIVE,
    OLLAMA_MODEL,
    OLLAMA_OPTIONS,
    OLLAMA_TASK_OPTIONS,
    OLLAMA_URL,
    task_timeout_s,
    task_wall_timeout_s,
)
from i18n import current_lang, t
from llm.prompts import (
    build_assistant_answer_prompt,
    build_chapter_summary_prompt,
    build_curiosity_hook_prompt,
    build_evaluation_prompt,
    build_flashcard_prompt,
    build_flashcard_tags_prompt,
    build_follow_up_prompt,
    build_intervention_prompt,
    build_latex_contextual_chunk_render_prompt,
    build_meta_cognition_analysis_prompt,
    build_meta_cognition_questions_prompt,
    build_profile_analysis_prompt,
    build_question_prompt,
    build_quiz_distractors_prompt,
    build_quiz_session_analysis_prompt,
    build_rephrasing_prompt,
    build_session_summary_prompt,
    build_document_digest_prompt,
)
from llm.schema_json import (
    parse_chapter_summary,
    parse_curiosity_hook,
    parse_evaluation,
    parse_flashcard,
    parse_flashcard_tags,
    parse_follow_up,
    parse_intervention,
    parse_latex_paragraph_render,
    parse_meta_cognition_analysis,
    parse_meta_cognition_questions,
    parse_profile_analysis,
    parse_question,
    parse_quiz_distractors,
    parse_quiz_session_analysis,
    parse_rephrasing,
    parse_session_summary,
    parse_document_digest,
)

logger = logging.getLogger("LLM")

Parser = Callable[[str], dict | None]
_CHUNK_MAX_CHARS = 1500
_IMAGE_MAX_BYTES = 500_000

# File de priorité LLM — sérialise toutes les requêtes Ollama sur un worker unique.
# Valeur basse = priorité haute. Ordre : math_render > descriptions > Q&A > background.
_TASK_PRIORITY: dict[str, int] = {
    "math_render":              0,
    "question":                 2,
    "follow_up":                3,
    "assistant_answer":         3,
    "evaluation":               4,
    "rephrasing":               5,
    "flashcard_standalone":     5,
    "quiz_distractors":         5,
    "quiz_analysis":            6,
    "assistant_intervention":   6,
    # Fiche d'un document fraîchement importé : travail de fond, joué pendant que
    # l'utilisateur ouvre déjà le PDF. Doit céder le pas à TOUT ce qui est
    # interactif — une question du lecteur ne doit jamais attendre derrière elle.
    "document_digest":          7,
    # ── Module langue ────────────────────────────────────────────────────────
    "lang_curriculum":          7,
    "lang_curiosity":           7,
    "lang_lesson":              7,
    "lang_exercises":           7,
    "lang_correction":          7,
    "lang_revision_quiz":       7,
    "lang_session_select":      7,
    "lang_content_dialogue":    7,
    "lang_content_reading":     7,
    "lang_content_vocab":       7,
    "lang_content_phonetics":   7,
    "lang_content_translation": 7,
    "lang_content_dictation":   7,
    "lang_content_production":  7,
    "lang_content_cloze":       7,
    "lang_content_ordering":    7,
    "lang_content_matching":    7,
    "lang_content_transform":   7,
}
_LLM_QUEUE: queue.PriorityQueue = queue.PriorityQueue()
_QUEUE_COUNTER = itertools.count()
_RAW_LATEX_OUTSIDE_MATH_RE = re.compile(
    r"\\[A-Za-z]+|(?<![\w$])[A-Za-z][A-Za-z0-9]*\s*[_^]\s*(?:\{[^}\n]{1,80}\}|[A-Za-z0-9]+)"
)
_ORPHAN_SCRIPT_OUTSIDE_MATH_RE = re.compile(r"(?<![$\\\w])[_^]\s*(?:\{[^}\n]{1,120}\}|[A-Za-z0-9]+)")
_EMPTY_SQRT_RE = re.compile(r"\\+sqrt\s*\{\s*\}")

# Token incrémenté à chaque cancel_pending_generations() — les tâches capturant
# un token obsolète s'annulent silencieusement sans appeler les callbacks.
_generation_token: int = 0


def cancel_pending_generations() -> None:
    """Invalide toutes les tâches LLM en attente ou en cours de streaming."""
    global _generation_token
    _generation_token += 1
    logger.info("Génération LLM annulée (token=%s)", _generation_token)


class CallerSlot:
    """Canal ténu entre un appelant synchrone et la tâche qu'il vient d'enfiler.

    `services/llm_bridge.run_llm_sync` ouvre un slot AVANT d'appeler la fonction
    `*_async` ; celle-ci, qui s'exécute dans le même thread, y publie le budget
    de sa tâche et y lit de quoi savoir si l'appelant a renoncé.

    Deux problèmes en un seul objet :
      * `timeout_s` — l'attente synchrone reprend le budget RÉEL de la tâche au
        lieu d'un nombre saisi à la main qui contredisait le timeout socket ;
      * `abandon` — sur timeout, l'appelant lève le drapeau et le worker jette
        la tâche au lieu de la lancer. Il n'y a qu'UN worker LLM : sans ça, un
        travail dont plus personne ne veut le résultat bloque toute la file.
    """

    __slots__ = ("abandon", "timeout_s")

    def __init__(self) -> None:
        self.abandon = threading.Event()
        self.timeout_s: float | None = None


_caller_slot = threading.local()


def open_caller_slot() -> CallerSlot:
    """Ouvre un slot pour le thread courant (appelé par run_llm_sync)."""
    slot = CallerSlot()
    _caller_slot.value = slot
    return slot


def close_caller_slot() -> None:
    """Referme le slot : une tâche enfilée hors run_llm_sync n'en hérite pas."""
    _caller_slot.value = None


def _current_caller_slot() -> "CallerSlot | None":
    return getattr(_caller_slot, "value", None)


def _queue_worker() -> None:
    while True:
        _priority, _seq, fn = _LLM_QUEUE.get()
        try:
            fn()
        except Exception as exc:
            logger.error("LLM queue worker erreur inattendue: %s", exc)
        finally:
            _LLM_QUEUE.task_done()


_worker_thread = threading.Thread(target=_queue_worker, daemon=True, name="llm-queue-worker")
_worker_thread.start()


def is_ollama_available() -> bool:
    try:
        url = OLLAMA_URL.replace("/api/generate", "/api/tags")
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def generate_question_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    prompt = build_question_prompt(
        paragraph=context.get("paragraph") or context.get("text") or "",
        chapter_title=context.get("chapter_title", ""),
        doc_title=context.get("doc_title", ""),
        metacog_profile=context.get("metacog_profile") or {},
        history=context.get("history") or [],
        session_gauges=context.get("session_gauges") or {},
        recent_question_types=context.get("recent_question_types") or [],
        preferred_question_type=context.get("preferred_question_type"),
        source_block_id=context.get("source_block_id"),
        has_existing_question=bool(context.get("has_existing_question", False)),
        standalone=bool(context.get("standalone", False)),
        past_struggles=context.get("past_struggles") or [],
        user_highlights=context.get("user_highlights") or [],
    )
    return _run_json_async(
        "question",
        prompt,
        parse_question,
        on_success,
        on_error,
        model,
        image_paths=context.get("image_paths") or [],
    )


def evaluate_answer_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    prompt = build_evaluation_prompt(
        question=context.get("question") or {},
        user_answer=context.get("user_answer") or context.get("answer_text") or "",
        paragraph=context.get("paragraph") or "",
        metacog_profile=context.get("metacog_profile") or {},
        history=context.get("history") or [],
        past_struggles=context.get("past_struggles") or [],
        objective_verdict=context.get("objective_verdict") or "",
    )
    return _run_json_async(
        "evaluation",
        prompt,
        parse_evaluation,
        on_success,
        on_error,
        model,
        image_paths=context.get("image_paths") or [],
    )


def answer_follow_up_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    prompt = build_follow_up_prompt(
        paragraph=context.get("paragraph") or "",
        user_question=context.get("user_question") or "",
        metacog_profile=context.get("metacog_profile") or {},
    )
    return _run_json_async(
        "follow_up",
        prompt,
        parse_follow_up,
        on_success,
        on_error,
        model,
        image_paths=context.get("image_paths") or [],
    )


def answer_user_question_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    """Question libre posée à la bulle assistant (contexte = snapshot de page)."""
    prompt = build_assistant_answer_prompt(
        page_text=context.get("page_text") or context.get("paragraph") or "",
        user_question=context.get("user_question") or "",
        doc_title=context.get("doc_title", ""),
        chapter_title=context.get("chapter_title", ""),
        page_number=context.get("page_number"),
        metacog_profile=context.get("metacog_profile") or {},
        session_gauges=context.get("session_gauges") or {},
        recent_exchanges=context.get("recent_exchanges") or [],
        related_flashcards=context.get("related_flashcards") or [],
        selected_snippets=context.get("selected_snippets") or [],
        user_highlights=context.get("user_highlights") or [],
        retrieved_passages=context.get("retrieved_passages") or [],
    )
    return _run_json_async(
        "assistant_answer",
        prompt,
        parse_follow_up,
        on_success,
        on_error,
        model,
        image_paths=context.get("image_paths") or [],
    )


def decide_intervention_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    """Décision d'intervention autonome de l'assistant pendant la lecture."""
    prompt = build_intervention_prompt(context)
    return _run_json_async(
        "assistant_intervention",
        prompt,
        parse_intervention,
        on_success,
        on_error,
        model,
    )


def generate_rephrasing_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    prompt = build_rephrasing_prompt(
        paragraph=context.get("paragraph") or "",
        attempt_count=int(context.get("attempt_count") or 0),
    )
    return _run_json_async(
        "rephrasing",
        prompt,
        parse_rephrasing,
        on_success,
        on_error,
        model,
        image_paths=context.get("image_paths") or [],
    )


def generate_quiz_session_analysis_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    prompt = build_quiz_session_analysis_prompt(
        answers_history=context.get("answers_history") or [],
        subject_profiles=context.get("subject_profiles") or [],
    )
    return _run_json_async("quiz_analysis", prompt, parse_quiz_session_analysis, on_success, on_error, model)


def generate_quiz_distractors_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    """Génère en un seul appel 3 distracteurs par question pour une session de QCM."""
    prompt = build_quiz_distractors_prompt(context.get("items") or [])
    return _run_json_async("quiz_distractors", prompt, parse_quiz_distractors, on_success, on_error, model)


def generate_session_summary_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    session_data = context.get("session_data") or {}
    profile = context.get("metacog_profile") or session_data.get("profile") or {}
    session_gauges = session_data.get("gauges") or session_data.get("session_score") or {}
    prompt = build_session_summary_prompt(
        session_data=session_data,
        metacog_profile=profile,
        session_gauges=session_gauges,
    )
    return _run_json_async("session_summary", prompt, parse_session_summary, on_success, on_error, model)


def generate_meta_cognition_questions_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    prompt = build_meta_cognition_questions_prompt(
        session_summary=context.get("session_summary") or {},
        recent_user_answers=context.get("recent_user_answers") or [],
        previous_end_questions=context.get("previous_end_questions") or [],
        user_profile=context.get("user_profile") or {},
    )
    return _run_json_async("meta_cognition_questions", prompt, parse_meta_cognition_questions, on_success, on_error, model)


def analyze_meta_cognition_answers_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    prompt = build_meta_cognition_analysis_prompt(
        questions=context.get("questions") or [],
        answers=context.get("answers") or [],
        session_context=context.get("session_context") or {},
        user_profile=context.get("user_profile") or {},
    )
    return _run_json_async("meta_cognition_analysis", prompt, parse_meta_cognition_analysis, on_success, on_error, model)


def generate_profile_analysis_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    """Analyse générale (évolutive) de l'apprenant, affichée sur la page profil."""
    prompt = build_profile_analysis_prompt(
        profile=context.get("profile") or {},
        session_metrics=context.get("session_metrics") or {},
        session_gauges=context.get("session_gauges") or {},
        reflections=context.get("reflections") or [],
        previous_analysis=context.get("previous_analysis") or "",
    )
    return _run_json_async("profile_analysis", prompt, parse_profile_analysis, on_success, on_error, model)


def generate_flashcard_tags_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    prompt = build_flashcard_tags_prompt(
        front=context.get("front") or "",
        back=context.get("back") or "",
        session_context=context.get("session_context") or {},
        existing_sections=context.get("existing_sections") or [],
        existing_tags=context.get("existing_tags") or [],
    )
    return _run_json_async("flashcard_tags", prompt, parse_flashcard_tags, on_success, on_error, model)


def make_standalone_flashcard_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    """Réécrit un échange (recto/verso bruts) en flashcard autoportante."""
    prompt = build_flashcard_prompt(
        front=context.get("front") or "",
        back=context.get("back") or "",
        paragraph=context.get("paragraph") or "",
    )
    return _run_json_async("flashcard_standalone", prompt, parse_flashcard, on_success, on_error, model)


def generate_chapter_summary_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    prompt = build_chapter_summary_prompt(
        chapter_title=context.get("chapter_title", ""),
        paragraphs_summary=context.get("paragraphs_summary") or [],
        metacog_profile=context.get("metacog_profile") or {},
    )
    return _run_json_async("chapter_summary", prompt, parse_chapter_summary, on_success, on_error, model)


def generate_document_digest_async(
    doc_title: str,
    excerpt: str,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    prompt = build_document_digest_prompt(doc_title, excerpt)
    return _run_json_async(
        "document_digest",
        prompt,
        parse_document_digest,
        on_success,
        on_error,
        model,
    )


def generate_curiosity_hook_async(
    doc_title: str,
    chapter_title: str,
    subchapter_title: str,
    chapter_excerpt: str,
    profile: dict | None,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    prompt = build_curiosity_hook_prompt(
        doc_title=doc_title,
        chapter_title=chapter_title,
        subchapter_title=subchapter_title,
        chapter_excerpt=chapter_excerpt,
        profile=profile or {},
    )
    return _run_json_async("curiosity_hook", prompt, parse_curiosity_hook, on_success, on_error, model)


def render_math_paragraph_async(
    paragraph_text: str,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
    image_paths: list[str] | None = None,
) -> None:
    chunks = _split_paragraph_for_llm_with_context(paragraph_text)
    safe_images = _filter_heavy_images(image_paths or [])
    task_options = OLLAMA_TASK_OPTIONS.get("math_render", OLLAMA_OPTIONS)
    seq = next(_QUEUE_COUNTER)
    captured_token = _generation_token

    def _run_chunks() -> None:
        if _generation_token != captured_token:
            logger.debug("Tâche LLM math_render annulée (token obsolète)")
            return
        try:
            parts = []
            for i, chunk in enumerate(chunks):
                target = chunk["target"]
                imgs = safe_images if i == 0 else []
                prompt = build_latex_contextual_chunk_render_prompt(
                    target,
                    chunk.get("previous_context", ""),
                    chunk.get("next_context", ""),
                )
                try:
                    parsed = _generate_json(
                        "math_render",
                        prompt,
                        parse_latex_paragraph_render,
                        model=model,
                        retries=1,
                        image_paths=imgs,
                        options=task_options,
                    )
                    parts.append(_sanitize_math_paragraph_render(parsed.get("rendered"), target))
                except Exception as exc:
                    logger.warning("math_render chunk %s/%s échoué: %s", i + 1, len(chunks), exc)
                    parts.append(target)
            on_success({"rendered": "\n\n".join(parts)})
        except Exception as exc:
            logger.error("Échec génération LLM math_render : %s", exc)
            on_error(str(exc))

    _LLM_QUEUE.put((0, seq, _run_chunks))


def generate_questions_async(
    text: str,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    """
    Compatibilité API : certains appels attendent encore une liste de questions.
    La v1.3 génère désormais une question par paragraphe.
    """
    def _on_question(question: dict) -> None:
        on_success([{
            **question,
            "answer": question["expected_answer"],
            "llm_model": model,
        }])

    return generate_question_async({"paragraph": text}, _on_question, on_error, model)


def _split_paragraph_for_llm(text: str, max_chars: int = _CHUNK_MAX_CHARS) -> list[str]:
    """Découpe un texte long en chunks cohérents sans couper volontairement les blocs."""
    if len(text) <= max_chars:
        return [text]

    chunks = [chunk.strip() for chunk in text.split("\n\n") if chunk.strip()]
    result: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            result.append(chunk)
            continue

        cut = _find_safe_cut_outside_math(chunk, max_chars)
        if cut == -1:
            cut = min(len(chunk), max_chars) - 1
        result.append(chunk[: cut + 1].strip())
        tail = chunk[cut + 1 :].strip()
        if tail:
            result.extend(_split_paragraph_for_llm(tail, max_chars))

    return result or [text[:max_chars]]


def _split_paragraph_for_llm_with_context(
    text: str,
    max_chars: int = _CHUNK_MAX_CHARS,
    previous_context_chars: int = 520,
    next_context_chars: int = 320,
    source_block_ids: list[str] | None = None,
    document_context_before: str = "",
) -> list[dict[str, str | list[str]]]:
    """Split text into contextual chunks for LLM processing.

    Each chunk carries:
      - target: the text to rewrite
      - previous_context / next_context: surrounding text for understanding only
      - instruction: explicit reminder not to rewrite context
      - source_block_ids: which blocks this chunk belongs to (for dedup at recomposition)

    document_context_before seeds the first chunk's previous_context with text
    from already-rendered surrounding blocks so the LLM has document-level context.
    """
    chunks = _split_paragraph_for_llm(text, max_chars=max_chars)
    result: list[dict[str, str | list[str]]] = []
    for index, target in enumerate(chunks):
        if index > 0:
            previous_context = chunks[index - 1][-previous_context_chars:]
        else:
            # Seed from document-level rendered context when no intra-block context exists.
            previous_context = document_context_before[-previous_context_chars:] if document_context_before else ""
        next_context = chunks[index + 1][:next_context_chars] if index + 1 < len(chunks) else ""
        result.append({
            "target": target,
            "previous_context": previous_context,
            "next_context": next_context,
            "instruction": "Rewrite only the 'target' section. The context sections are for understanding only.",
            "source_block_ids": list(source_block_ids or []),
        })
    return result


def _sanitize_math_paragraph_render(rendered: str | None, source: str) -> str:
    """Reject math renderer outputs that would make the extracted PDF text worse."""
    source = (source or "").strip()
    text = (rendered or "").strip()
    if not text:
        return source
    degradation_reason = _math_render_degradation_reason(text, source)
    if degradation_reason:
        logger.debug("Rendu math LLM rejeté (%s), repli sur le texte PDF source.", degradation_reason)
        logger.debug(
            "Rendu math rejeté (%s): source=%r rendu=%r",
            degradation_reason,
            source[:500],
            text[:500],
        )
        return source
    return text


def _math_render_looks_degraded(rendered: str, source: str) -> bool:
    return _math_render_degradation_reason(rendered, source) is not None


def _math_render_degradation_reason(rendered: str, source: str) -> str | None:
    if not rendered:
        return "empty"
    if source and len(rendered) < max(8, int(len(source) * 0.35)):
        return "too_short"

    outside_math = _strip_math_spans(rendered)
    if _EMPTY_SQRT_RE.search(rendered):
        return "empty_sqrt"
    if _ORPHAN_SCRIPT_OUTSIDE_MATH_RE.search(outside_math):
        return "orphan_script_outside_math"
    if _RAW_LATEX_OUTSIDE_MATH_RE.search(outside_math):
        return "raw_latex_outside_math"

    source_mathish = _count_mathish_tokens(source)
    if source_mathish >= 3:
        rendered_math_spans = len(_math_ranges(rendered))
        rendered_mathish = _count_mathish_tokens(rendered)
        if rendered_math_spans == 0 and rendered_mathish >= source_mathish:
            return "undelimited_math"

    return None


def _json_math_render_fallback(
    chunk: str,
    image_paths: list[str],
    task_options: dict,
    model: str,
    *,
    previous_context: str = "",
    next_context: str = "",
) -> str:
    try:
        parsed = _generate_json(
            "math_render",
            build_latex_contextual_chunk_render_prompt(chunk, previous_context, next_context),
            parse_latex_paragraph_render,
            model=model,
            retries=1,
            image_paths=image_paths,
            options=task_options,
        )
        return _sanitize_math_paragraph_render(parsed.get("rendered"), chunk)
    except Exception as exc:
        logger.warning("math_render JSON de secours échoué, repli texte brut: %s", exc)
        return chunk


def _strip_math_spans(text: str) -> str:
    if not text:
        return ""
    ranges = _math_ranges(text)
    if not ranges:
        return text
    parts: list[str] = []
    cursor = 0
    for start, end in ranges:
        if cursor < start:
            parts.append(text[cursor:start])
        parts.append(" ")
        cursor = max(cursor, end)
    if cursor < len(text):
        parts.append(text[cursor:])
    return "".join(parts)


def _count_mathish_tokens(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\\[A-Za-z]+|[_^{}]|[α-ωΑ-Ω]|[⊗∑∏∞≤≥≈≃∼≠·]", text))


def _find_safe_cut_outside_math(text: str, max_chars: int) -> int:
    """Return an inclusive cut index that does not split a delimited math span."""
    if not text:
        return -1

    limit = min(len(text), max(1, int(max_chars)))
    ranges = _math_ranges(text)
    for start, end in ranges:
        if start < limit < end:
            limit = min(len(text), end)
            break

    for index in range(limit - 1, 0, -1):
        if text[index] not in ".!?;:":
            continue
        if _index_in_ranges(index, ranges):
            continue
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if not next_char or next_char.isspace():
            return index

    for index in range(limit - 1, 0, -1):
        if text[index].isspace() and not _index_in_ranges(index, ranges):
            return index

    for start, end in ranges:
        if start < max_chars < end:
            return end - 1
    return -1


def _math_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    mode: str | None = None
    start = 0
    index = 0

    while index < len(text):
        if mode is None:
            if text.startswith(r"\(", index):
                mode = r"\)"
                start = index
                index += 2
                continue
            if text.startswith(r"\[", index):
                mode = r"\]"
                start = index
                index += 2
                continue
            if text.startswith("$$", index) and not _is_escaped(text, index):
                mode = "$$"
                start = index
                index += 2
                continue
            if text[index] == "$" and not _is_escaped(text, index):
                mode = "$"
                start = index
                index += 1
                continue
            index += 1
            continue

        if mode in {r"\)", r"\]"}:
            if text.startswith(mode, index):
                ranges.append((start, index + 2))
                mode = None
                index += 2
                continue
        elif mode == "$$":
            if text.startswith("$$", index) and not _is_escaped(text, index):
                ranges.append((start, index + 2))
                mode = None
                index += 2
                continue
        elif mode == "$" and text[index] == "$" and not _is_escaped(text, index):
            ranges.append((start, index + 1))
            mode = None
            index += 1
            continue

        index += 1

    if mode is not None:
        ranges.append((start, len(text)))
    return ranges


def _index_in_ranges(index: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= index < end for start, end in ranges)


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _filter_heavy_images(image_paths: list[str]) -> list[str]:
    result = []
    for path in image_paths:
        try:
            size = Path(path).stat().st_size
            if size <= _IMAGE_MAX_BYTES:
                result.append(path)
            else:
                logger.debug(
                    "Image trop lourde (%d Ko), non envoyée au LLM: %s",
                    size // 1024,
                    path,
                )
        except OSError:
            pass
    return result


def _run_json_async(
    label: str,
    prompt: str,
    parser: Parser,
    on_success,
    on_error,
    model: str,
    image_paths: list[str] | None = None,
) -> None:
    task_options = OLLAMA_TASK_OPTIONS.get(label, OLLAMA_OPTIONS)
    priority = _TASK_PRIORITY.get(label, 6)
    seq = next(_QUEUE_COUNTER)
    captured_token = _generation_token
    slot = _current_caller_slot()
    if slot is not None:
        slot.timeout_s = task_wall_timeout_s(label)

    def _run() -> None:
        if _generation_token != captured_token:
            logger.debug("Tâche LLM %s annulée (token obsolète)", label)
            return
        if slot is not None and slot.abandon.is_set():
            logger.debug("Tâche LLM %s jetée (appelant parti)", label)
            return
        try:
            logger.info("Génération LLM %s lancée modèle=%s", label, model)
            parsed = _generate_json(label, prompt, parser, model=model, retries=3, image_paths=image_paths or [], options=task_options)
            logger.info("Génération LLM %s terminée", label)
            if _generation_token != captured_token:
                logger.debug("Résultat LLM %s ignoré (token obsolète)", label)
                return
            on_success(parsed)
        except Exception as exc:
            logger.error("Échec génération LLM %s : %s", label, exc)
            on_error(str(exc))

    _LLM_QUEUE.put((priority, seq, _run))


def _run_text_async(
    label: str,
    prompt: str,
    on_success,
    on_error,
    model: str,
    image_paths: list[str] | None = None,
) -> None:
    """Comme `_run_json_async` mais pour une sortie TEXTE LIBRE (pas de schéma JSON).

    Utilisé par le brainstorming : la réponse conversationnelle peut être longue et
    contenir du markdown, ce que le mode JSON d'Ollama gère mal. On passe par la même
    file priorisée pour rester sérialisé avec les autres tâches LLM.
    """
    task_options = OLLAMA_TASK_OPTIONS.get(label, OLLAMA_OPTIONS)
    priority = _TASK_PRIORITY.get(label, 6)
    seq = next(_QUEUE_COUNTER)
    captured_token = _generation_token
    slot = _current_caller_slot()
    if slot is not None:
        slot.timeout_s = task_wall_timeout_s(label)

    def _run() -> None:
        if _generation_token != captured_token:
            logger.debug("Tâche LLM %s annulée (token obsolète)", label)
            return
        if slot is not None and slot.abandon.is_set():
            logger.debug("Tâche LLM %s jetée (appelant parti)", label)
            return
        try:
            logger.info("Génération LLM %s (texte) lancée modèle=%s", label, model)
            images = _load_ollama_images(image_paths or [])
            try:
                raw = _call_ollama(prompt, model, images=images, options=task_options, format_json=False, task=label)
            except Exception as exc:
                if images:
                    logger.warning("Ollama a refusé les images, repli texte seul: %s", exc)
                    raw = _call_ollama(prompt, model, images=[], options=task_options, format_json=False, task=label)
                else:
                    raise
            logger.info("Génération LLM %s terminée", label)
            if _generation_token != captured_token:
                logger.debug("Résultat LLM %s ignoré (token obsolète)", label)
                return
            on_success((raw or "").strip())
        except Exception as exc:
            logger.error("Échec génération LLM %s : %s", label, exc)
            on_error(str(exc))

    _LLM_QUEUE.put((priority, seq, _run))


def _generate_json(
    label: str,
    prompt: str,
    parser: Parser,
    model: str,
    retries: int = 1,
    image_paths: list[str] | None = None,
    options: dict | None = None,
) -> dict:
    attempts = retries + 1
    # Échéance de la tâche ENTIÈRE : on ne rejoue pas au-delà du budget que
    # l'appelant synchrone attend (config.settings.task_wall_timeout_s), sinon
    # les tentatives suivantes travaillent pour un destinataire déjà parti.
    deadline = time.monotonic() + task_wall_timeout_s(label)
    last_raw = ""
    last_error: Exception | None = None
    images = _load_ollama_images(image_paths or [])
    current_prompt = prompt
    for attempt in range(1, attempts + 1):
        try:
            raw = _call_ollama(current_prompt, model, images=images, options=options, task=label)
        except Exception as exc:
            if images:
                logger.warning("Ollama a refusé les images jointes, repli texte seul: %s", exc)
                images = []
                try:
                    raw = _call_ollama(current_prompt, model, images=[], options=options, task=label)
                except Exception as text_exc:
                    last_error = text_exc
                    logger.debug(
                        "Appel LLM %s sans image échoué tentative %s/%s: %s",
                        label,
                        attempt,
                        attempts,
                        text_exc,
                    )
                    if attempt < attempts and time.monotonic() < deadline:
                        current_prompt = prompt
                        continue
                    break
            else:
                last_error = exc
                logger.debug(
                    "Appel LLM %s échoué tentative %s/%s: %s",
                    label,
                    attempt,
                    attempts,
                    exc,
                )
                if attempt < attempts and time.monotonic() < deadline:
                    current_prompt = prompt
                    continue
                break
        last_raw = raw
        parsed = parser(raw)
        if parsed is not None:
            return parsed
        logger.debug("JSON LLM %s non conforme tentative %s/%s", label, attempt, attempts)
        if time.monotonic() >= deadline:
            logger.debug("Budget de la tâche %s épuisé : plus de réparation", label)
            break
        if attempt < attempts:
            current_prompt = _build_json_repair_prompt(label, prompt, raw)

    logger.debug("Dernière réponse JSON invalide %s: %s", parser, last_raw[:500])
    fallback = _fallback_json_result(label, prompt, parser, last_raw)
    if fallback is not None:
        reason = f"erreur appel: {last_error}" if last_error else "JSON invalide"
        logger.warning("LLM %s non exploitable après %s tentative(s), repli local (%s).", label, attempts, reason)
        return fallback
    if last_error is not None:
        raise RuntimeError(f"Échec LLM {label} après {attempts} tentative(s): {last_error}") from last_error
    raise ValueError(f"Réponse LLM JSON invalide après {attempts} tentative(s).")


def _build_json_repair_prompt(label: str, original_prompt: str, raw_response: str) -> str:
    raw = (raw_response or "").strip()[:2800]
    schema = {
        "question": """
{
  "question_type": "open",
  "question": "question courte",
  "choices": [],
  "expected_answer": "réponse attendue",
  "evaluation_criteria": ["critère"],
  "paragraph_mask": {"enabled": false}
}""",
        "evaluation": """
{
  "verdict": "partial",
  "feedback": "retour bref",
  "completion": "",
  "hint": "",
  "metacog_signals": {},
  "curiosity_signals": {},
  "creativity_signals": {},
  "answer_to_user_question": null,
  "flashcard": null
}""",
        "follow_up": """
{
  "answer": "réponse claire",
  "metacog_signals": {},
  "curiosity_signals": {}
}""",
        "rephrasing": """
{
  "rephrasing_angle": "angle choisi",
  "rephrased_paragraph": "reformulation fidèle",
  "note": "note brève"
}""",
        "session_summary": """
{
  "session_summary": {
    "duration_s": 0,
    "paragraphs_read": 0,
    "flashcards_created": 0,
    "rephrasings_count": 0,
    "success_rate": 0.0,
    "qualitative_summary": "phrase courte",
    "metacognitive_questions": ["question 1", "question 2", "question 3"]
  }
}""",
        "meta_cognition_questions": """
{"questions": ["question 1", "question 2", "question 3"]}""",
        "meta_cognition_analysis": """
{
  "score_delta": 0.0,
  "score": 50.0,
  "reasoning": "raisonnement bref",
  "detected_signals": {}
}""",
        "flashcard_tags": """
{"tags": ["tag 1", "tag 2"]}""",
        "chapter_summary": """
{
  "chapter_summary": {
    "title": "titre",
    "overview": "synthèse courte",
    "recap_qa": [
      {"question": "question 1", "answer": "réponse 1"},
      {"question": "question 2", "answer": "réponse 2"},
      {"question": "question 3", "answer": "réponse 3"}
    ]
  }
}""",
        "curiosity_hook": """
{
  "curiosity_hook": "phrase d'accroche",
  "tone": "concrete",
  "link_with_chapter": "lien bref",
  "estimated_accessibility": 0.6
}""",
        "quiz_analysis": """
{
  "analysis": "synthèse courte",
  "weak_subjects": [],
  "courses_to_review": [
    {"title": "nom du cours", "subject": "matière", "reason": "raison courte", "document": "", "chapter_title": ""}
  ]
}""",
        "math_render": """
{"rendered": "texte nettoyé"}""",
        "document_digest": """
{"subject": "culture", "summary": "phrase courte décrivant le contenu du document", "keywords": ["mot-clé 1", "mot-clé 2", "mot-clé 3"]}""",
        "assistant_answer": """
{
  "answer": "réponse claire",
  "metacog_signals": {},
  "curiosity_signals": {}
}""",
        "assistant_intervention": """
{
  "should_intervene": false,
  "kind": "offer_help",
  "message": "",
  "question": ""
}""",
    }.get(label, "{...}")
    original = (original_prompt or "").strip()[:3200]
    return f"""La réponse suivante n'a pas respecté le contrat JSON attendu.
Réécris-la en un unique objet JSON valide, sans Markdown, sans commentaire et sans texte autour.
Garde le sens de la réponse précédente. Si elle est tronquée ou ambiguë, régénère depuis le prompt initial.
Si une information optionnelle manque, utilise une valeur neutre.
Pour une question, question_type doit être exactement une de ces valeurs :
{question_types.keys_line()}.

Tâche : {label}
Format attendu :
{schema}

Réponse précédente à réparer :
---
{raw}
---

Prompt initial utile en cas de réponse tronquée :
---
{original}
---"""


def _fallback_json_result(label: str, prompt: str, parser: Parser, last_raw: str = "") -> dict | None:
    if last_raw:
        parsed = parser(_closed_json_candidate(last_raw))
        if parsed is not None:
            return parsed

    if label == "question":
        return _fallback_question_from_prompt(prompt)
    if label == "evaluation":
        return _fallback_evaluation_from_prompt(prompt)
    if label == "follow_up":
        return _fallback_follow_up_from_prompt(prompt)
    if label == "assistant_answer":
        return _fallback_follow_up_from_prompt(prompt)
    if label == "assistant_intervention":
        # En dégradé, l'assistant se tait plutôt que d'inventer une intervention.
        return {"should_intervene": False, "kind": "offer_help", "message": "", "question": ""}
    if label == "rephrasing":
        return _fallback_rephrasing_from_prompt(prompt)
    if label == "session_summary":
        return _fallback_session_summary_from_prompt(prompt)
    if label == "meta_cognition_questions":
        return _fallback_meta_cognition_questions_from_prompt(prompt)
    if label == "meta_cognition_analysis":
        return _fallback_meta_cognition_analysis_from_prompt(prompt)
    if label == "flashcard_tags":
        return _fallback_flashcard_tags_from_prompt(prompt)
    if label == "chapter_summary":
        return _fallback_chapter_summary_from_prompt(prompt)
    if label == "curiosity_hook":
        return _fallback_curiosity_hook_from_prompt(prompt)
    if label == "quiz_analysis":
        return _fallback_quiz_analysis_from_prompt(prompt)
    if label == "math_render":
        return _fallback_math_render_from_prompt(prompt)
    if label == "document_digest":
        return _fallback_document_digest_from_prompt(prompt)
    return None


def _closed_json_candidate(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return stripped
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in stripped:
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
    return stripped + suffix


# Types que le repli hors-ligne sait vraiment fabriquer sans LLM : ceux dont la
# consigne est générique. Sous-ensemble assumé du registre — « ordering » exige des
# étapes réelles, « recall » un masque, « error_detection » une erreur plausible :
# hors-ligne, on retombe alors sur la question dictée par le contenu de la page.
_FALLBACK_PREFERRED_TYPES = frozenset({
    "open", "comprehension", "curiosity", "metacognition", "anticipation",
    "teach_back", "elaboration_why", "connection", "counterexample",
})


def _fallback_question_from_prompt(prompt: str) -> dict | None:
    english = current_lang() == "en"
    paragraph = (
        _extract_prompt_section(prompt, "Paragraphe à vérifier")
        or _extract_prompt_section(prompt, "Paragraph to assess")
    )
    paragraph = re.sub(r"\s+", " ", paragraph).strip()
    source_block_id = _extract_source_block_id(prompt)
    topic = _fallback_topic_from_paragraph(paragraph)
    topic_ref = f'"{topic}"' if english and topic else f"« {topic} »" if topic else ""
    has_math = _looks_like_math(paragraph)
    has_table = "[Tableau" in paragraph or "[Table" in paragraph or "|" in paragraph
    has_figure = "[Figure" in paragraph
    existing_question = _extract_first_question(paragraph)
    preferred_type = _extract_preferred_question_type(prompt)
    if "Stratégie : diversifier les types de questions" in prompt or "Strategy : diversify question types" in prompt:
        preferred_type = ""
    needs_pause_hint = (
        "Attention actuelle sous le seuil 45" in prompt
        or "Current attention below threshold 45" in prompt
    )

    if existing_question:
        question_type = "comprehension"
        question = existing_question
        if english:
            expected = "Answer the question present in the passage directly, using the provided text."
            criteria = ["Answers the passage question", "Uses the information available in the paragraph"]
        else:
            expected = "Il faut répondre directement à la question présente dans le passage, en s'appuyant sur le texte fourni."
            criteria = [
                "Répond à la question du passage",
                "S'appuie sur les informations disponibles dans le paragraphe",
            ]
    elif has_figure:
        question_type = "visualization"
        if english:
            question = (
                f"What should you observe in the figure to understand the role of {topic_ref} in this passage?"
                if topic_ref else
                "What should you observe in the figure to understand the main idea of this passage?"
            )
            expected = "Describe the visual element or relationship indicated by the passage and connect it to the main idea."
            criteria = ["Identifies the relevant visual element", "Connects the representation to the passage idea"]
        else:
            if topic_ref:
                question = f"Que dois-tu observer dans la figure pour comprendre le rôle de {topic_ref} dans ce passage ?"
            else:
                question = "Que dois-tu observer dans la figure pour comprendre l'idée principale de ce passage ?"
            expected = "Il faut décrire l'élément visuel ou la relation indiquée par le passage et le relier à l'idée principale."
            criteria = [
                "Identifie l'élément visuel pertinent",
                "Relie la représentation à l'idée du passage",
            ]
    elif has_table:
        question_type = "application"
        if english:
            question = (
                f"Based on the table, what comparison or trend stands out about {topic_ref}?"
                if topic_ref else
                "Based on the table, what main comparison or trend stands out?"
            )
            expected = "Use the table data or trends and connect them to the passage."
            criteria = ["Identifies a table datum, comparison, or trend", "Connects this observation to the passage idea"]
        else:
            if topic_ref:
                question = f"D'après le tableau, quelle comparaison ou tendance ressort à propos de {topic_ref} ?"
            else:
                question = "D'après le tableau, quelle comparaison ou tendance principale ressort ?"
            expected = "Il faut utiliser les données ou tendances du tableau et les relier au passage."
            criteria = [
                "Repère une donnée, une comparaison ou une tendance du tableau",
                "Relie cette observation à l'idée du passage",
            ]
    elif has_math:
        question_type = "application"
        if english:
            question = (
                f"In the formula from the passage, what does {topic_ref} help obtain or compare?"
                if topic_ref else
                "In the formula from the passage, what does it help obtain or compare?"
            )
            expected = "Explain the role of the formula or mathematical notation in the passage's reasoning."
            criteria = ["Reuses the passage notation correctly", "Explains the formula's role in the reasoning"]
        else:
            if topic_ref:
                question = f"Dans la formule du passage, que permet d'obtenir ou de comparer {topic_ref} ?"
            else:
                question = "Dans la formule du passage, que permet-on d'obtenir ou de comparer ?"
            expected = "Il faut expliquer le rôle de la formule ou des notations mathématiques dans le raisonnement du passage."
            criteria = [
                "Réutilise correctement les notations du passage",
                "Explique le rôle de la formule dans le raisonnement",
            ]
    else:
        question_type = "open"
        if english:
            if topic_ref:
                question = f"What role does {topic_ref} play in the main idea of this passage?"
                expected = f"Explain the role of {topic_ref} in the passage in your own words."
            else:
                question = "What new clarification does this passage add to the main idea?"
                expected = "Reformulate the central contribution of the passage in your own words."
            criteria = ["Identifies the central idea", "Uses the passage content"]
        else:
            if topic_ref:
                question = f"Quel rôle joue {topic_ref} dans l'idée principale de ce passage ?"
                expected = f"Il faut expliquer le rôle de {topic_ref} dans le passage, avec ses propres mots."
            else:
                question = "Quelle précision nouvelle ce passage ajoute-t-il à l'idée principale ?"
                expected = "Il faut reformuler l'apport central du passage avec ses propres mots."
            criteria = [
                "Repère l'idée centrale",
                "S'appuie sur le contenu du passage",
            ]
    if preferred_type in _FALLBACK_PREFERRED_TYPES and not existing_question:
        question_type, question, expected, criteria = _fallback_preferred_question(
            preferred_type,
            topic_ref,
            paragraph,
        )
    return parse_question({
        "question_type": question_type,
        "question": question,
        "choices": [],
        "expected_answer": expected,
        "evaluation_criteria": criteria,
        "session_hint": t("qa.low_attention_hint") if needs_pause_hint else "",
        "source_block_id": source_block_id,
        "paragraph_mask": {"enabled": False},
    })


def _extract_source_block_id(prompt: str) -> str:
    match = re.search(r'"source_block_id"\s*:\s*"([^"]*)"', prompt or "")
    return match.group(1).strip() if match else ""


def _extract_preferred_question_type(prompt: str) -> str:
    match = re.search(r'(?:Type pédagogique cible|Target pedagogical type)\s*:\s*"([^"]+)"', prompt or "")
    if not match:
        return ""
    value = match.group(1).strip().lower()
    return value if value in question_types.KEYS else ""


def _fallback_preferred_question(
    preferred_type: str,
    topic_ref: str,
    paragraph: str,
) -> tuple[str, str, str, list[str]]:
    english = current_lang() == "en"
    focus = topic_ref or ("the main idea of the passage" if english else "l'idée principale du passage")
    if preferred_type == "curiosity":
        if english:
            return (
                "curiosity",
                f"What new question would you like to explore about {focus}, while staying connected to the passage?",
                "Formulate a lead or hypothesis grounded in the passage.",
                ["Formulates a relevant curiosity", "Stays connected to the passage content"],
            )
        return (
            "curiosity",
            f"Quelle question nouvelle te donne envie d'explorer {focus}, tout en restant liée au passage ?",
            "Il faut formuler une piste ou une hypothèse ancrée dans le passage.",
            ["Formule une curiosité pertinente", "Reste relié au contenu du passage"],
        )
    if preferred_type == "metacognition":
        if english:
            return (
                "metacognition",
                f"How would you check that you really understand {focus}?",
                "Describe a checking strategy or personal reformulation.",
                ["Describes a comprehension strategy", "Identifies what needs to be checked"],
            )
        return (
            "metacognition",
            f"Comment t'y prendrais-tu pour vérifier que tu comprends bien {focus} ?",
            "Il faut décrire une stratégie de vérification ou de reformulation personnelle.",
            ["Décrit une stratégie de compréhension", "Identifie ce qui doit être vérifié"],
        )
    if preferred_type == "anticipation":
        if english:
            return (
                "anticipation",
                f"What point might be difficult in {focus}, and how would you detect it?",
                "Anticipate a plausible difficulty and propose a concrete cue.",
                ["Identifies a possible difficulty", "Proposes a sign or method to check it"],
            )
        return (
            "anticipation",
            f"Quel point pourrait te poser difficulté dans {focus}, et comment le repérerais-tu ?",
            "Il faut anticiper une difficulté plausible et proposer un repère concret.",
            ["Repère une difficulté possible", "Propose un signe ou une méthode pour la vérifier"],
        )
    if preferred_type == "comprehension":
        if english:
            return (
                "comprehension",
                f"What explicit information does the passage give about {focus}?",
                "Extract the information directly provided by the passage.",
                ["Uses explicit information", "Answers briefly and faithfully"],
            )
        return (
            "comprehension",
            f"Quelle information explicite le passage donne-t-il sur {focus} ?",
            "Il faut extraire l'information directement fournie par le passage.",
            ["S'appuie sur une information explicite", "Répond de façon courte et fidèle"],
        )
    if preferred_type == "teach_back":
        if english:
            return (
                "teach_back",
                f"Explain {focus} in two sentences to someone who has never seen it, without technical jargon.",
                "Reformulate the notion simply, without jargon, while staying faithful to the passage.",
                ["Explanation understandable by a beginner", "No jargon", "Stays faithful to the passage"],
            )
        return (
            "teach_back",
            f"Explique {focus} en deux phrases à quelqu'un qui ne l'a jamais vu, sans jargon technique.",
            "Il faut reformuler la notion simplement, sans jargon, en restant fidèle au passage.",
            ["Explication compréhensible par un débutant", "Sans jargon", "Reste fidèle au passage"],
        )
    if preferred_type == "elaboration_why":
        if english:
            return (
                "elaboration_why",
                f"Why is what the passage states about {focus} true, rather than the opposite?",
                "Justify with the mechanism or reason given in the passage.",
                ["Gives a justification, not a restatement", "Relies on the passage"],
            )
        return (
            "elaboration_why",
            f"Pourquoi ce que le passage affirme sur {focus} est-il vrai, plutôt que l'inverse ?",
            "Il faut justifier par le mécanisme ou la raison donnée dans le passage.",
            ["Donne une justification, pas une reformulation", "S'appuie sur le passage"],
        )
    if preferred_type == "connection":
        if english:
            return (
                "connection",
                f"What does {focus} connect to in what you have already read or answered?",
                "Name a link with an earlier notion and say what the two have in common.",
                ["Names an explicit link", "Justifies what the two elements share"],
            )
        return (
            "connection",
            f"À quoi {focus} se relie-t-il dans ce que tu as déjà lu ou répondu ?",
            "Il faut nommer un lien avec une notion antérieure et dire ce que les deux ont en commun.",
            ["Nomme un lien explicite", "Justifie ce que les deux éléments partagent"],
        )
    if preferred_type == "counterexample":
        if english:
            return (
                "counterexample",
                f"Under what condition would what the passage states about {focus} stop being true?",
                "Give a counterexample or name the condition that breaks the statement.",
                ["Identifies a validity condition", "Stays grounded in the passage"],
            )
        return (
            "counterexample",
            f"Dans quel cas ce que le passage affirme sur {focus} cesserait-il d'être vrai ?",
            "Il faut donner un contre-exemple ou nommer la condition qui casse l'affirmation.",
            ["Identifie une condition de validité", "Reste ancré dans le passage"],
        )
    topic = topic_ref or _fallback_topic_from_paragraph(paragraph) or ("this passage" if english else "ce passage")
    if english:
        return (
            "open",
            f"Reformulate in your own words what the passage says about {topic}.",
            "Reformulate the central idea without copying the text.",
            ["Reformulates the central idea", "Stays faithful to the passage"],
        )
    return (
        "open",
        f"Reformule avec tes propres mots ce que le passage affirme sur {topic}.",
        "Il faut reformuler l'idée centrale sans copier le texte.",
        ["Reformule l'idée centrale", "Reste fidèle au passage"],
    )


def _looks_like_math(paragraph: str) -> bool:
    text = paragraph or ""
    if "$" in text or "\\" in text:
        if re.search(r"\\(?:sim|ln|sin|cos|tan|frac|sqrt|sum|int|lim|to|rightarrow)\b", text):
            return True
        if "$" in text:
            return True
    if re.search(r"[=<>≤≥≠≈∞∑∫√]", text):
        return True
    if re.search(r"\b[A-Za-z]\s*[_^]\s*\{?[A-Za-z0-9]", text):
        return True
    if re.search(r"\d+(?:[.,]\d+)?\s*[+*/−-]\s*\d+(?:[.,]\d+)?", text):
        return True
    return False


def _extract_first_question(paragraph: str) -> str:
    match = re.search(r"([^.!?]{8,220}\?)", paragraph or "")
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def _fallback_topic_from_paragraph(paragraph: str) -> str:
    text = _clean_paragraph_for_topic(paragraph)
    candidates: list[str] = []
    patterns = (
        r"\b\d+D\s+U-?Net\b",
        r"\bU-?Net\b",
        r"\b[A-Z]{2,}(?:[- ][A-Z0-9]{2,})*\b",
        r"\b[A-Z][A-Za-z0-9]+(?:[- ][A-Z][A-Za-z0-9]+)+\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            candidate = re.sub(r"\s+", " ", match.group(0)).strip()
            if _usable_topic(candidate) and candidate not in candidates:
                candidates.append(candidate)
    if candidates:
        return candidates[0]

    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9'’-]{3,}", text)
    meaningful: list[str] = []
    for word in words:
        token = _topic_token(word)
        if token and token not in _FALLBACK_TOPIC_STOPWORDS:
            meaningful.append(word.strip("’'-.;,"))
        if len(meaningful) >= 3:
            break
    return " ".join(meaningful)


def _clean_paragraph_for_topic(paragraph: str) -> str:
    text = paragraph or ""
    text = re.sub(r"\[(?:Tableau|Table|Figure|Formule|Formula)[^\]:]*:\s*([^\]]+)\]", r" \1 ", text, flags=re.IGNORECASE)
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = re.sub(r"\$.*?\$", " ", text)
    text = re.sub(r"\|", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _usable_topic(candidate: str) -> bool:
    token = _topic_token(candidate)
    if len(token) < 3:
        return False
    if token in _FALLBACK_TOPIC_STOPWORDS:
        return False
    return not token.isdigit()


def _topic_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")


_FALLBACK_TOPIC_STOPWORDS = {
    "about",
    "after",
    "also",
    "avec",
    "been",
    "cette",
    "dans",
    "des",
    "does",
    "dont",
    "elle",
    "entre",
    "figure",
    "from",
    "have",
    "into",
    "leur",
    "more",
    "pour",
    "présente",
    "present",
    "results",
    "sans",
    "sont",
    "sur",
    "table",
    "tableau",
    "that",
    "the",
    "this",
    "une",
    "using",
    "with",
}


def _fallback_evaluation_from_prompt(prompt: str) -> dict | None:
    user_answer = _extract_prompt_section(prompt, "Réponse de l'étudiant")
    normalized_answer = re.sub(r"\s+", " ", user_answer).strip()
    if not normalized_answer:
        verdict = "incorrect"
        feedback = "Je n'ai pas reçu de réponse exploitable pour valider ce point."
        hint = "Repars de la phrase principale du paragraphe et reformule-la avec tes mots."
        completion = ""
    elif len(normalized_answer) < 24:
        verdict = "partial"
        feedback = "Ta réponse donne une piste, mais elle reste trop courte pour être validée finement."
        completion = "Ajoute l'idée principale du paragraphe et les notations utiles."
        hint = ""
    else:
        verdict = "partial"
        feedback = (
            "Je n'ai pas pu analyser automatiquement la réponse, mais elle contient assez "
            "d'éléments pour continuer avec prudence."
        )
        completion = "Vérifie que ta réponse reprend bien l'idée attendue du paragraphe."
        hint = ""

    return parse_evaluation({
        "verdict": verdict,
        "feedback": feedback,
        "completion": completion,
        "hint": hint,
        "metacog_signals": {
            "context_comprehension": 0.0,
            "creativity": 0.0,
            "attention": 0.0,
            "retention": 0.0,
            "curiosity": 0.0,
            "meta_cognition": 0.0,
        },
        "curiosity_signals": {},
        "creativity_signals": {},
        "answer_to_user_question": None,
        "flashcard": None,
    })


def _fallback_follow_up_from_prompt(prompt: str) -> dict | None:
    paragraph = re.sub(r"\s+", " ", _extract_prompt_section(prompt, "Paragraphe source")).strip()
    user_question = re.sub(r"\s+", " ", _extract_prompt_section(prompt, "Question de l'étudiant")).strip()
    topic = _fallback_topic_from_paragraph(paragraph)
    if paragraph:
        focus = f" sur {topic}" if topic else ""
        answer = (
            f"Le passage permet surtout de revenir au point central{focus}. "
            "Pour avancer, relis la phrase qui porte la définition, la relation ou l'exemple, "
            "puis reformule-la avec tes propres mots."
        )
    else:
        answer = (
            "Je n'ai pas assez de contexte exploitable pour répondre finement. "
            "Repars de la notion mentionnée dans ta question et formule ce que tu sais déjà, "
            "puis isole le point précis qui bloque."
        )
    if user_question:
        answer += f" Ta question était : « {user_question[:180]} »."
    return parse_follow_up({
        "answer": answer,
        "metacog_signals": {"curiosity": 1.0},
        "curiosity_signals": {"asked_follow_up_question": True},
    })


def _fallback_rephrasing_from_prompt(prompt: str) -> dict | None:
    paragraph = _extract_prompt_section(prompt, "Paragraphe original")
    paragraph = re.sub(r"\s+", " ", paragraph).strip()
    if not paragraph:
        return None
    return parse_rephrasing({
        "rephrasing_angle": "reformulation locale",
        "rephrased_paragraph": paragraph,
        "note": "Reprends le passage lentement et repère le mot ou la notation qui porte l'idée principale.",
    })


def _fallback_session_summary_from_prompt(prompt: str) -> dict | None:
    data = _extract_prompt_json(prompt, "Données de session") or {}
    if not isinstance(data, dict):
        data = {}
    duration = _safe_int(data.get("duration_s", data.get("duration", 0)))
    paragraphs = _safe_int(data.get("paragraphs_read", data.get("paragraphs", 0)))
    flashcards = _safe_int(data.get("flashcards_created", data.get("flashcards", 0)))
    rephrasings = _safe_int(data.get("rephrasings_count", data.get("rephrasings", 0)))
    success_rate = _safe_float(data.get("success_rate", data.get("successRate", 0.0)))
    if success_rate > 1.0:
        success_rate = success_rate / 100.0
    return parse_session_summary({
        "session_summary": {
            "duration_s": max(0, duration),
            "paragraphs_read": max(0, paragraphs),
            "flashcards_created": max(0, flashcards),
            "rephrasings_count": max(0, rephrasings),
            "success_rate": max(0.0, min(1.0, success_rate)),
            "qualitative_summary": "Session résumée localement : les indicateurs principaux ont été conservés.",
            "metacognitive_questions": _fallback_meta_questions(seed=data.get("session_id")),
        }
    })


def _fallback_meta_cognition_questions_from_prompt(prompt: str) -> dict | None:
    previous = _extract_prompt_json(prompt, "Questions déjà posées récemment")
    session_summary = _extract_prompt_json(prompt, "Résumé de session")
    seed = session_summary.get("session_id") if isinstance(session_summary, dict) else None
    questions = _fallback_meta_questions(
        previous_questions=previous if isinstance(previous, list) else [],
        seed=seed,
    )
    return parse_meta_cognition_questions({"questions": questions})


def _fallback_meta_cognition_analysis_from_prompt(prompt: str) -> dict | None:
    from metacog.reflection import fallback_meta_cognition_analysis

    questions = _extract_prompt_json(prompt, "Questions")
    answers = _extract_prompt_json(prompt, "Réponses de l'utilisateur")
    context = _extract_prompt_json(prompt, "Contexte de session")
    profile = _extract_prompt_json(prompt, "Profil utilisateur")
    analysis = fallback_meta_cognition_analysis(
        questions if isinstance(questions, list) else [],
        answers if isinstance(answers, list) else [],
        context if isinstance(context, dict) else {},
        profile if isinstance(profile, dict) else {},
    )
    return parse_meta_cognition_analysis(analysis)


def _fallback_flashcard_tags_from_prompt(prompt: str) -> dict | None:
    from utils.tags import fallback_flashcard_tags

    front = _extract_prompt_section(prompt, "Recto")
    back = _extract_prompt_section(prompt, "Verso")
    existing_tags = _extract_prompt_json(prompt, "Tags existants")
    existing_sections = _extract_prompt_json(prompt, "Sections existantes")
    tags = fallback_flashcard_tags(
        front,
        back,
        existing_tags=existing_tags if isinstance(existing_tags, list) else [],
        existing_sections=existing_sections if isinstance(existing_sections, list) else [],
    )
    for default_tag in ("memoire", "revision"):
        if len(tags) >= 2:
            break
        if default_tag not in tags:
            tags.append(default_tag)
    return parse_flashcard_tags({"tags": tags})


def _fallback_chapter_summary_from_prompt(prompt: str) -> dict | None:
    title = _extract_line_after_prefix(prompt, "Chapitre :") or "Chapitre"
    items = _extract_prompt_json(prompt, "Éléments lus dans le chapitre")
    overview = _fallback_overview_from_items(items)
    return parse_chapter_summary({
        "chapter_summary": {
            "title": title.strip() or "Chapitre",
            "overview": overview,
            "recap_qa": [
                {
                    "question": "Quelle est l'idée principale à retenir ?",
                    "answer": overview,
                },
                {
                    "question": "Quel élément du chapitre dois-tu pouvoir réexpliquer ?",
                    "answer": "La notion centrale, avec ses conditions ou notations importantes.",
                },
                {
                    "question": "Quel point vérifier avant de continuer ?",
                    "answer": "Vérifier que les définitions et relations utilisées sont comprises.",
                },
            ],
        }
    })


def _fallback_curiosity_hook_from_prompt(prompt: str) -> dict | None:
    chapter = _extract_line_after_prefix(prompt, "- Chapitre :") or _extract_line_after_prefix(prompt, "Chapitre :")
    subchapter = _extract_line_after_prefix(prompt, "- Sous-chapitre :")
    target = subchapter or chapter or "ce passage"
    return parse_curiosity_hook({
        "curiosity_hook": f"Entre dans {target} en cherchant le lien entre l'idée principale et un exemple concret.",
        "tone": "concrete",
        "link_with_chapter": chapter or target,
        "estimated_accessibility": 0.7,
    })


def _fallback_quiz_analysis_from_prompt(prompt: str) -> dict | None:
    history = _extract_prompt_json(prompt, "Historique des réponses")
    weak_subjects: list[str] = []
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict):
                continue
            correct = item.get("correct")
            verdict = str(item.get("verdict", item.get("result", ""))).lower()
            is_wrong = correct is False or verdict in {"incorrect", "wrong", "faux"}
            subject = str(item.get("subject", item.get("category", ""))).strip()
            if is_wrong and subject and subject not in weak_subjects:
                weak_subjects.append(subject)
    courses = [
        {
            "title": subject,
            "subject": subject,
            "reason": "Des erreurs récentes indiquent que ce thème mérite une reprise ciblée.",
        }
        for subject in weak_subjects[:3]
    ]
    analysis = (
        "Analyse locale : reprends en priorité les thèmes associés aux réponses incorrectes."
        if weak_subjects
        else "Analyse locale : aucune faiblesse nette n'a été isolée dans l'historique disponible."
    )
    return parse_quiz_session_analysis({
        "analysis": analysis,
        "weak_subjects": weak_subjects,
        "courses_to_review": courses,
    })


def _fallback_math_render_from_prompt(prompt: str) -> dict | None:
    text = _extract_prompt_section(prompt, "Texte brut extrait")
    text = text.strip()
    if not text:
        return None
    return parse_latex_paragraph_render({"rendered": text})


def _fallback_document_digest_from_prompt(prompt: str) -> dict | None:
    """Fiche de document sans LLM (Ollama éteint ou sortie inexploitable).

    Ni le rangement ni la recherche ne doivent dépendre d'Ollama : on retombe sur
    la matière heuristique, la première phrase utile de l'extrait comme résumé,
    et des mots-clés tirés du titre puis de l'extrait.
    """
    from utils.tags import fallback_document_keywords

    doc_title = (
        _extract_line_after_prefix(prompt, "Titre du document :")
        or _extract_line_after_prefix(prompt, "Document title:")
    )
    excerpt = (
        _extract_prompt_section(prompt, "Début du document")
        or _extract_prompt_section(prompt, "Beginning of the document")
    )
    return parse_document_digest({
        "subject": _heuristic_subject(f"{doc_title}\n{excerpt}"),
        "summary": _heuristic_document_summary(excerpt),
        "keywords": fallback_document_keywords(doc_title, excerpt),
    })


def _heuristic_document_summary(excerpt: str) -> str:
    """Première phrase substantielle de l'extrait — descriptif, jamais inventé.

    Une page de garde donne souvent une ligne parfaitement parlante. Si rien ne
    dépasse 40 caractères, on renvoie "" : le ruban se replie côté interface
    plutôt que d'afficher une bouillie.
    """
    text = " ".join((excerpt or "").split())
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        candidate = sentence.strip(" -–—•")
        if len(candidate) >= 40:
            return candidate
    return text if len(text) >= 40 else ""


def _fallback_meta_questions(previous_questions: list[str] | None = None, seed=None) -> list[str]:
    from metacog.reflection import normalize_meta_cognition_questions

    return normalize_meta_cognition_questions([], previous_questions=previous_questions or [], seed_context=seed)


def _extract_prompt_section(prompt: str, title: str) -> str:
    marker, start = _find_prompt_marker(prompt, title)
    if start == -1:
        return ""
    body = prompt[start + len(marker):]
    fence_start = body.find("---")
    if fence_start == -1:
        return body[:800]
    body = body[fence_start + 3:]
    fence_end = body.find("---")
    return body[:fence_end if fence_end != -1 else 800]


def _extract_prompt_json(prompt: str, title: str):
    marker, start = _find_prompt_marker(prompt, title)
    if start == -1:
        return None
    return _extract_first_json_value(prompt[start + len(marker):])


def _find_prompt_marker(prompt: str, title: str) -> tuple[str, int]:
    for marker in (f"{title} :", f"{title}:"):
        start = (prompt or "").find(marker)
        if start != -1:
            return marker, start
    return "", -1


def _extract_first_json_value(text: str):
    for start, char in enumerate(text or ""):
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
                    candidate = text[start:index + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        return None
    return None


def _extract_line_after_prefix(prompt: str, prefix: str) -> str:
    for line in (prompt or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return ""


def _fallback_overview_from_items(items) -> str:
    snippets: list[str] = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                text = item.get("summary") or item.get("text") or item.get("paragraph") or item.get("content")
            else:
                text = item
            clean = re.sub(r"\s+", " ", str(text or "")).strip()
            if clean:
                snippets.append(clean)
            if len(" ".join(snippets)) >= 220:
                break
    elif isinstance(items, dict):
        for key in ("summary", "overview", "text", "content"):
            if items.get(key):
                snippets.append(re.sub(r"\s+", " ", str(items[key])).strip())
                break
    overview = " ".join(snippets).strip()
    if overview:
        return overview[:420]
    return "Le chapitre contient plusieurs notions à reprendre progressivement."


def _safe_int(value) -> int:
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return 0


def _safe_float(value) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _heuristic_subject(text: str) -> str:
    lower = (text or "").lower()
    # Ordre : du plus spécifique au plus générique (la 1re correspondance gagne).
    if re.search(r"\b(math|suite|fonction|équation|equation|théorème|theoreme|dérivée|derivee|intégrale|integrale|matrice|algèbre|algebre|géométrie|geometrie)\b", lower):
        return "mathématiques"
    if re.search(r"\b(physique|mécanique|mecanique|électron|electron|quantique|relativité|relativite|newton|onde|force|champ magnétique|magnetique)\b", lower):
        return "physique"
    if re.search(r"\b(chimie|molécule|molecule|atome|réaction|reaction|acide|base|ion|liaison|chimique|oxyd)\b", lower):
        return "chimie"
    if re.search(r"\b(biologie|cellule|adn|gène|gene|cellulaire|enzyme|organisme|évolution|evolution|écosystème|ecosysteme|protéine|proteine)\b", lower):
        return "biologie"
    if re.search(r"\b(programmation|algorithme|algorithm|python|software|logiciel|donnée|donnee|réseau|reseau|network|informatique|informatics|computing|machine learning|base de données|code source)\b", lower):
        return "informatique"
    if re.search(r"\b(ingénierie|ingenierie|engineering|technologie|technique|circuit|moteur|conception|fabrication|matériau|materiau)\b", lower):
        return "technologie"
    if re.search(r"\b(médecine|medecine|anatomie|pathologie|symptôme|symptome|diagnostic|clinique|maladie|santé|sante|physiologie)\b", lower):
        return "médecine"
    if re.search(r"\b(droit|juridique|loi|législation|legislation|tribunal|contrat|jurisprudence|constitution|code civil|pénal|penal)\b", lower):
        return "droit"
    if re.search(r"\b(économie|economie|economics|marché|marche|inflation|pib|gdp|monnaie|offre|demande|macroéconomie|macroeconomie)\b", lower):
        return "économie"
    if re.search(r"\b(gestion|management|comptabilité|comptabilite|entreprise|marketing|finance|stratégie|strategie|ressources humaines)\b", lower):
        return "gestion"
    if re.search(r"\b(psychologie|psychology|cognition|comportement|émotion|emotion|inconscient|freud|mémoire|memoire|perception)\b", lower):
        return "psychologie"
    if re.search(r"\b(sociologie|sociology|société|societe|social|institution|classe sociale|durkheim|interaction)\b", lower):
        return "sociologie"
    if re.search(r"\b(philosophie|philosophy|métaphysique|metaphysique|éthique|ethique|épistémologie|epistemologie|kant|platon|conscience|morale)\b", lower):
        return "philosophie"
    if re.search(r"\b(guerre|siècle|siecle|empire|révolution|revolution|histoire|history|war|century|antiquité|antiquite|moyen âge|moyen age)\b", lower):
        return "histoire"
    if re.search(r"\b(carte|relief|climat|climate|territoire|continent|géographie|geographie|geography|population|urbanisation)\b", lower):
        return "géographie"
    if re.search(r"\b(littérature|litterature|roman|poésie|poesie|récit|recit|narration|auteur|œuvre|oeuvre|fiction)\b", lower):
        return "littérature"
    if re.search(r"\b(grammaire|conjugaison|orthographe|texte|français|francais|vocabulaire|syntaxe|dictée|dictee)\b", lower):
        return "français"
    if re.search(r"\b(langue|anglais|english|espagnol|allemand|italien|traduction|vocabulary|grammar)\b", lower):
        return "langues"
    if re.search(r"\b(art|peinture|sculpture|dessin|architecture|esthétique|esthetique|artiste|tableau)\b", lower):
        return "arts"
    if re.search(r"\b(musique|music|harmonie|mélodie|melodie|rythme|partition|instrument|note de musique|gamme)\b", lower):
        return "musique"
    if re.search(r"\b(sport|eps|entraînement|entrainement|athlète|athlete|musculaire|exercice physique|compétition|competition)\b", lower):
        return "sport"
    if re.search(r"\b(religion|théologie|theologie|spiritualité|spiritualite|bible|coran|dieu|sacré|sacre|croyance)\b", lower):
        return "religion"
    if re.search(r"\b(sciences?|expérience|experience|énergie|energie|laboratoire|hypothèse|hypothese)\b", lower):
        return "sciences"
    return "culture"


def _call_ollama(prompt: str, model: str, images: list[str] | None = None, options: dict | None = None, format_json: bool = True, task: str = "") -> str:
    """Point d'étranglement de TOUTES les générations synchrones : délègue au
    fournisseur actif (services/llm_provider — Ollama local). `task` = label de
    la tâche (observabilité locale, jamais de contenu)."""
    from services.llm_provider import generate

    return generate(prompt, model=model, images=images, options=options, format_json=format_json, task=task)


def _call_ollama_http(prompt: str, model: str, images: list[str] | None = None, options: dict | None = None, format_json: bool = True, task: str = "") -> str:
    """Implémentation HTTP brute vers Ollama local (appelée par llm_provider).

    Le timeout socket est dérivé du budget de `task` (`settings.task_timeout_s`) :
    une tâche qui demande 3000 tokens ne peut pas tenir dans le budget d'une qui
    en demande 160."""
    payload_data = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": options if options is not None else OLLAMA_OPTIONS,
        "keep_alive": OLLAMA_KEEP_ALIVE,
    }
    if format_json:
        payload_data["format"] = "json"

    if images:
        payload_data["images"] = images

    payload = json.dumps(payload_data).encode()

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=task_timeout_s(task)) as resp:
            data = json.loads(resp.read())
            if "error" in data:
                raise RuntimeError(f"Ollama error: {data['error']}")
            response = data.get("response", "")

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama indisponible: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Réponse Ollama invalide: {exc}") from exc

    if not isinstance(response, str) or not response.strip():
        raise ValueError("Réponse Ollama vide")

    return response


# ── Module langue — fonctions async ──────────────────────────────────────────

def generate_lang_curriculum_async(
    language: str,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    from llm.prompts import build_lang_curriculum_prompt
    from llm.schema_json import parse_lang_curriculum
    prompt = build_lang_curriculum_prompt(language)
    return _run_json_async(
        "lang_curriculum", prompt, parse_lang_curriculum, on_success, on_error, model
    )


def generate_lang_curiosity_async(
    language: str,
    lesson_n: int,
    theme: str,
    grammar_point: str,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    from llm.prompts import build_lang_curiosity_prompt
    from llm.schema_json import parse_lang_curiosity
    prompt = build_lang_curiosity_prompt(language, lesson_n, theme, grammar_point)
    return _run_json_async(
        "lang_curiosity", prompt, parse_lang_curiosity, on_success, on_error, model
    )


def generate_lang_lesson_async(
    language: str,
    lesson_n: int,
    curriculum_row: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    from llm.prompts import build_lang_lesson_prompt
    from llm.schema_json import parse_lang_lesson
    prompt = build_lang_lesson_prompt(language, lesson_n, curriculum_row)
    return _run_json_async(
        "lang_lesson", prompt, parse_lang_lesson, on_success, on_error, model
    )


def generate_lang_exercises_async(
    language: str,
    lesson_n: int,
    dialogue: list,
    vocabulary: list,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    from llm.prompts import build_lang_exercises_prompt
    from llm.schema_json import parse_lang_exercises
    prompt = build_lang_exercises_prompt(language, lesson_n, dialogue, vocabulary)
    return _run_json_async(
        "lang_exercises", prompt, parse_lang_exercises, on_success, on_error, model
    )


def generate_lang_correction_async(
    language: str,
    target_phrase: str,
    user_attempt: str,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    from llm.prompts import build_lang_correction_prompt
    from llm.schema_json import parse_lang_correction
    prompt = build_lang_correction_prompt(language, target_phrase, user_attempt)
    return _run_json_async(
        "lang_correction", prompt, parse_lang_correction, on_success, on_error, model
    )


def generate_lang_revision_quiz_async(
    language: str,
    errors: list,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    from llm.prompts import build_lang_revision_quiz_prompt
    from llm.schema_json import parse_lang_revision_quiz
    prompt = build_lang_revision_quiz_prompt(language, errors)
    return _run_json_async(
        "lang_revision_quiz", prompt, parse_lang_revision_quiz, on_success, on_error, model
    )


# ── Séquenceur adaptatif : choix de type (léger) + contenu (paramétré par type) ──

_RENDER_KIND_TASK_LABEL: dict[str, str] = {
    "dialogue": "lang_content_dialogue",
    "reading": "lang_content_reading",
    "vocabulary": "lang_content_vocab",
    "phonetics": "lang_content_phonetics",
    "translation": "lang_content_translation",
    "dictation": "lang_content_dictation",
    "production": "lang_content_production",
    "writing": "lang_content_writing",
    "cloze": "lang_content_cloze",
    "ordering": "lang_content_ordering",
    "matching": "lang_content_matching",
    "transform": "lang_content_transform",
}


def plan_lesson_async(
    state: dict,
    level: str,
    language: str,
    phase: str,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    """Appel court : propose le THÈME d'une séance (l'arc des 10 slots est construit côté code)."""
    from llm.prompts import build_lang_lesson_plan_prompt
    from llm.schema_json import parse_lesson_plan
    prompt = build_lang_lesson_plan_prompt(state, level, language, phase)
    return _run_json_async(
        "lang_lesson_plan", prompt, parse_lesson_plan, on_success, on_error, model
    )


def generate_placement_test_async(
    language: str,
    script: str,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    """Génère un test de niveau complet (~15-20 items de difficulté croissante)."""
    from llm.prompts import build_lang_placement_prompt
    from llm.schema_json import parse_placement_test
    prompt = build_lang_placement_prompt(language, script)
    return _run_json_async(
        "lang_placement", prompt, parse_placement_test, on_success, on_error, model
    )


def evaluate_placement_async(
    language: str,
    summary: str,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    """Estime le niveau CEFR d'entrée à partir d'un résumé des réponses au test."""
    from llm.prompts import build_lang_placement_eval_prompt
    from llm.schema_json import parse_placement_eval
    prompt = build_lang_placement_eval_prompt(language, summary)
    return _run_json_async(
        "lang_placement_eval", prompt, parse_placement_eval, on_success, on_error, model
    )


def choose_session_type_async(
    state: dict,
    available: list,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    """Appel court : choisit le TYPE de la prochaine session (JSON de 2 champs)."""
    from llm.prompts import build_lang_session_select_prompt
    from llm.schema_json import parse_session_choice
    prompt = build_lang_session_select_prompt(state, available)
    return _run_json_async(
        "lang_session_select", prompt, parse_session_choice, on_success, on_error, model
    )


def generate_session_content_async(
    language: str,
    session_type: str,
    profile: dict,
    weak_points,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
    due_cards=None,
) -> None:
    """Génère le contenu d'UNE session, scope réduit, dispatché par render_kind.

    Réinjecte session_type/render_kind/label/kind dans le contenu renvoyé pour
    que le frontend sache quel composant de rendu utiliser. `due_cards` (cartes SR
    dues) alimente le quiz de révision en plus des erreurs (pont SR → séance).
    """
    from db.lang_db import SESSION_TYPE_RENDER_KIND, SESSION_TYPE_LABEL
    from llm.prompts import LANG_SESSION_PROMPT_BUILDERS
    from llm.schema_json import LANG_CONTENT_PARSERS

    render_kind = SESSION_TYPE_RENDER_KIND.get(session_type, "dialogue")
    label_human = SESSION_TYPE_LABEL.get(session_type, session_type)

    def _wrapped_ok(content):
        if isinstance(content, dict):
            content.setdefault("kind", render_kind)
            content["session_type"] = session_type
            content["render_kind"] = render_kind
            content["label"] = label_human
        on_success(content)

    # Révision : réutilise le pipeline de quiz de révision (alimenté par les erreurs
    # passées ET les cartes SR dues — pont SR → séance, 2e vague Assimil).
    if render_kind == "revision":
        from llm.prompts import build_lang_revision_quiz_prompt
        from llm.schema_json import parse_session_revision
        prompt = build_lang_revision_quiz_prompt(language, weak_points or [], due_cards or [])
        return _run_json_async(
            "lang_revision_quiz", prompt, parse_session_revision, _wrapped_ok, on_error, model
        )

    builder = LANG_SESSION_PROMPT_BUILDERS.get(session_type)
    parser = LANG_CONTENT_PARSERS.get(render_kind)
    if builder is None or parser is None:
        on_error(f"type de session inconnu : {session_type}")
        return
    prompt = builder(language, profile, weak_points or [])
    task_label = _RENDER_KIND_TASK_LABEL.get(render_kind, "lang_content_dialogue")
    return _run_json_async(task_label, prompt, parser, _wrapped_ok, on_error, model)


def _load_ollama_images(image_paths: list[str]) -> list[str]:
    images: list[str] = []
    for raw_path in image_paths[:4]:
        try:
            path = Path(str(raw_path)).expanduser()
            if not path.exists() or not path.is_file():
                logger.debug("Image LLM ignorée, fichier absent: %s", path)
                continue
            images.append(base64.b64encode(path.read_bytes()).decode("ascii"))
        except Exception as exc:
            logger.debug("Image LLM ignorée %s: %s", raw_path, exc)
    return images


# ── Brainstorming — chat libre + RAG sur la base utilisateur ──────────────────

def decide_brainstorm_search_async(
    history: list[dict],
    user_message: str,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    """Décide s'il faut fouiller la base de l'utilisateur (JSON court {search, queries})."""
    from llm.prompts import build_brainstorm_search_decide_prompt
    from llm.schema_json import parse_brainstorm_search_decision
    prompt = build_brainstorm_search_decide_prompt(history, user_message)
    return _run_json_async(
        "brainstorm_search_decide", prompt, parse_brainstorm_search_decision,
        on_success, on_error, model,
    )


def answer_brainstorm_async(
    context: dict,
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    """Réponse conversationnelle (texte libre) avec mémoire de la discussion + sources DB."""
    from llm.prompts import build_brainstorm_answer_prompt
    prompt = build_brainstorm_answer_prompt(
        summary=context.get("summary") or "",
        history=context.get("history") or [],
        user_message=context.get("user_message") or "",
        sources=context.get("sources") or [],
    )
    return _run_text_async("brainstorm_answer", prompt, on_success, on_error, model)


def summarize_brainstorm_async(
    previous_summary: str,
    new_messages: list[dict],
    on_success,
    on_error,
    model: str = OLLAMA_MODEL,
) -> None:
    """Met à jour le résumé glissant d'une discussion (mémoire longue compactée)."""
    from llm.prompts import build_brainstorm_summary_prompt
    prompt = build_brainstorm_summary_prompt(previous_summary, new_messages)
    return _run_text_async("brainstorm_summary", prompt, on_success, on_error, model)
