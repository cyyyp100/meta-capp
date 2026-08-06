"""llm/jobs/queue.py — Unified LLM job queue (Phase 8).

JobQueue is a single-worker priority queue with generation-based cancellation.
It supersedes the parallel systems in llm.pdf_assistant_queue and
llm.ollama_client._LLM_QUEUE for new callers while leaving those modules
untouched for backwards compatibility.

Key properties:

  • One daemon worker thread — all fn() calls are serialised.
  • Priority queue — lower priority value = executes first.
  • Generation tracking — every JobSpec carries a generation token captured at
    submission time.  The worker silently skips any job whose generation no
    longer matches the queue's current generation at dequeue time.
  • Explicit handle cancellation — JobHandle.cancel() marks a job before the
    worker touches it; the worker checks the flag at dequeue.
  • Timeout-triggered suspension — after a blocking submit_sync() times out the
    queue suspends itself for a configurable cooldown period and rejects
    subsequent jobs until it recovers.
  • Thread-safe — all mutable state is protected by a single lock.

Typical usage:

    queue = JobQueue()
    spec = JobSpec(kind="math_render", fn=my_callable, generation=gen)

    # Non-blocking:
    handle = queue.submit(spec)
    result = handle.wait(timeout=15.0)

    # Blocking (pipeline thread):
    result = queue.submit_sync(spec, timeout=15.0)
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import time

from llm.jobs.types import (
    JobHandle,
    JobResult,
    JobSpec,
    _QueuedJob,
    _make_immediate_handle,
)

logger = logging.getLogger("LLM.jobs.queue")

_DEFAULT_COOLDOWN = 75.0
_DEFAULT_TIMEOUT = 30.0


class JobQueue:
    """Unified single-worker LLM job queue with generation-based cancellation.

    One instance per domain is the typical usage:
        - one queue for PDF structural jobs (scoped to a document generation)
        - one queue for reader session jobs (scoped to a reading session)

    Both queues share the same scheduling mechanism but maintain independent
    generation counters so cancelling a document switch does not affect
    in-flight Q&A jobs.
    """

    def __init__(self, *, name: str = "llm-job-queue", cooldown: float = _DEFAULT_COOLDOWN) -> None:
        self._pqueue: queue.PriorityQueue[_QueuedJob] = queue.PriorityQueue()
        self._sequence = itertools.count()
        self._generation: int = 0
        self._lock = threading.Lock()
        self._suspended_until: float = 0.0
        self._cooldown = max(1.0, float(cooldown))
        self._name = name
        self._worker = threading.Thread(
            target=self._run, daemon=True, name=self._name
        )
        self._worker.start()

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    def submit(self, spec: JobSpec) -> JobHandle:
        """Enqueue *spec* and return a handle immediately.

        If the spec's generation is already stale, the job is not enqueued and
        the returned handle is immediately done with a cancelled result.
        """
        if self._is_stale(spec.generation):
            logger.debug(
                "[%s] submit skipped — stale generation spec.gen=%s current=%s kind=%s",
                self._name, spec.generation, self._current_generation(), spec.kind,
            )
            return _make_immediate_handle(
                JobResult(
                    value=None,
                    error=None,
                    cancelled=True,
                    generation=spec.generation,
                    elapsed=0.0,
                )
            )

        job = _QueuedJob(
            priority=spec.priority,
            sequence=next(self._sequence),
            spec=spec,
        )
        self._pqueue.put(job)
        logger.debug(
            "[%s] submitted kind=%s gen=%s priority=%s",
            self._name, spec.kind, spec.generation, spec.priority,
        )
        return JobHandle(job)

    def submit_sync(self, spec: JobSpec, timeout: float | None = None) -> JobResult:
        """Enqueue *spec* and block until done or *timeout* seconds elapse.

        If timeout expires before the worker sets a result, a synthetic
        cancelled result is returned and the queue enters cooldown suspension
        to avoid hammering a slow LLM backend.

        *timeout* defaults to spec.timeout, then _DEFAULT_TIMEOUT.
        """
        effective_timeout = timeout if timeout is not None else (
            spec.timeout if spec.timeout is not None else _DEFAULT_TIMEOUT
        )

        # Suspension check — fast reject if queue is cooling down.
        suspended_for = self._suspended_for()
        if suspended_for > 0.0:
            logger.info(
                "[%s] submit_sync suspended %.1fs kind=%s",
                self._name, suspended_for, spec.kind,
            )
            return JobResult(
                value=None, error=None, cancelled=True,
                generation=spec.generation, elapsed=0.0,
            )

        handle = self.submit(spec)
        if handle.done:
            return handle.result  # type: ignore[return-value]  # result is set

        started = time.monotonic()
        result = handle.wait(timeout=effective_timeout)
        elapsed = time.monotonic() - started

        if not handle.done:
            # The wait returned a synthetic timeout result — trigger cooldown.
            logger.warning(
                "[%s] submit_sync timeout after %.1fs kind=%s gen=%s",
                self._name, elapsed, spec.kind, spec.generation,
            )
            self._trigger_cooldown(spec.generation)

        return result

    # ------------------------------------------------------------------
    # Generation management
    # ------------------------------------------------------------------

    def cancel_generation(self) -> int:
        """Increment the generation counter and clear any active suspension.

        All pending jobs whose generation no longer matches will be silently
        skipped by the worker.  Returns the new generation token.
        """
        with self._lock:
            self._generation += 1
            self._suspended_until = 0.0
            new_gen = self._generation
        logger.info("[%s] generation cancelled — new token=%s", self._name, new_gen)
        return new_gen

    def current_generation(self) -> int:
        return self._current_generation()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def pending_count(self) -> int:
        """Approximate number of pending jobs (includes stale ones not yet dequeued)."""
        return self._pqueue.qsize()

    def is_suspended(self) -> bool:
        return self._suspended_for() > 0.0

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while True:
            job = self._pqueue.get()
            try:
                self._execute(job)
            finally:
                self._pqueue.task_done()

    def _execute(self, job: _QueuedJob) -> None:
        start = time.monotonic()

        # Pre-execution checks — cancel without calling fn().
        if job._cancelled:
            job.resolve(JobResult(
                value=None, error=None, cancelled=True,
                generation=job.spec.generation, elapsed=0.0,
            ))
            logger.debug("[%s] job skipped — handle cancelled kind=%s", self._name, job.spec.kind)
            return

        if self._is_stale(job.spec.generation):
            job.resolve(JobResult(
                value=None, error=None, cancelled=True,
                generation=job.spec.generation, elapsed=0.0,
            ))
            logger.debug(
                "[%s] job skipped — stale gen spec=%s current=%s kind=%s",
                self._name, job.spec.generation, self._current_generation(), job.spec.kind,
            )
            return

        suspended_for = self._suspended_for()
        if suspended_for > 0.0:
            job.resolve(JobResult(
                value=None, error=None, cancelled=True,
                generation=job.spec.generation, elapsed=0.0,
            ))
            logger.debug(
                "[%s] job skipped — queue suspended %.1fs kind=%s",
                self._name, suspended_for, job.spec.kind,
            )
            return

        # Execute fn().
        try:
            value = job.spec.fn()
            elapsed = time.monotonic() - start
            job.resolve(JobResult(
                value=value, error=None, cancelled=False,
                generation=job.spec.generation, elapsed=elapsed,
            ))
            logger.debug(
                "[%s] job done kind=%s elapsed=%.2fs", self._name, job.spec.kind, elapsed
            )
        except BaseException as exc:
            elapsed = time.monotonic() - start
            job.resolve(JobResult(
                value=None, error=exc, cancelled=False,
                generation=job.spec.generation, elapsed=elapsed,
            ))
            logger.warning(
                "[%s] job error kind=%s elapsed=%.2fs: %s",
                self._name, job.spec.kind, elapsed, exc,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_stale(self, generation: int) -> bool:
        with self._lock:
            return generation != self._generation

    def _current_generation(self) -> int:
        with self._lock:
            return self._generation

    def _suspended_for(self) -> float:
        with self._lock:
            return max(0.0, self._suspended_until - time.monotonic())

    def _trigger_cooldown(self, generation: int) -> None:
        with self._lock:
            if generation == self._generation:
                self._generation += 1
            self._suspended_until = max(
                self._suspended_until,
                time.monotonic() + self._cooldown,
            )
        logger.info("[%s] queue suspended for %.1fs after timeout", self._name, self._cooldown)


# ---------------------------------------------------------------------------
# Module-level singletons — one per domain, mirroring the existing split
# between PDFLLMQueue (document-generation-scoped) and _LLM_QUEUE (session-scoped).
# ---------------------------------------------------------------------------

_PDF_JOB_QUEUE: JobQueue | None = None
_SESSION_JOB_QUEUE: JobQueue | None = None
_PDF_QUEUE_LOCK = threading.Lock()
_SESSION_QUEUE_LOCK = threading.Lock()


def get_pdf_job_queue() -> JobQueue:
    """Return the module-level PDF structural job queue (lazy init)."""
    global _PDF_JOB_QUEUE
    if _PDF_JOB_QUEUE is None:
        with _PDF_QUEUE_LOCK:
            if _PDF_JOB_QUEUE is None:
                from config.settings import PDF_LLM_TIMEOUT_COOLDOWN
                _PDF_JOB_QUEUE = JobQueue(
                    name="llm-pdf-job-queue",
                    cooldown=float(PDF_LLM_TIMEOUT_COOLDOWN),
                )
    return _PDF_JOB_QUEUE


def get_session_job_queue() -> JobQueue:
    """Return the module-level reader-session job queue (lazy init)."""
    global _SESSION_JOB_QUEUE
    if _SESSION_JOB_QUEUE is None:
        with _SESSION_QUEUE_LOCK:
            if _SESSION_JOB_QUEUE is None:
                _SESSION_JOB_QUEUE = JobQueue(
                    name="llm-session-job-queue",
                    cooldown=30.0,
                )
    return _SESSION_JOB_QUEUE
