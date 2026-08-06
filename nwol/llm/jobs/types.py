"""llm/jobs/types.py — Typed contracts for the unified LLM job system (Phase 8).

Three public types:

  JobSpec    — immutable description of a unit of LLM work.
  JobResult  — immutable outcome of a completed or cancelled job.
  JobHandle  — lightweight receipt returned by JobQueue.submit(); supports
               polling, waiting, and pre-execution cancellation.

These types carry no queue or Ollama logic; they are pure data.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Job kind constants — string literals kept as a plain set for fast lookup.
# ---------------------------------------------------------------------------

# PDF structural jobs — generation-scoped to the current document.
PDF_JOB_KINDS: frozenset[str] = frozenset({
    "layout_order",
    "layout_crop",
    "math_repair",
})

# Render jobs — generation-scoped to the active reader session.
RENDER_JOB_KINDS: frozenset[str] = frozenset({
    "math_render",
    "math_stream",
    "schema_description",
    "table_description",
    "slide_description",
})

# QA and metacognition jobs — generation-scoped to the active reader session.
QA_JOB_KINDS: frozenset[str] = frozenset({
    "question",
    "follow_up",
    "evaluation",
    "rephrasing",
    "curiosity_hook",
})

# Session-level background jobs — not bound to page generation.
SESSION_JOB_KINDS: frozenset[str] = frozenset({
    "session_summary",
    "chapter_summary",
    "meta_cognition_questions",
    "meta_cognition_analysis",
    "quiz_analysis",
    "flashcard_tags",
    "subject_detection",
})

# Language module jobs — not bound to page generation.
LANG_JOB_KINDS: frozenset[str] = frozenset({
    "lang_curriculum",
    "lang_curiosity",
    "lang_lesson",
    "lang_exercises",
    "lang_correction",
    "lang_revision_quiz",
})

ALL_JOB_KINDS: frozenset[str] = (
    PDF_JOB_KINDS
    | RENDER_JOB_KINDS
    | QA_JOB_KINDS
    | SESSION_JOB_KINDS
    | LANG_JOB_KINDS
)


# ---------------------------------------------------------------------------
# JobSpec
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class JobSpec:
    """Describes a unit of LLM work to submit to the queue.

    *fn* is the callable executed by the worker.  It must be thread-safe and
    must not interact with Tk widgets directly.

    *generation* is the caller's generation token at submission time.  The
    queue will reject (cancel) the job if the current generation has advanced
    past this value by the time the worker picks it up.

    *priority* follows the convention of Python's PriorityQueue: lower value
    means higher priority.  Use the constants in pdf_jobs / math_jobs instead
    of raw ints.

    *timeout* is the maximum wall-clock seconds the caller is willing to block
    in submit_sync().  None means use the queue default.

    *metadata* is an optional read-only mapping used only for logging and
    diagnostics; it must not affect execution logic.
    """

    kind: str
    fn: Callable[[], Any]
    generation: int
    priority: int = 0
    timeout: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("JobSpec.kind must not be empty")
        if not callable(self.fn):
            raise TypeError("JobSpec.fn must be callable")
        if self.generation < 0:
            raise ValueError("JobSpec.generation must be >= 0")


# ---------------------------------------------------------------------------
# JobResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class JobResult:
    """Immutable outcome of a completed or cancelled job.

    *value* holds the return value of fn() on success, else None.
    *error* holds the exception raised by fn() if it threw, else None.
    *cancelled* is True when the job was skipped due to stale generation or
      an explicit handle.cancel() call before execution started.
    *generation* is the generation stored in the JobSpec at submission.
    *elapsed* is wall-clock seconds consumed by fn() execution (0.0 if
      cancelled or timed out).
    """

    value: Any
    error: BaseException | None
    cancelled: bool
    generation: int
    elapsed: float

    @property
    def ok(self) -> bool:
        """True iff the job ran to completion without error or cancellation."""
        return not self.cancelled and self.error is None


# ---------------------------------------------------------------------------
# _QueuedJob — internal queue entry
# ---------------------------------------------------------------------------

@dataclass(order=True, slots=True)
class _QueuedJob:
    priority: int
    sequence: int
    spec: JobSpec = field(compare=False)
    _cancelled: bool = field(default=False, compare=False)
    _event: threading.Event = field(default_factory=threading.Event, compare=False)
    _result: JobResult | None = field(default=None, compare=False)

    def mark_cancelled(self) -> None:
        self._cancelled = True

    def resolve(self, result: JobResult) -> None:
        self._result = result
        self._event.set()


# ---------------------------------------------------------------------------
# JobHandle
# ---------------------------------------------------------------------------

class JobHandle:
    """Receipt returned by JobQueue.submit().

    Allows the caller to:
    - poll whether the job is done (.done property),
    - block until the result is available (.wait()),
    - cancel the job before it starts executing (.cancel()).

    A handle is cheap to create and thread-safe.
    """

    __slots__ = ("_job",)

    def __init__(self, job: _QueuedJob) -> None:
        self._job = job

    # -- polling ----------------------------------------------------------------

    @property
    def done(self) -> bool:
        """True once the worker has set a result (success, error, or cancel)."""
        return self._job._event.is_set()

    @property
    def result(self) -> JobResult | None:
        """The result if done, else None.  Does not block."""
        return self._job._result if self._job._event.is_set() else None

    # -- blocking ---------------------------------------------------------------

    def wait(self, timeout: float | None = None) -> JobResult:
        """Block until the job finishes or *timeout* seconds elapse.

        If the timeout expires before the worker sets a result, returns a
        synthetic cancelled JobResult (the job itself is not cancelled; it
        may still complete and a subsequent .wait() would return the real
        result).
        """
        self._job._event.wait(timeout=timeout)
        if self._job._result is None:
            return JobResult(
                value=None,
                error=None,
                cancelled=True,
                generation=self._job.spec.generation,
                elapsed=0.0,
            )
        return self._job._result

    # -- cancellation -----------------------------------------------------------

    def cancel(self) -> None:
        """Request cancellation before execution begins.

        Has no effect if the worker has already started executing the job.
        The worker checks _cancelled at dequeue time and skips the fn() call.
        """
        self._job.mark_cancelled()


# ---------------------------------------------------------------------------
# Convenience: immediate handle for pre-rejected jobs
# ---------------------------------------------------------------------------

def _make_immediate_handle(result: JobResult) -> JobHandle:
    """Return a JobHandle that is already done with the given result."""
    job = _QueuedJob(
        priority=0,
        sequence=0,
        spec=JobSpec(kind="_immediate", fn=lambda: None, generation=result.generation),
    )
    job.resolve(result)
    return JobHandle(job)
