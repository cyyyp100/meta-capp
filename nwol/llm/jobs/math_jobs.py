"""llm/jobs/math_jobs.py — Typed JobSpec factories for math/render/QA/session jobs.

These jobs are generation-scoped to the active reader session.  Cancelling the
session (new document, chapter skip) invalidates all pending jobs in this
family.

Priority ladder (lower = higher priority):
  0  math_render / math_stream   — inline math rendering for visible paragraph
  1  schema / table / slide      — image descriptions for visible block
  2  question                    — Q&A for completed section
  3  follow_up                   — follow-up answer
  4  evaluation                  — user answer evaluation
  5  rephrasing                  — paragraph rephrasing
  6  curiosity_hook              — chapter hook
  7  session-level background     — summaries, metacog, subject detection, etc.
  8  lang module                 — language lesson generation
"""

from __future__ import annotations

from typing import Any, Callable

from llm.jobs.types import JobSpec

# ---------------------------------------------------------------------------
# Priority constants
# ---------------------------------------------------------------------------

MATH_PRIORITY_RENDER: int = 0       # math_render, math_stream
MATH_PRIORITY_VISUAL: int = 1       # schema, table, slide descriptions
MATH_PRIORITY_QUESTION: int = 2
MATH_PRIORITY_FOLLOW_UP: int = 3
MATH_PRIORITY_EVALUATION: int = 4
MATH_PRIORITY_REPHRASING: int = 5
MATH_PRIORITY_HOOK: int = 6
MATH_PRIORITY_SESSION: int = 7      # summaries, metacog, quiz, flashcards
MATH_PRIORITY_LANG: int = 8         # language module jobs


# ---------------------------------------------------------------------------
# Render and visual description spec factories
# ---------------------------------------------------------------------------

def make_math_render_spec(
    fn: Callable[[], Any],
    *,
    generation: int,
    block_id: str = "",
    streaming: bool = False,
    timeout: float | None = None,
) -> JobSpec:
    """Return a JobSpec for inline math paragraph rendering (LLM clean-up)."""
    kind = "math_stream" if streaming else "math_render"
    return JobSpec(
        kind=kind,
        fn=fn,
        generation=generation,
        priority=MATH_PRIORITY_RENDER,
        timeout=timeout,
        metadata={"block_id": block_id, "streaming": streaming},
    )


def make_schema_spec(
    fn: Callable[[], Any],
    *,
    generation: int,
    image_path: str = "",
    timeout: float | None = None,
) -> JobSpec:
    """Return a JobSpec for schema/diagram image description."""
    return JobSpec(
        kind="schema_description",
        fn=fn,
        generation=generation,
        priority=MATH_PRIORITY_VISUAL,
        timeout=timeout,
        metadata={"image_path": image_path},
    )


def make_table_spec(
    fn: Callable[[], Any],
    *,
    generation: int,
    image_path: str = "",
    timeout: float | None = None,
) -> JobSpec:
    """Return a JobSpec for table image description."""
    return JobSpec(
        kind="table_description",
        fn=fn,
        generation=generation,
        priority=MATH_PRIORITY_VISUAL,
        timeout=timeout,
        metadata={"image_path": image_path},
    )


def make_slide_spec(
    fn: Callable[[], Any],
    *,
    generation: int,
    image_path: str = "",
    timeout: float | None = None,
) -> JobSpec:
    """Return a JobSpec for slide image description."""
    return JobSpec(
        kind="slide_description",
        fn=fn,
        generation=generation,
        priority=MATH_PRIORITY_VISUAL,
        timeout=timeout,
        metadata={"image_path": image_path},
    )


# ---------------------------------------------------------------------------
# Q&A spec factories
# ---------------------------------------------------------------------------

def make_question_spec(
    fn: Callable[[], Any],
    *,
    generation: int,
    block_id: str = "",
    timeout: float | None = None,
) -> JobSpec:
    """Return a JobSpec for section Q&A question generation."""
    return JobSpec(
        kind="question",
        fn=fn,
        generation=generation,
        priority=MATH_PRIORITY_QUESTION,
        timeout=timeout,
        metadata={"block_id": block_id},
    )


