# ui/quiz_page.py — Interface Quiz adaptatif avec LLM
from __future__ import annotations

from collections import defaultdict
import tkinter as tk
from typing import Callable

from i18n import t
from ui import theme
from ui.components import CanvasWheelController, score_color
from ui.rich_text import rich_text_widget
from ui.top_nav import Tooltip
from llm.ollama_client import (
    evaluate_answer_async,
    generate_question_async,
    generate_quiz_session_analysis_async,
)

BG = theme.BG
SURFACE = theme.SURFACE
TEXT = theme.TEXT
MUTED = theme.MUTED
ACCENT = theme.ACCENT

_TYPE_COLORS: dict[str, tuple[str, str]] = {
    "qcm":           (theme.QUESTION, theme.QUESTION_BORDER),
    "open":          (theme.SUCCESS_SOFT, theme.SUCCESS),
    "comprehension": (theme.WARNING_SOFT, theme.WARNING),
    "application":   (theme.ACCENT_SOFT, theme.ACCENT_HOVER),
    "curiosity":     (theme.DANGER_SOFT, theme.DANGER),
    "visualization": (theme.SURFACE_SOFT, theme.ACCENT_HOVER),
    "metacognition": (theme.BG_ALT, theme.TEXT_SOFT),
    "anticipation":  (theme.WARNING_SOFT, theme.WARNING),
}

def _type_label(qtype: str) -> str:
    return t(f"quiz.type.{qtype}")

_KNOWN_SUBJECTS = {
    "mathématiques", "sciences", "histoire",
    "géographie", "français", "informatique", "culture",
}

_SPINNER = ["   ", ".  ", ".. ", "..."]


