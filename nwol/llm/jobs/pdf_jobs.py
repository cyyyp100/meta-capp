"""llm/jobs/pdf_jobs.py — Typed JobSpec factories for PDF structural LLM jobs.

These are generation-scoped jobs whose results are meaningful only for the
document and page that triggered them.  A generation advance (new document
loaded, page re-extracted) invalidates all pending PDF jobs.

Priority ladder (lower = higher priority):
  0  layout_order_visible   — re-order blocks on the currently visible page
  1  layout_order_next      — pre-order blocks on the next page
  2  math_repair_visible    — late inline LaTeX repair for visible page
  3  crop_visible           — refine a crop on the currently visible block
  4  crop_prefetch          — speculative crop refinement off-screen

Usage:

    from llm.jobs.pdf_jobs import make_layout_order_spec, make_crop_spec
    from llm.jobs.queue import get_pdf_job_queue

    queue = get_pdf_job_queue()
    spec = make_layout_order_spec(
        fn=lambda: llm_reorder(blocks),
        generation=queue.current_generation(),
        visible=True,
        block_id=page_id,
    )
    result = queue.submit_sync(spec, timeout=12.0)
"""

from __future__ import annotations

from typing import Any, Callable

from config.settings import LLM_CROP_TIMEOUT, LLM_LATEX_TIMEOUT, LLM_LAYOUT_TIMEOUT
from llm.jobs.types import JobSpec

# ---------------------------------------------------------------------------
# Priority constants
# ---------------------------------------------------------------------------

PDF_PRIORITY_LAYOUT_VISIBLE: int = 0
PDF_PRIORITY_LAYOUT_NEXT: int = 1
PDF_PRIORITY_MATH_REPAIR: int = 2
PDF_PRIORITY_CROP_VISIBLE: int = 3
PDF_PRIORITY_CROP_PREFETCH: int = 4

_PRIORITY_KEY_MAP: dict[str, int] = {
    "layout_order_visible": PDF_PRIORITY_LAYOUT_VISIBLE,
    "layout_order_next": PDF_PRIORITY_LAYOUT_NEXT,
    "math_repair_visible": PDF_PRIORITY_MATH_REPAIR,
    "crop_visible": PDF_PRIORITY_CROP_VISIBLE,
    "crop_prefetch": PDF_PRIORITY_CROP_PREFETCH,
}


# ---------------------------------------------------------------------------
# Spec factories
# ---------------------------------------------------------------------------

def make_layout_order_spec(
    fn: Callable[[], Any],
    *,
    generation: int,
    visible: bool = True,
    page: int | None = None,
    block_id: str = "",
    timeout: float | None = None,
) -> JobSpec:
    """Return a JobSpec for a reading-order LLM arbitration job.

    *visible=True* means the target page is currently on screen — higher
    priority.  *visible=False* is for prefetch/look-ahead ordering.
    """
    priority_key = "layout_order_visible" if visible else "layout_order_next"
    return JobSpec(
        kind="layout_order",
        fn=fn,
        generation=generation,
        priority=_PRIORITY_KEY_MAP[priority_key],
        timeout=timeout if timeout is not None else float(LLM_LAYOUT_TIMEOUT),
        metadata={
            "priority_key": priority_key,
            "page": page,
            "block_id": block_id,
        },
    )


def make_crop_spec(
    fn: Callable[[], Any],
    *,
    generation: int,
    visible: bool = True,
    page: int | None = None,
    block_id: str = "",
    timeout: float | None = None,
) -> JobSpec:
    """Return a JobSpec for an LLM-guided PDF crop refinement job."""
    priority_key = "crop_visible" if visible else "crop_prefetch"
    return JobSpec(
        kind="layout_crop",
        fn=fn,
        generation=generation,
        priority=_PRIORITY_KEY_MAP[priority_key],
        timeout=timeout if timeout is not None else float(LLM_CROP_TIMEOUT),
        metadata={
            "priority_key": priority_key,
            "page": page,
            "block_id": block_id,
        },
    )


def make_math_repair_spec(
    fn: Callable[[], Any],
    *,
    generation: int,
    page: int | None = None,
    block_id: str = "",
    timeout: float | None = None,
) -> JobSpec:
    """Return a JobSpec for a late inline LaTeX repair job on a visible page."""
    return JobSpec(
        kind="math_repair",
        fn=fn,
        generation=generation,
        priority=PDF_PRIORITY_MATH_REPAIR,
        timeout=timeout if timeout is not None else float(LLM_LATEX_TIMEOUT),
        metadata={
            "priority_key": "math_repair_visible",
            "page": page,
            "block_id": block_id,
        },
    )