def make_follow_up_spec(
    fn: Callable[[], Any],
    *,
    generation: int,
    timeout: float | None = None,
) -> JobSpec:
    """Return a JobSpec for follow-up answer generation."""
    return JobSpec(
        kind="follow_up",
        fn=fn,
        generation=generation,
        priority=MATH_PRIORITY_FOLLOW_UP,
        timeout=timeout,
        metadata={},
    )


def make_evaluation_spec(
    fn: Callable[[], Any],
    *,
    generation: int,
    timeout: float | None = None,
) -> JobSpec:
    """Return a JobSpec for user answer evaluation."""
    return JobSpec(
        kind="evaluation",
        fn=fn,
        generation=generation,
        priority=MATH_PRIORITY_EVALUATION,
        timeout=timeout,
        metadata={},
    )


def make_rephrasing_spec(
    fn: Callable[[], Any],
    *,
    generation: int,
    block_id: str = "",
    timeout: float | None = None,
) -> JobSpec:
    """Return a JobSpec for paragraph rephrasing."""
    return JobSpec(
        kind="rephrasing",
        fn=fn,
        generation=generation,
        priority=MATH_PRIORITY_REPHRASING,
        timeout=timeout,
        metadata={"block_id": block_id},
    )


def make_curiosity_hook_spec(
    fn: Callable[[], Any],
    *,
    generation: int,
    timeout: float | None = None,
) -> JobSpec:
    """Return a JobSpec for chapter curiosity hook generation."""
    return JobSpec(
        kind="curiosity_hook",
        fn=fn,
        generation=generation,
        priority=MATH_PRIORITY_HOOK,
        timeout=timeout,
        metadata={},
    )


# ---------------------------------------------------------------------------
# Session-level spec factories
# ---------------------------------------------------------------------------

def make_session_spec(
    fn: Callable[[], Any],
    *,
    kind: str,
    generation: int,
    timeout: float | None = None,
) -> JobSpec:
    """Return a JobSpec for a background session-level job.

    *kind* must be one of: session_summary, chapter_summary,
    meta_cognition_questions, meta_cognition_analysis, quiz_analysis,
    flashcard_tags, subject_detection.
    """
    _SESSION_KINDS = {
        "session_summary",
        "chapter_summary",
        "meta_cognition_questions",
        "meta_cognition_analysis",
        "quiz_analysis",
        "flashcard_tags",
        "subject_detection",
    }
    if kind not in _SESSION_KINDS:
        raise ValueError(f"make_session_spec: unknown kind '{kind}', expected one of {sorted(_SESSION_KINDS)}")
    return JobSpec(
        kind=kind,
        fn=fn,
        generation=generation,
        priority=MATH_PRIORITY_SESSION,
        timeout=timeout,
        metadata={},
    )


# ---------------------------------------------------------------------------
# Language module spec factories
# ---------------------------------------------------------------------------

def make_lang_spec(
    fn: Callable[[], Any],
    *,
    kind: str,
    generation: int,
    timeout: float | None = None,
) -> JobSpec:
    """Return a JobSpec for a language module job.

    *kind* must be one of: lang_curriculum, lang_curiosity, lang_lesson,
    lang_exercises, lang_correction, lang_revision_quiz.
    """
    _LANG_KINDS = {
        "lang_curriculum",
        "lang_curiosity",
        "lang_lesson",
        "lang_exercises",
        "lang_correction",
        "lang_revision_quiz",
    }
    if kind not in _LANG_KINDS:
        raise ValueError(f"make_lang_spec: unknown kind '{kind}', expected one of {sorted(_LANG_KINDS)}")
    return JobSpec(
        kind=kind,
        fn=fn,
        generation=generation,
        priority=MATH_PRIORITY_LANG,
        timeout=timeout,
        metadata={},
    )
