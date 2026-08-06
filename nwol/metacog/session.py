# metacog/session.py — Orchestration d'une session d'apprentissage
from __future__ import annotations

import time

from db import get_connection
from db.answers import get_answers_for_session
from db.metacog import ensure_profile
from db.rephrasing import count_rephrasings_for_session
from db.session_gauges import record_gauges
from db.sessions import end_session as db_end_session
from db.sessions import start_session
from db.user import DEFAULT_USER_ID
from metacog.gauges import clamp_gauge, make_gauges, snapshot, update_gauges_from_evaluation
from metacog.profile import update_profile


class SessionManager:
    def __init__(
        self,
        document_id: int,
        user_id: int = DEFAULT_USER_ID,
        session_id: int | None = None,
        subject: str | None = None,
    ):
        self.document_id = document_id
        self.user_id = user_id
        self.session_id = session_id or start_session(document_id, user_id)
        self.started_monotonic = time.monotonic()
        self.profile = ensure_profile(user_id)
        self.gauges = make_gauges(self.profile)
        self.subject: str | None = subject
        self.subject_level: float | None = None
        self._subject_realtime_updates = 0
        if subject:
            self.set_subject(subject, record=False)
        self._ended_summary: dict | None = None
        self._profile_finalized = False
        record_gauges(self.session_id, self.current_gauges(), t=0.0)

    def update_from_evaluation(
        self,
        evaluation: dict,
        response_time_ms: int | None = None,
        consecutive_incorrect: int = 0,
        update_subject: bool = True,
    ) -> dict[str, float]:
        values = update_gauges_from_evaluation(
            self.gauges,
            evaluation,
            response_time_ms=response_time_ms,
            consecutive_incorrect=consecutive_incorrect,
        )
        if update_subject and self.subject and self.subject_level is not None and not evaluation.get("follow_up_answer"):
            from db.subjects import update_subject_from_evaluation
            self.subject_level = update_subject_from_evaluation(
                self.user_id,
                self.subject,
                evaluation,
                current_level=self.subject_level,
                session_id=self.session_id,
            )
            values["subject"] = self.subject_level
            self._subject_realtime_updates += 1
        record_gauges(self.session_id, values, t=time.monotonic() - self.started_monotonic)
        return values

    def current_gauges(self) -> dict[str, float]:
        gauges = snapshot(self.gauges)
        if self.subject is not None and self.subject_level is not None:
            gauges["subject"] = self.subject_level
        return gauges

    def update_subject_level(self, new_level: float) -> dict[str, float]:
        self.subject_level = max(0.0, min(100.0, float(new_level)))
        return self.current_gauges()

    def set_subject(self, subject: str, record: bool = True) -> dict[str, float]:
        from db.subjects import ensure_subject
        entry = ensure_subject(self.user_id, subject)
        self.subject = subject
        self.subject_level = float(entry.get("level", 50.0))
        values = self.current_gauges()
        if record:
            record_gauges(self.session_id, values, t=time.monotonic() - self.started_monotonic)
        return values

    def end_session(
        self,
        pages_read: int | None = None,
        chapters_completed: list | None = None,
    ) -> dict:
        duration_s = int(time.monotonic() - self.started_monotonic)
        answers = get_answers_for_session(self.session_id)
        session_score = self.current_gauges()
        quantitative_stats = self._compute_quantitative_stats(answers)
        db_end_session(
            self.session_id,
            pages_read=pages_read,
            duration_s=duration_s,
            chapters_completed=chapters_completed,
        )
        self._ended_summary = {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "duration_s": duration_s,
            "session_score": session_score,
            "profile": ensure_profile(self.user_id),
            "gauges": self.current_gauges(),
            **quantitative_stats,
        }
        return dict(self._ended_summary)

    def apply_meta_cognition_analysis(self, analysis: dict | None) -> dict[str, float]:
        if "meta_cognition" not in self.gauges:
            return self.current_gauges()

        analysis = analysis or {}
        try:
            delta = float(analysis.get("score_delta", analysis.get("scoreDelta", 0.0)) or 0.0)
        except (TypeError, ValueError):
            delta = 0.0
        delta = max(-20.0, min(20.0, delta))
        value = self.gauges["meta_cognition"].apply_delta(delta)
        values = self.current_gauges()
        record_gauges(self.session_id, values, t=time.monotonic() - self.started_monotonic)

        normalized_analysis = dict(analysis)
        normalized_analysis["score_delta"] = delta
        normalized_analysis["score"] = clamp_gauge(value)
        if self._ended_summary is not None:
            self._ended_summary["gauges"] = values
            self._ended_summary.setdefault("session_score", {})["meta_cognition"] = value
            self._ended_summary["meta_cognition_analysis"] = normalized_analysis
        return values

    def finalize_profile(self) -> dict:
        if self._profile_finalized and self._ended_summary:
            return ensure_profile(self.user_id)

        session_score = None
        if self._ended_summary:
            session_score = self._ended_summary.get("session_score")
        if session_score is None:
            session_score = self.current_gauges()

        profile = update_profile(self.user_id, session_score, self.session_id)
        self.profile = profile
        self._profile_finalized = True
        if self._ended_summary is not None:
            self._ended_summary["profile"] = profile

        if self.subject and session_score and self._subject_realtime_updates == 0:
            from db.subjects import update_subject_from_session
            retention = float(session_score.get("retention", 50.0))
            comprehension = float(session_score.get("context_comprehension", 50.0))
            reading_score = retention * 0.6 + comprehension * 0.4
            new_level = update_subject_from_session(
                self.user_id,
                self.subject,
                reading_score,
                session_id=self.session_id,
            )
            self.subject_level = new_level

        return profile

    def _compute_quantitative_stats(self, answers: list[dict]) -> dict:
        from db.questions import count_assistant_questions, get_assistant_help_pages

        verdict_answers = [
            answer for answer in answers
            if answer.get("verdict") in {"correct", "partial", "incorrect"}
        ]
        total = len(verdict_answers)
        correct = sum(1 for answer in verdict_answers if answer.get("verdict") == "correct")
        paragraphs_read = _count_answered_paragraphs(self.session_id)
        flashcards_created = _count_flashcards_from_session_questions(self.session_id)
        rephrasings_count = count_rephrasings_for_session(self.session_id)
        return {
            "paragraphs_read": paragraphs_read,
            "flashcards_created": flashcards_created,
            "rephrasings_count": rephrasings_count,
            "answers_total": total,
            "answers_correct": correct,
            "success_rate": (correct / total) if total else 0.0,
            "assistant_questions": count_assistant_questions(self.session_id),
            "help_pages": get_assistant_help_pages(self.session_id),
        }