class QuizPage(tk.Frame):
    def __init__(
        self,
        master,
        on_back: Callable,
        get_questions: Callable[[int, str | None], list[dict]],
        on_answer: Callable[..., None] | None = None,
        on_flashcards: Callable[[], None] | None = None,
        on_profile: Callable[[], None] | None = None,
        **kwargs,
    ):
        super().__init__(master, bg=BG, **kwargs)
        self._on_back = on_back
        self._get_questions = get_questions
        self._on_answer = on_answer
        self._on_flashcards = on_flashcards
        self._on_profile = on_profile

        self._questions_raw: list[dict] = []
        self._current_index: int = 0
        self._score: int = 0
        self._answers_history: list[dict] = []
        self._current_q: dict = {}
        self._current_raw: dict = {}
        self._selected_var = tk.StringVar(value="")
        self._spinner_job: str | None = None
        self._spinner_msg: str = ""
        self._spinner_idx: int = 0
        self._user_id: int = 1
        self._selected_subject: str | None = None
        self._can_advance = False
        self._advancing = False
        self._validated_current = False

        # Widgets set during question display
        self._answer_choices_frame: tk.Frame | None = None
        self._open_entry_ref: tk.Text | None = None
        self._feedback_frame: tk.Frame | None = None
        self._validate_btn: tk.Button | None = None
        self._next_btn: tk.Button | None = None
        self._choice_rows: list[tuple[str, tk.Radiobutton, tk.Text, tk.Frame]] = []
        self._results_wheel_controller: CanvasWheelController | None = None

        self._build_chrome()

    # ------------------------------------------------------------------
    # Static chrome (nav bar, always visible)
    # ------------------------------------------------------------------

    def _build_chrome(self) -> None:
        nav = tk.Frame(self, bg=BG)
        nav.pack(fill="x", padx=40, pady=(28, 0))

        back_btn = theme.make_button(
            nav, text=t("quiz.back"), command=self._on_back, kind="ghost",
            font=(theme.FONT_UI, 11, "bold"),
        )
        back_btn.pack(side="left")
        Tooltip(back_btn, t("quiz.back_tip"))

        self._progress_lbl = tk.Label(
            nav, text="", bg=BG, fg=MUTED, font=(theme.FONT_UI, 11, "bold"),
        )
        self._progress_lbl.pack(side="right")

        theme.divider(self, pady=(16, 0))

        self._body = tk.Frame(self, bg=BG)
        self._body.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def load(self, user_id: int = 1) -> None:
        self._user_id = user_id
        self._current_index = 0
        self._score = 0
        self._answers_history = []
        self._current_q = {}
        self._progress_lbl.configure(text="")
        self._show_subject_selector()

    # ------------------------------------------------------------------
    # Subject selector
    # ------------------------------------------------------------------

    def _show_subject_selector(self) -> None:
        self._clear_body()

        try:
            from db.subjects import get_all_subjects, SUBJECT_LABELS
            subjects = get_all_subjects(self._user_id)
        except Exception:
            subjects = []
            SUBJECT_LABELS = {}  # type: ignore[assignment]

        wrapper = tk.Frame(self._body, bg=BG)
        wrapper.place(relx=0.5, rely=0.44, anchor="center")

        tk.Label(
            wrapper, text=t("quiz.subject_title"),
            bg=BG, fg=TEXT, font=(theme.FONT_TITLE, 24, "bold"),
        ).pack(pady=(0, 6))

        tk.Label(
            wrapper, text=t("quiz.subject_subtitle"),
            bg=BG, fg=MUTED, font=(theme.FONT_UI, 12),
        ).pack(pady=(0, 28))

        if subjects:
            grid_frame = tk.Frame(wrapper, bg=BG)
            grid_frame.pack(pady=(0, 4))
            for i, s in enumerate(subjects):
                subj = s["subject"]
                label = SUBJECT_LABELS.get(subj, subj.capitalize())
                theme.make_button(
                    grid_frame, text=label,
                    command=lambda sub=subj: self._start_quiz(sub),
                    kind="soft", padx=22, pady=10,
                    font=(theme.FONT_UI, 11, "bold"),
                ).grid(row=i // 3, column=i % 3, padx=6, pady=6, sticky="ew")

        theme.divider(wrapper, pady=(18, 18))

        theme.make_button(
            wrapper, text=t("quiz.subject_all"),
            command=lambda: self._start_quiz(None),
            kind="primary", padx=28, pady=12,
            font=(theme.FONT_UI, 11, "bold"),
        ).pack()

    def _start_quiz(self, subject: str | None) -> None:
        self._selected_subject = subject
        self._questions_raw = self._get_questions(self._user_id, subject)
        self._current_index = 0
        self._score = 0
        self._answers_history = []
        self._current_q = {}

        total = len(self._questions_raw)
        if not total:
            self._progress_lbl.configure(text="")
            self._show_empty()
            return

        self._progress_lbl.configure(text=f"1 / {total}")
        self._generate_current_question()

    # ------------------------------------------------------------------
    # Body helpers
    # ------------------------------------------------------------------

    def _clear_body(self) -> None:
        self._stop_spinner()
        self._answer_choices_frame = None
        self._open_entry_ref = None
        self._feedback_frame = None
        self._validate_btn = None
        self._next_btn = None
        self._choice_rows = []
        self._results_wheel_controller = None
        self._can_advance = False
        self._advancing = False
        self._validated_current = False
        for w in self._body.winfo_children():
            w.destroy()

    def _show_empty(self) -> None:
        self._clear_body()
        wrapper = tk.Frame(self._body, bg=BG)
        wrapper.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(
            wrapper, text=t("quiz.no_questions"),
            bg=BG, fg=MUTED, font=(theme.FONT_UI, 13),
        ).pack()

    # ------------------------------------------------------------------
    # Spinner
    # ------------------------------------------------------------------

    def _show_loading(self, message: str) -> None:
        self._clear_body()
        wrapper = tk.Frame(self._body, bg=BG)
        wrapper.place(relx=0.5, rely=0.45, anchor="center")
        self._spinner_lbl = tk.Label(
            wrapper, text="", bg=BG, fg=MUTED, font=(theme.FONT_UI, 13),
        )
        self._spinner_lbl.pack()
        self._spinner_msg = message
        self._spinner_idx = 0
        self._tick_spinner()

    def _tick_spinner(self) -> None:
        if not hasattr(self, "_spinner_lbl") or not self._spinner_lbl.winfo_exists():
            return
        dots = _SPINNER[self._spinner_idx % len(_SPINNER)]
        self._spinner_lbl.configure(text=f"{self._spinner_msg}{dots}")
        self._spinner_idx += 1
        self._spinner_job = self.after(380, self._tick_spinner)

    def _stop_spinner(self) -> None:
        if self._spinner_job:
            try:
                self.after_cancel(self._spinner_job)
            except Exception:
                pass
            self._spinner_job = None

    # ------------------------------------------------------------------
    # Question generation (LLM)
    # ------------------------------------------------------------------

    def _generate_current_question(self) -> None:
        raw = self._questions_raw[self._current_index]
        self._current_raw = raw
        self._show_loading(t("quiz.generating"))

        paragraph = _question_generation_context(raw)
        if raw.get("choices"):
            paragraph += "\nPropositions : " + " / ".join(str(c) for c in raw["choices"])

        context = {
            "paragraph": paragraph,
            "chapter_title": raw.get("chapter_title") or raw.get("category", ""),
            "doc_title": raw.get("document") or "Quiz de révision MetaC-App",
            "standalone": True,
            "preferred_question_type": _preferred_quiz_question_type(raw),
            "history": [
                {"question": h["question"], "verdict": h["verdict"]}
                for h in self._answers_history[-3:]
            ],
        }

        def _ok(q: dict) -> None:
            self.after(0, lambda: self._display_question(q))

        def _err(_msg: str) -> None:
            fallback = {
                "question_type": "qcm" if raw.get("choices") else "open",
                "question": raw["question"],
                "choices": list(raw.get("choices") or []),
                "expected_answer": raw["answer"],
                "evaluation_criteria": [],
                "paragraph_mask": {"enabled": False},
            }
            self.after(0, lambda: self._display_question(fallback))

        generate_question_async(context, _ok, _err)

    # ------------------------------------------------------------------
    # Question display
    # ------------------------------------------------------------------

    def _display_question(self, q: dict) -> None:
        self._current_q = q
        self._clear_body()
        self._can_advance = False
        self._advancing = False
        self._validated_current = False

        tk.Frame(self._body, bg=BG).pack(fill="both", expand=True)

        card = theme.surface_frame(self._body, bg=SURFACE)
        card.pack(anchor="center", padx=80, fill="x")
        card.configure(padx=40, pady=32)

        # Question type badge
        qtype = q.get("question_type", "open")
        bg_badge, fg_badge = _TYPE_COLORS.get(qtype, ("#EEF2F4", "#2d4a5e"))
        tk.Label(
            card, text=_type_label(qtype),
            bg=bg_badge, fg=fg_badge,
            font=(theme.FONT_UI, 9, "bold"), padx=8, pady=3,
        ).pack(anchor="w")

        context_text = _display_course_context(self._current_raw)
        if context_text:
            context_box = tk.Frame(card, bg=theme.BG_ALT, padx=12, pady=10)
            context_box.pack(fill="x", pady=(12, 8))
            rich_text_widget(
                context_box,
                context_text,
                bg=theme.BG_ALT,
                fg=theme.TEXT_SOFT,
                font=(theme.FONT_UI, 10),
            ).pack(fill="x")

        # Question text
        rich_text_widget(
            card, text=q.get("question", ""),
            bg=SURFACE, fg=TEXT,
            font=(theme.FONT_UI, 14, "bold"),
        ).pack(fill="x", pady=(10, 16))

        # Answer input — QCM or open text
        choices = q.get("choices") or []
        self._selected_var.set("")

        if choices:
            cf = tk.Frame(card, bg=SURFACE)
            cf.pack(fill="x")
            for choice in choices:
                self._pack_choice_row(cf, str(choice))
            self._answer_choices_frame = cf
            self._open_entry_ref = None
        else:
            oe = tk.Text(
                card, font=(theme.FONT_UI, 12), height=3,
                bg=theme.BG_ALT, fg=TEXT, relief="flat", wrap="word",
                padx=8, pady=6,
                highlightthickness=1, highlightbackground=theme.BORDER,
            )
            oe.pack(fill="x", pady=(0, 8))
            oe.focus_set()
            oe.bind("<Control-Return>", lambda _e: self._validate())
            self._open_entry_ref = oe
            self._answer_choices_frame = None

        # Feedback placeholder (filled after evaluation)
        self._feedback_frame = tk.Frame(card, bg=SURFACE)
        self._feedback_frame.pack(fill="x", pady=(8, 0))

        # Action buttons
        actions = tk.Frame(card, bg=SURFACE)
        actions.pack(fill="x", pady=(16, 0))

        self._validate_btn = theme.make_button(
            actions, text=t("quiz.validate_btn"), command=self._validate,
            kind="primary", padx=20, pady=8,
            font=(theme.FONT_UI, 11, "bold"),
        )
        self._validate_btn.pack(side="left")

        total = len(self._questions_raw)
        is_last = (self._current_index + 1) >= total
        next_label = t("quiz.last_btn") if is_last else t("quiz.next_btn")
        self._next_btn = theme.make_button(
            actions, text=next_label, command=self._next_question,
            kind="secondary", padx=20, pady=8,
            font=(theme.FONT_UI, 11, "bold"),
        )
        # _next_btn volontairement non affiché ici — apparaît après correction

        tk.Frame(self._body, bg=BG).pack(fill="both", expand=True)

    def _pack_choice_row(self, parent: tk.Frame, choice: str) -> None:
        row = tk.Frame(
            parent,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            padx=10,
            pady=7,
        )
        row.pack(fill="x", pady=3)
        btn = tk.Radiobutton(
            row,
            text="",
            variable=self._selected_var,
            value=choice,
            bg=SURFACE,
            fg=TEXT,
            selectcolor=SURFACE,
            activebackground=theme.ACCENT_SOFT,
            font=(theme.FONT_UI, 12),
            anchor="w",
            cursor="hand2",
        )
        btn.pack(side="left", anchor="n")
        text = rich_text_widget(
            row,
            choice,
            bg=SURFACE,
            fg=TEXT,
            font=(theme.FONT_UI, 12),
        )
        text.pack(side="left", fill="x", expand=True, padx=(4, 0))
        text.bind("<Button-1>", lambda _event, value=choice: self._selected_var.set(value))
        row.bind("<Button-1>", lambda _event, value=choice: self._selected_var.set(value))
        self._choice_rows.append((choice, btn, text, row))

    # ------------------------------------------------------------------
    # Validation & LLM evaluation
    # ------------------------------------------------------------------

    def _validate(self) -> None:
        if self._validated_current or self._can_advance:
            return
        choices = self._current_q.get("choices") or []
        if choices:
            user_answer = self._selected_var.get().strip()
            if not user_answer:
                return
            self._disable_answer_inputs()
        else:
            if self._open_entry_ref is None:
                return
            user_answer = self._open_entry_ref.get("1.0", "end").strip()
            if not user_answer:
                return
            self._open_entry_ref.configure(state="disabled")

        self._validated_current = True
        if self._validate_btn:
            self._validate_btn.configure(state="disabled")

        self._show_eval_spinner()

        raw = self._current_raw
        paragraph = _question_generation_context(raw)
        context = {
            "question": self._current_q,
            "user_answer": user_answer,
            "paragraph": paragraph,
        }
        ua = user_answer

        def _ok(ev: dict) -> None:
            self.after(0, lambda: self._show_feedback(ev, ua))

        def _err(_msg: str) -> None:
            expected = (raw.get("answer") or "").strip().lower()
            correct = ua.strip().lower() == expected
            fallback = {
                "verdict": "correct" if correct else "incorrect",
                "feedback": t("quiz.correct_fallback") if correct else t("quiz.incorrect_fallback", answer=raw["answer"]),
                "completion": "",
                "hint": "",
            }
            self.after(0, lambda: self._show_feedback(fallback, ua))

        evaluate_answer_async(context, _ok, _err)

    def _show_eval_spinner(self) -> None:
        if not self._feedback_frame:
            return
        for w in self._feedback_frame.winfo_children():
            w.destroy()
        tk.Label(
            self._feedback_frame,
            text=t("quiz.correcting"),
            bg=SURFACE, fg=MUTED, font=(theme.FONT_UI, 11, "italic"),
        ).pack(anchor="w", pady=(8, 0))

    def _show_feedback(self, evaluation: dict, user_answer: str) -> None:
        if self._can_advance:
            return
        verdict = evaluation.get("verdict", "incorrect")
        feedback_text = evaluation.get("feedback", "")
        completion = evaluation.get("completion", "")
        hint = evaluation.get("hint", "")
        correct = verdict == "correct"
        score = 1.0 if correct else (0.5 if verdict == "partial" else 0.0)

        if correct:
            self._score += 1
            bg_fb, fg_fb = theme.SUCCESS_SOFT, theme.SUCCESS
        elif verdict == "partial":
            bg_fb, fg_fb = theme.WARNING_SOFT, theme.WARNING
        else:
            bg_fb, fg_fb = theme.DANGER_SOFT, theme.DANGER

        # Record for session analysis
        raw = self._current_raw
        category = (raw.get("category") or self._selected_subject or "culture").lower()
        is_reading = raw.get("source") == "reading"
        self._answers_history.append({
            "question": self._current_q.get("question", ""),
            "user_answer": user_answer,
            "verdict": verdict,
            "score": score,
            "category": category,
            "source": raw.get("source", "static"),
            "document": raw.get("document") if is_reading else None,
            "chapter_title": raw.get("chapter_title") if is_reading else None,
            "course_context": raw.get("course_context") if is_reading else None,
            "expected_answer": raw.get("answer"),
        })

        # Subject gauge callback
        if self._on_answer:
            try:
                self._on_answer(category, correct, {
                    "verdict": verdict,
                    "question_id": raw.get("id"),
                    "source": raw.get("source", "static"),
                    "document": raw.get("document"),
                    "question_type": self._current_q.get("question_type"),
                    "metacog_signals": evaluation.get("metacog_signals") or {},
                    "curiosity_signals": evaluation.get("curiosity_signals") or {},
                    "creativity_signals": evaluation.get("creativity_signals") or {},
                })
            except Exception:
                pass

        # Render feedback card
        if self._feedback_frame:
            for w in self._feedback_frame.winfo_children():
                w.destroy()

            fb_card = tk.Frame(self._feedback_frame, bg=bg_fb, padx=12, pady=10)
            fb_card.pack(fill="x", pady=(10, 0))

            main_text = feedback_text or (t("quiz.correct_fallback") if correct else t("quiz.incorrect_fallback", answer=""))
            rich_text_widget(
                fb_card,
                main_text,
                bg=bg_fb, fg=fg_fb,
                font=(theme.FONT_UI, 11, "bold"),
            ).pack(fill="x")

            if completion:
                rich_text_widget(
                    fb_card,
                    t("quiz.completion_prefix", text=completion),
                    bg=bg_fb, fg=fg_fb, font=(theme.FONT_UI, 10),
                ).pack(fill="x", pady=(4, 0))

            if hint:
                rich_text_widget(
                    fb_card,
                    t("quiz.hint_prefix", text=hint),
                    bg=bg_fb, fg=fg_fb, font=(theme.FONT_UI, 10),
                ).pack(fill="x", pady=(4, 0))

        # Highlight QCM choices
        if self._answer_choices_frame:
            raw = self._current_raw
            expected = (
                self._current_q.get("expected_answer") or raw.get("answer") or ""
            ).strip().lower()
            for choice, btn, text_widget, row in self._choice_rows:
                val = choice.strip().lower()
                if val == expected:
                    btn.configure(fg=theme.SUCCESS, font=(theme.FONT_UI, 12, "bold"))
                    text_widget.tag_configure("rich_text", foreground=theme.SUCCESS, font=(theme.FONT_UI, 12, "bold"))
                    row.configure(highlightbackground=theme.SUCCESS)
                elif val == user_answer.strip().lower() and val != expected:
                    btn.configure(fg=theme.DANGER)
                    text_widget.tag_configure("rich_text", foreground=theme.DANGER)
                    row.configure(highlightbackground=theme.DANGER)

        self._can_advance = True
        self._validated_current = True
        if self._validate_btn:
            self._validate_btn.pack_forget()
        if self._next_btn:
            self._next_btn.pack(side="left")

        total = len(self._questions_raw)
        self._progress_lbl.configure(text=f"{self._current_index + 1} / {total}")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _next_question(self) -> None:
        if not self._can_advance or self._advancing:
            return
        self._advancing = True
        self._can_advance = False
        if self._next_btn:
            self._next_btn.configure(state="disabled")
        self._current_index += 1
        total = len(self._questions_raw)
        if self._current_index >= total:
            self._start_analysis()
        else:
            self._progress_lbl.configure(text=f"{self._current_index + 1} / {total}")
            self._generate_current_question()

    def _disable_answer_inputs(self) -> None:
        if self._open_entry_ref is not None:
            self._open_entry_ref.configure(state="disabled")
        for _choice, btn, text_widget, row in self._choice_rows:
            btn.configure(state="disabled", cursor="arrow")
            text_widget.configure(cursor="arrow")
            row.configure(cursor="arrow")
            row.bind("<Button-1>", lambda _event: "break")
            text_widget.bind("<Button-1>", lambda _event: "break")

    # ------------------------------------------------------------------
    # Session analysis (LLM)
    # ------------------------------------------------------------------

    def _start_analysis(self) -> None:
        self._show_loading(t("quiz.analyzing"))

        try:
            from db.subjects import get_all_subjects
            subject_profiles = get_all_subjects(self._user_id)
        except Exception:
            subject_profiles = []

        context = {
            "answers_history": self._answers_history,
            "subject_profiles": subject_profiles,
        }

        def _ok(result: dict) -> None:
            fallback = self._fallback_quiz_analysis()
            merged = _merge_analysis(fallback, result or {})
            self.after(0, lambda r=merged: self._show_results(r))

        def _err(_msg: str) -> None:
            self.after(0, lambda: self._show_results(self._fallback_quiz_analysis()))

        generate_quiz_session_analysis_async(context, _ok, _err)

    def _fallback_quiz_analysis(self) -> dict:
        by_category: dict[str, list[dict]] = defaultdict(list)
        mistakes: list[dict] = []
        for answer in self._answers_history:
            category = (answer.get("category") or "culture").lower()
            by_category[category].append(answer)
            if answer.get("verdict") != "correct":
                mistakes.append(answer)

        strengths: list[str] = []
        weaknesses: list[str] = []
        categories: list[dict] = []
        courses_to_review: list[dict] = []

        for category, rows in sorted(by_category.items()):
            total = len(rows)
            correct = sum(1 for row in rows if row.get("verdict") == "correct")
            pct = int(round(correct / total * 100)) if total else 0
            item = {
                "category": category,
                "label": _category_label(category),
                "total": total,
                "correct": correct,
                "success_rate": pct,
                "mistakes": total - correct,
            }
            categories.append(item)
            if pct >= 75:
                strengths.append(t("quiz.category.strength", label=_category_label(category), pct=pct))
            elif total - correct > 0:
                weaknesses.append(t("quiz.category.weakness", label=_category_label(category), count=total - correct))

        grouped_review: dict[tuple[str, str], dict] = {}
        for answer in mistakes:
            source = answer.get("source") or "static"
            if source == "reading":
                title = answer.get("chapter_title") or answer.get("document") or _category_label(answer.get("category") or "culture")
                key = ("reading", title)
                entry = grouped_review.setdefault(key, {
                    "title": title,
                    "count": 0,
                    "source": "reading",
                    "document": answer.get("document") or "",
                    "chapter_title": answer.get("chapter_title") or "",
                    "course_context": answer.get("course_context") or "",
                })
            else:
                title = _category_label(answer.get("category") or "culture")
                key = ("static", title)
                entry = grouped_review.setdefault(key, {
                    "title": title,
                    "count": 0,
                    "source": "static",
                    "document": "",
                    "chapter_title": "",
                    "course_context": "",
                })
            entry["count"] += 1

        for entry in sorted(grouped_review.values(), key=lambda item: item["count"], reverse=True):
            count = int(entry["count"])
            priority = t("quiz.priority.high") if count >= 2 else t("quiz.priority.medium")
            reason = t("quiz.review_reason", count=count)
            if entry.get("course_context"):
                reason += t("quiz.review_reason_context")
            courses_to_review.append({
                "title": entry["title"],
                "reason": reason,
                "priority": priority,
                "source": entry["source"],
                "document": entry.get("document", ""),
                "chapter_title": entry.get("chapter_title", ""),
            })

        total = len(self._questions_raw)
        pct = int(round(self._score / total * 100)) if total else 0
        if pct >= 80:
            analysis = t("quiz.analysis_high")
        elif pct >= 50:
            analysis = t("quiz.analysis_mid")
        else:
            analysis = t("quiz.analysis_low")

        return {
            "analysis": analysis,
            "strengths": strengths,
            "weaknesses": weaknesses or [t("quiz.no_weakness")],
            "categories": categories,
            "courses_to_review": courses_to_review,
            "source": "fallback",
        }

    # ------------------------------------------------------------------
    # Results screen
    # ------------------------------------------------------------------

    def _show_results(self, analysis: dict) -> None:
        analysis = _merge_analysis(self._fallback_quiz_analysis(), analysis or {})
        self._clear_body()
        total = len(self._questions_raw)
        pct = int(round(self._score / total * 100)) if total else 0
        self._progress_lbl.configure(text=f"{self._score} / {total}")

        # Scrollable container
        canvas = tk.Canvas(self._body, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(self._body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)

        inner = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))

        self._results_wheel_controller = CanvasWheelController(canvas, inner)

        content = tk.Frame(inner, bg=BG)
        content.pack(fill="both", expand=True, padx=64, pady=32)

        # Score card
        score_card = theme.surface_frame(content, bg=SURFACE)
        score_card.pack(fill="x", pady=(0, 20))
        score_card.configure(padx=32, pady=24)

        score_fg = score_color(pct)
        tk.Label(
            score_card, text=t("quiz.done_title"),
            bg=SURFACE, fg=TEXT, font=(theme.FONT_TITLE, 22, "bold"),
        ).pack(anchor="w")
        s = t("quiz.score_s") if self._score > 1 else ""
        tk.Label(
            score_card,
            text=t("quiz.score_line", correct=self._score, s=s, total=total, pct=pct),
            bg=SURFACE, fg=score_fg, font=(theme.FONT_UI, 14, "bold"),
        ).pack(anchor="w", pady=(6, 0))
        score_bar = tk.Canvas(score_card, height=18, bg=SURFACE, highlightthickness=0)
        score_bar.pack(fill="x", pady=(14, 0))
        score_bar.bind(
            "<Configure>",
            lambda event, c=score_bar: theme.draw_pill_bar(
                c,
                event.width,
                14,
                pct,
                fill=score_fg,
                background=theme.BORDER,
                tag="score",
            ),
        )
        tk.Label(
            score_card,
            text=_score_message(pct),
            bg=SURFACE,
            fg=theme.TEXT_SOFT,
            font=(theme.FONT_UI, 11),
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(10, 0))

        # LLM analysis text
        analysis_text = (analysis.get("analysis") or "").strip()
        if analysis_text:
            a_card = theme.surface_frame(content, bg=SURFACE)
            a_card.pack(fill="x", pady=(0, 20))
            a_card.configure(padx=32, pady=20)
            tk.Label(
                a_card, text=t("quiz.analysis_header"),
                bg=SURFACE, fg=TEXT, font=(theme.FONT_UI, 12, "bold"),
            ).pack(anchor="w", pady=(0, 8))
            rich_text_widget(
                a_card,
                analysis_text,
                bg=SURFACE, fg=theme.TEXT_SOFT,
                font=(theme.FONT_UI, 11),
            ).pack(fill="x")

        self._render_competency_block(content, analysis)

        # Courses to review
        courses = analysis.get("courses_to_review") or []
        if courses:
            tk.Label(
                content, text=t("quiz.courses_header"),
                bg=BG, fg=TEXT, font=(theme.FONT_UI, 13, "bold"),
            ).pack(anchor="w", pady=(0, 10))
            for course in courses:
                self._render_course_card(content, course)
        elif pct >= 80:
            tk.Label(
                content, text=t("quiz.excellent"),
                bg=BG, fg=theme.SUCCESS, font=(theme.FONT_UI, 12, "bold"),
            ).pack(anchor="w", pady=(0, 10))

        # Retry + back buttons
        self._render_result_actions(content)

    def _render_competency_block(self, parent: tk.Frame, analysis: dict) -> None:
        categories = analysis.get("categories") or []
        if not categories:
            return
        tk.Label(
            parent,
            text=t("quiz.competency_header"),
            bg=BG,
            fg=TEXT,
            font=(theme.FONT_UI, 13, "bold"),
        ).pack(anchor="w", pady=(0, 10))

        grid = tk.Frame(parent, bg=BG)
        grid.pack(fill="x", pady=(0, 18))
        grid.columnconfigure(0, weight=1, uniform="quizcats")
        grid.columnconfigure(1, weight=1, uniform="quizcats")
        for index, category in enumerate(categories):
            card = theme.surface_frame(grid, bg=SURFACE)
            card.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0 if index % 2 == 0 else 8, 8 if index % 2 == 0 else 0), pady=6)
            card.configure(padx=18, pady=14)
            label = category.get("label") or _category_label(category.get("category", "culture"))
            pct = int(category.get("success_rate") or 0)
            tk.Label(card, text=label, bg=SURFACE, fg=TEXT, font=(theme.FONT_UI, 11, "bold"), anchor="w").pack(fill="x")
            tk.Label(
                card,
                text=t("quiz.correct_count", correct=category.get("correct", 0), total=category.get("total", 0), mistakes=category.get("mistakes", 0)),
                bg=SURFACE,
                fg=MUTED,
                font=(theme.FONT_UI, 9),
                anchor="w",
            ).pack(fill="x", pady=(2, 8))
            bar = tk.Canvas(card, height=16, bg=SURFACE, highlightthickness=0)
            bar.pack(fill="x")
            bar.bind(
                "<Configure>",
                lambda event, c=bar, value=pct: theme.draw_pill_bar(
                    c,
                    event.width,
                    12,
                    value,
                    fill=score_color(value),
                    background=theme.BORDER,
                    tag="bar",
                ),
            )

        strengths = analysis.get("strengths") or []
        weaknesses = analysis.get("weaknesses") or []
        if strengths or weaknesses:
            note = theme.surface_frame(parent, bg=theme.SURFACE_SOFT)
            note.pack(fill="x", pady=(0, 18))
            note.configure(padx=18, pady=12)
            if strengths:
                rich_text_widget(
                    note,
                    t("quiz.strengths_prefix") + " ".join(str(item) for item in strengths[:3]),
                    bg=theme.SURFACE_SOFT,
                    fg=theme.TEXT_SOFT,
                    font=(theme.FONT_UI, 10),
                ).pack(fill="x")
            if weaknesses:
                rich_text_widget(
                    note,
                    t("quiz.weaknesses_prefix") + " ".join(str(item) for item in weaknesses[:3]),
                    bg=theme.SURFACE_SOFT,
                    fg=theme.TEXT_SOFT,
                    font=(theme.FONT_UI, 10),
                ).pack(fill="x", pady=(6 if strengths else 0, 0))

    def _render_result_actions(self, content: tk.Frame) -> None:
        btns = tk.Frame(content, bg=BG)
        btns.pack(anchor="w", pady=(24, 0))

        theme.make_button(
            btns, text=t("quiz.retry_btn"), command=lambda: self.load(self._user_id),
            kind="secondary", padx=20, pady=10,
            font=(theme.FONT_UI, 11, "bold"),
        ).pack(side="left", padx=(0, 10))

        if self._on_flashcards and self._has_flashcards():
            theme.make_button(
                btns,
                text=t("quiz.flashcards_btn"),
                command=self._on_flashcards,
                kind="secondary",
                padx=20,
                pady=10,
                font=(theme.FONT_UI, 11, "bold"),
            ).pack(side="left", padx=(0, 10))

        if self._on_profile:
            theme.make_button(
                btns,
                text=t("quiz.profile_btn"),
                command=self._on_profile,
                kind="soft",
                padx=20,
                pady=10,
                font=(theme.FONT_UI, 11, "bold"),
            ).pack(side="left", padx=(0, 10))

        theme.make_button(
            btns, text=t("quiz.home_btn"), command=self._on_back,
            kind="primary", padx=20, pady=10,
            font=(theme.FONT_UI, 11, "bold"),
        ).pack(side="left")

    def _has_flashcards(self) -> bool:
        try:
            from db.flashcards import get_flashcards
            return bool(get_flashcards(self._user_id))
        except Exception:
            return False

    def refresh_lang(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._answer_choices_frame = None
        self._open_entry_ref = None
        self._feedback_frame = None
        self._validate_btn = None
        self._next_btn = None
        self._choice_rows = []
        self._results_wheel_controller = None
        self._body = None  # type: ignore[assignment]
        self._progress_lbl = None  # type: ignore[assignment]
        self._build_chrome()
        self._show_subject_selector()

    def _render_course_card(self, parent: tk.Frame, course: dict) -> None:
        card = theme.surface_frame(parent, bg=SURFACE)
        card.pack(fill="x", pady=(0, 10))
        card.configure(padx=24, pady=16)

        title = (course.get("title") or course.get("subject") or "Cours").strip()
        reason = (course.get("reason") or "").strip()
        priority = (course.get("priority") or "moyenne").strip()

        header = tk.Frame(card, bg=SURFACE)
        header.pack(fill="x")
        tk.Label(
            header, text=title, bg=SURFACE, fg=TEXT,
            font=(theme.FONT_UI, 12, "bold"), anchor="w",
        ).pack(side="left", fill="x", expand=True)
        high = t("quiz.priority.high")
        tk.Label(
            header,
            text=t("quiz.priority_label", priority=priority),
            bg=theme.WARNING_SOFT if priority == high else theme.ACCENT_SOFT,
            fg=theme.WARNING if priority == high else theme.ACCENT_HOVER,
            font=(theme.FONT_UI, 9, "bold"),
            padx=8,
            pady=3,
        ).pack(side="right")
        if reason:
            rich_text_widget(
                card,
                reason,
                bg=SURFACE,
                fg=MUTED,
                font=(theme.FONT_UI, 10),
            ).pack(fill="x", pady=(4, 0))
        meta = " · ".join(part for part in (course.get("document"), course.get("chapter_title")) if part)
        if meta:
            tk.Label(
                card,
                text=meta,
                bg=SURFACE,
                fg=MUTED,
                font=(theme.FONT_UI, 9, "italic"),
                anchor="w",
            ).pack(fill="x", pady=(6, 0))


def _question_generation_context(raw: dict) -> str:
    parts: list[str] = []
    course_context = _display_course_context(raw)
    if course_context:
        parts.append(t("quiz.ctx_header", ctx=course_context))
    parts.append(t("quiz.origin_question", q=raw["question"]))
    parts.append(t("quiz.expected_answer", a=raw["answer"]))
    return "\n\n".join(parts)


def _display_course_context(raw: dict) -> str:
    if raw.get("source") != "reading":
        return ""
    course_context = str(raw.get("course_context") or "").strip()
    if course_context:
        return course_context

    parts: list[str] = []
    if raw.get("document"):
        parts.append(t("quiz.ctx_course", doc=raw["document"]))
    if raw.get("chapter_title"):
        parts.append(t("quiz.ctx_chapter", chapter=raw["chapter_title"]))
    source_context = " ".join(str(raw.get("source_context") or "").split())
    if source_context:
        parts.append(t("quiz.ctx_excerpt", text=source_context[:900]))
    return "\n".join(parts)


_TYPE_KEYS = {"qcm", "open", "comprehension", "application", "curiosity", "visualization", "metacognition", "anticipation"}


def _preferred_quiz_question_type(raw: dict) -> str:
    qtype = str(raw.get("question_type") or "").strip().lower()
    if qtype in _TYPE_KEYS:
        return qtype
    return "qcm" if raw.get("choices") else "comprehension"


def _merge_analysis(fallback: dict, result: dict) -> dict:
    merged = dict(fallback or {})
    for key, value in (result or {}).items():
        if value not in (None, "", [], {}):
            merged[key] = value
    if not merged.get("categories"):
        merged["categories"] = (fallback or {}).get("categories") or []
    if not merged.get("courses_to_review"):
        merged["courses_to_review"] = (fallback or {}).get("courses_to_review") or []
    if not merged.get("strengths"):
        merged["strengths"] = (fallback or {}).get("strengths") or []
    if not merged.get("weaknesses"):
        merged["weaknesses"] = (fallback or {}).get("weaknesses") or []
    return merged


def _category_label(category: str) -> str:
    clean = str(category or "culture").strip().lower()
    key = f"quiz.cat.{clean}"
    result = t(key)
    return result if result != key else clean.capitalize()


def _score_message(pct: int) -> str:
    if pct >= 80:
        return t("quiz.score_msg.high")
    if pct >= 50:
        return t("quiz.score_msg.mid")
    return t("quiz.score_msg.low")
