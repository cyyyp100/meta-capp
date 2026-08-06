from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from config.settings import (
    LLM_CACHE_ENABLED,
    LLM_CROP_TIMEOUT,
    LLM_LATEX_TIMEOUT,
    LLM_LAYOUT_TIMEOUT,
    PDF_LLM_TIMEOUT_COOLDOWN,
)

logger = logging.getLogger("LLM.pdf_assistant_queue")

PDF_LLM_PRIORITIES = {
    "layout_visible": 0,
    "layout_next": 1,
    "latex_visible": 2,
    "crop_visible": 3,
    "learning_prefetch": 4,
}


@dataclass(order=True)
class _QueuedTask:
    priority: int
    sequence: int
    task_type: str = field(compare=False)
    generation: int = field(compare=False)
    fn: Callable[[], Any] = field(compare=False)
    event: threading.Event = field(default_factory=threading.Event, compare=False)
    result: Any = field(default=None, compare=False)
    error: BaseException | None = field(default=None, compare=False)


class PDFLLMQueue:
    """Single-worker queue for PDF-specific LLM arbitration tasks.

    Tasks are small and controlled: order permutations, crop refinements, or
    LaTeX repair. The queue lets the visible page preempt background work and
    makes stale generations cheap to skip before execution.
    """

    def __init__(self) -> None:
        self._queue: queue.PriorityQueue[_QueuedTask] = queue.PriorityQueue()
        self._sequence = itertools.count()
        self._generation = 0
        self._suspended_until = 0.0
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, daemon=True, name="pdf-llm-queue")
        self._worker.start()

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def cancel_obsolete(self) -> int:
        with self._lock:
            self._generation += 1
            self._suspended_until = 0.0
            generation = self._generation
        logger.info("[LLM_ORDER] génération PDF invalidée token=%s", generation)
        return generation

    def run_sync(
        self,
        task_type: str,
        fn: Callable[[], Any],
        *,
        priority: int | None = None,
        timeout: float | None = None,
        generation: int | None = None,
    ) -> Any | None:
        if generation is None:
            generation = self.generation
        if self._is_obsolete(generation):
            return None
        suspended_for = self._suspended_for()
        if suspended_for > 0.0:
            logger.info("[LLM_%s] suspendu %.1fs après timeout précédent", task_type.upper(), suspended_for)
            return None

        task = _QueuedTask(
            priority=int(priority if priority is not None else PDF_LLM_PRIORITIES.get(task_type, 4)),
            sequence=next(self._sequence),
            task_type=task_type,
            generation=generation,
            fn=fn,
        )
        started = time.monotonic()
        self._queue.put(task)
        if not task.event.wait(timeout if timeout is not None else _timeout_for(task_type)):
            elapsed = time.monotonic() - started
            self._suspend_after_timeout(generation)
            logger.warning("[LLM_%s] timeout après %.1fs", task_type.upper(), elapsed)
            return None
        if task.error is not None:
            logger.debug("[LLM_%s] échec: %s", task_type.upper(), task.error)
            return None
        return task.result

    def _run(self) -> None:
        while True:
            task = self._queue.get()
            try:
                if self._is_obsolete(task.generation):
                    continue
                task.result = task.fn()
            except BaseException as exc:
                task.error = exc
            finally:
                task.event.set()
                self._queue.task_done()

    def _is_obsolete(self, generation: int) -> bool:
        with self._lock:
            return generation != self._generation

    def _suspended_for(self) -> float:
        with self._lock:
            remaining = self._suspended_until - time.monotonic()
        return max(0.0, remaining)

    def _suspend_after_timeout(self, generation: int) -> None:
        cooldown = max(5.0, float(PDF_LLM_TIMEOUT_COOLDOWN))
        with self._lock:
            if generation == self._generation:
                self._generation += 1
            self._suspended_until = max(self._suspended_until, time.monotonic() + cooldown)


_QUEUE = PDFLLMQueue()


def get_pdf_llm_queue() -> PDFLLMQueue:
    return _QUEUE


def llm_cache_enabled() -> bool:
    return bool(LLM_CACHE_ENABLED)


def validate_reading_order_response(raw_order: Any, valid_ids: list[str]) -> list[str] | None:
    if not isinstance(raw_order, list):
        return None
    valid = set(valid_ids)
    seen: set[str] = set()
    result: list[str] = []
    for item in raw_order:
        block_id = str(item) if item is not None else ""
        if block_id not in valid or block_id in seen:
            return None
        result.append(block_id)
        seen.add(block_id)
    if set(result) != valid:
        return None
    return result


def _timeout_for(task_type: str) -> float:
    if "crop" in task_type:
        return float(LLM_CROP_TIMEOUT)
    if "latex" in task_type:
        return float(LLM_LATEX_TIMEOUT)
    return float(LLM_LAYOUT_TIMEOUT)
