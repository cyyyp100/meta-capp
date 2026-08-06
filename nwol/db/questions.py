# db/questions.py — CRUD table questions
import json
import logging
from db import get_connection

logger = logging.getLogger("DB.questions")


def save_question(
    doc_id: int,
    scope_type: str,
    scope_label: str,
    page_start: int | None,
    page_end: int | None,
    question: dict,
    llm_model: str | None = None,
    session_id: int | None = None,
    chapter_id: int | None = None,
) -> int:
    choices = question.get("choices") or []
    choices_json = json.dumps(choices, ensure_ascii=False) if choices else None
    source_context = (
        question.get("source_context")
        or question.get("course_context")
        or question.get("context")
        or ""
    )
    source_block_id = str(question.get("source_block_id") or "").strip() or None
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO questions
               (document_id, session_id, chapter_id, scope_type, scope_label,
                page_start, page_end, question_type, question, source_context, source_block_id,
                choices_json, answer, llm_model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc_id,
                session_id,
                chapter_id,
                scope_type,
                scope_label,
                page_start,
                page_end,
                question.get("question_type"),
                question["question"],
                str(source_context).strip()[:1800] if source_context else None,
                source_block_id,
                choices_json,
                question.get("answer") or question.get("expected_answer", ""),
                question.get("llm_model") or llm_model,
            ),
        )
    logger.info("Question sauvegardée id=%s type=%s scope='%s'", cur.lastrowid, question.get("question_type"), scope_label)
    return int(cur.lastrowid)


def save_questions(doc_id: int, scope_type: str, scope_label: str,
                   page_start: int, page_end: int,
                   questions: list[dict], llm_model: str | None = None) -> list[int]:
    ids = [
        save_question(doc_id, scope_type, scope_label, page_start, page_end, question, llm_model)
        for question in questions
    ]
    logger.info(f"Questions sauvegardées ({len(questions)}) pour scope '{scope_label}'")
    return ids


def save_assistant_exchange(
    doc_id: int,
    page: int,
    user_question: str,
    llm_answer: str,
    session_id: int | None = None,
    chapter_id: int | None = None,
    llm_model: str | None = None,
    scope_type: str = "assistant_follow_up",
) -> int:
    """Question libre posée à la bulle assistant + réponse LLM.

    ``scope_type`` distingue la bulle (``assistant_follow_up``) des questions de
    suivi posées dans un bloc Q&R (``qa_follow_up``). Pas de ligne ``answers``
    associée : ce n'est pas une réponse évaluée de l'utilisateur, c'est lui qui
    interroge le LLM.
    """
    return save_question(
        doc_id=doc_id,
        scope_type=scope_type,
        scope_label=f"Page {page}",
        page_start=page,
        page_end=page,
        question={
            "question_type": "open",
            "question": user_question,
            "answer": llm_answer,
        },
        llm_model=llm_model,
        session_id=session_id,
        chapter_id=chapter_id,
    )


def count_assistant_questions(session_id: int) -> int:
    conn = get_connection()
    row = conn.execute(
        """SELECT COUNT(*) AS n FROM questions
           WHERE session_id=? AND scope_type='assistant_follow_up'""",
        (session_id,),
    ).fetchone()
    return int(row["n"]) if row else 0


def get_assistant_help_pages(session_id: int, top_n: int = 3) -> list[dict]:
    """Pages où l'utilisateur a le plus sollicité l'assistant pendant la session."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT page_start AS page, COUNT(*) AS questions_count
           FROM questions
           WHERE session_id=? AND scope_type='assistant_follow_up' AND page_start IS NOT NULL
           GROUP BY page_start
           ORDER BY questions_count DESC, page_start
           LIMIT ?""",
        (session_id, int(top_n)),
    ).fetchall()
    return [dict(r) for r in rows]


def get_questions_for_scope(doc_id: int, page_start: int, page_end: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM questions
           WHERE document_id=? AND page_start=? AND page_end=?
           ORDER BY id""",
        (doc_id, page_start, page_end)
    ).fetchall()
    return [dict(r) for r in rows]
