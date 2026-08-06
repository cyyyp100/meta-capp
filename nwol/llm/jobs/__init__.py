"""llm/jobs — Unified LLM job system (Phase 8).

Public surface:

  Types:
    JobSpec     — describes one unit of LLM work (kind, fn, generation, …)
    JobResult   — immutable outcome (value, error, cancelled, elapsed)
    JobHandle   — receipt from submit(); supports wait() / cancel() / .done

  Queue:
    JobQueue               — single-worker priority queue with generation tracking
    get_pdf_job_queue()    — module-level singleton for PDF structural jobs
    get_session_job_queue() — module-level singleton for reader-session jobs

  PDF job factories (generation-scoped to current document):
    make_layout_order_spec  — reading-order LLM arbitration
    make_crop_spec          — PDF crop refinement
    make_math_repair_spec   — late inline LaTeX repair

  Math/render/QA job factories (generation-scoped to reader session):
    make_math_render_spec   — inline math paragraph rendering
    make_schema_spec        — schema/diagram image description
    make_table_spec         — table image description
    make_slide_spec         — slide image description
    make_question_spec      — section Q&A question generation
    make_follow_up_spec     — follow-up answer
    make_evaluation_spec    — user answer evaluation
    make_rephrasing_spec    — paragraph rephrasing
    make_curiosity_hook_spec — chapter curiosity hook
    make_session_spec       — session-level background jobs
    make_lang_spec          — language module jobs

  Kind sets (for validation and routing):
    ALL_JOB_KINDS, PDF_JOB_KINDS, RENDER_JOB_KINDS,
    QA_JOB_KINDS, SESSION_JOB_KINDS, LANG_JOB_KINDS
"""

from llm.jobs.math_jobs import (
    make_curiosity_hook_spec,
    make_evaluation_spec,
    make_follow_up_spec,
    make_lang_spec,
    make_math_render_spec,
    make_question_spec,
    make_rephrasing_spec,
    make_schema_spec,
    make_session_spec,
    make_slide_spec,
    make_table_spec,
)
from llm.jobs.pdf_jobs import (
    make_crop_spec,
    make_layout_order_spec,
    make_math_repair_spec,
)
from llm.jobs.queue import JobQueue, get_pdf_job_queue, get_session_job_queue
from llm.jobs.types import (
    ALL_JOB_KINDS,
    LANG_JOB_KINDS,
    PDF_JOB_KINDS,
    QA_JOB_KINDS,
    RENDER_JOB_KINDS,
    SESSION_JOB_KINDS,
    JobHandle,
    JobResult,
    JobSpec,
)

__all__ = [
    # types
    "JobSpec",
    "JobResult",
    "JobHandle",
    # queue
    "JobQueue",
    "get_pdf_job_queue",
    "get_session_job_queue",
    # pdf factories
    "make_layout_order_spec",
    "make_crop_spec",
    "make_math_repair_spec",
    # math/render/qa factories
    "make_math_render_spec",
    "make_schema_spec",
    "make_table_spec",
    "make_slide_spec",
    "make_question_spec",
    "make_follow_up_spec",
    "make_evaluation_spec",
    "make_rephrasing_spec",
    "make_curiosity_hook_spec",
    "make_session_spec",
    "make_lang_spec",
    # kind sets
    "ALL_JOB_KINDS",
    "PDF_JOB_KINDS",
    "RENDER_JOB_KINDS",
    "QA_JOB_KINDS",
    "SESSION_JOB_KINDS",
    "LANG_JOB_KINDS",
]
