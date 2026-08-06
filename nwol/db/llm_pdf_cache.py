from __future__ import annotations

import json
import logging
from typing import Any

from db import get_connection

logger = logging.getLogger("DB.llm_pdf_cache")


def get_llm_pdf_cache(cache_key: str, task_type: str) -> dict[str, Any] | None:
    conn = get_connection()
    row = conn.execute(
        """SELECT cache_key, task_type, input_hash, output_json, confidence, model, created_at
           FROM llm_pdf_cache
          WHERE cache_key=? AND task_type=?""",
        (cache_key, task_type),
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    try:
        data["output"] = json.loads(data["output_json"])
    except (TypeError, json.JSONDecodeError):
        data["output"] = None
    return data


def save_llm_pdf_cache(
    *,
    cache_key: str,
    task_type: str,
    input_hash: str,
    output: dict[str, Any],
    confidence: float | None = None,
    model: str | None = None,
) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO llm_pdf_cache
               (cache_key, task_type, input_hash, output_json, confidence, model)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(cache_key, task_type) DO UPDATE SET
                 input_hash=excluded.input_hash,
                 output_json=excluded.output_json,
                 confidence=excluded.confidence,
                 model=excluded.model""",
            (
                cache_key,
                task_type,
                input_hash,
                json.dumps(output, ensure_ascii=False),
                confidence,
                model,
            ),
        )
    logger.debug("[LLM_%s] cache écrit key=%s", task_type.upper(), cache_key[:12])