def _count_answered_paragraphs(session_id: int) -> int:
    """Compte le nombre de paragraphes distincts couverts par cette session."""
    conn = get_connection()
    # Compte les scope_labels distincts des questions liées à cette session
    row = conn.execute(
        """SELECT COUNT(DISTINCT q.scope_label) AS n
           FROM answers a
           JOIN questions q ON q.id = a.question_id
           WHERE a.session_id=? AND a.question_id IS NOT NULL""",
        (session_id,),
    ).fetchone()
    count = int(row["n"]) if row else 0
    if count:
        return count
    # Fallback : compte les réponses avec verdict
    row = conn.execute(
        """SELECT COUNT(DISTINCT question_id) AS n
           FROM answers
           WHERE session_id=? AND verdict IN ('correct', 'partial', 'incorrect')
             AND question_id IS NOT NULL""",
        (session_id,),
    ).fetchone()
    return int(row["n"]) if row else 0


def _count_flashcards_from_session_questions(session_id: int) -> int:
    conn = get_connection()
    row = conn.execute(
        """SELECT COUNT(*) AS n
           FROM flashcards
           WHERE session_id=?
              OR question_id IN (
                SELECT id FROM questions WHERE session_id=?
              )""",
        (session_id, session_id),
    ).fetchone()
    return int(row["n"]) if row else 0
