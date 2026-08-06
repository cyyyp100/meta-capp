# ui/inline_qa_block.py — Bloc Q&R embarqué dans le flux de lecture
from __future__ import annotations

import logging
import time
import tkinter as tk

from i18n import t
from ui import theme
from ui.rich_text import rich_text_widget as _rich_text_widget
from ui.top_nav import Tooltip

QUESTION_BG = theme.QUESTION
QUESTION_BORDER = theme.QUESTION_BORDER
OK_BG = theme.SUCCESS_SOFT
OK_BORDER = theme.SUCCESS
BAD_BG = theme.DANGER_SOFT
BAD_BORDER = theme.DANGER
TEXT = theme.TEXT
MUTED = theme.MUTED

logger = logging.getLogger("UI.inline_qa_block")


class QABlock(tk.Frame):
    def __init__(self, master, question: dict, on_submit, on_rephrase, on_reveal_mask=None, **kwargs):
        super().__init__(
            master,
            bg=QUESTION_BG,
            highlightthickness=1,
            highlightbackground=QUESTION_BORDER,
            highlightcolor=QUESTION_BORDER,
            **kwargs,
        )
        self.question = question
        self._on_submit = on_submit
        self._on_rephrase = on_rephrase
        self._on_reveal_mask = on_reveal_mask
        self._answer_widget = None
        self._feedback_body = None
        self._follow_up_input = None
        self._follow_up_button = None
        self._follow_up_status = None
        self._follow_up_answer_frame = None
        self._follow_up_frame = None
        self._next_question_status = None
        self._mode = "question"
        self._pending_question_text = None
        self._choice_var = tk.StringVar(value="")
        self._started_at = time.monotonic()
        self._build_question()

    def is_alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _clear_children(self) -> bool:
        if not self.is_alive():
            return False
        try:
            children = list(self.winfo_children())
        except tk.TclError:
            return False
        for child in children:
            try:
                child.destroy()
            except tk.TclError:
                pass
        self._answer_widget = None
        self._feedback_body = None
        self._follow_up_input = None
        self._follow_up_button = None
        self._follow_up_status = None
        self._follow_up_answer_frame = None
        self._follow_up_frame = None
        self._next_question_status = None
        return True

    def show_loading(self, text: str | None = None) -> None:
        if not self._clear_children():
            return
        text = text or t("qa.loading_evaluation")
        self._mode = "loading"
        self.configure(bg=QUESTION_BG)
        self._stripe(QUESTION_BORDER)
        tk.Label(
            self,
            text=f"⟳ {text}",
            bg=QUESTION_BG,
            fg=MUTED,
            font=(theme.FONT_UI, 11, "italic"),
            padx=16,
            pady=14,
        ).pack(anchor="w", fill="x")

    def show_pending_question(self, text: str | None = None) -> None:
        if not self.is_alive():
            return
        text = text or t("qa.pending_question")
        if self._widget_exists(self._feedback_body):
            bg = self.cget("bg")
            if self._widget_exists(self._next_question_status):
                self._next_question_status.configure(text=f"⟳ {text}")
                return
            status = tk.Label(
                self._feedback_body,
                text=f"⟳ {text}",
                bg=bg,
                fg=MUTED,
                font=(theme.FONT_UI, 9, "italic"),
                anchor="w",
            )
            status.pack(fill="x", anchor="w", pady=(10, 0))
            self._next_question_status = status
            return

        if self._mode == "loading":
            self._pending_question_text = text
            return

        self.show_loading(text)

    def show_feedback(
        self,
        verdict: str,
        feedback: str,
        completion: str = "",
        hint: str = "",
        on_follow_up=None,
    ) -> None:
        if not self._clear_children():
            return

        self._mode = "feedback"
        self._follow_up_input = None
        self._follow_up_button = None
        self._follow_up_status = None
        self._follow_up_answer_frame = None

        is_ok = verdict in {"correct", "partial"}
        bg = OK_BG if is_ok else BAD_BG
        border = OK_BORDER if is_ok else BAD_BORDER
        symbol = "✓" if is_ok else "✗"
        self.configure(bg=bg)
        self._stripe(border)

        body = tk.Frame(self, bg=bg)
        self._feedback_body = body
        body.pack(fill="x", padx=(16, 14), pady=14)
        _rich_text_widget(
            body,
            f"{symbol} {feedback}",
            bg=bg,
            fg=TEXT,
            font=(theme.FONT_UI, 11, "bold"),
        ).pack(fill="x", anchor="w")

        if completion:
            _rich_text_widget(
                body,
                completion,
                bg=bg,
                fg=TEXT,
                font=(theme.FONT_UI, 10),
            ).pack(fill="x", anchor="w", pady=(6, 0))

        if verdict == "incorrect" and hint:
            _rich_text_widget(
                body,
                t("qa.hint_prefix", text=hint),
                bg=bg,
                fg=TEXT,
                font=(theme.FONT_UI, 10),
            ).pack(fill="x", anchor="w", pady=(6, 0))

        if on_follow_up is not None:
            self._build_follow_up_form(body, bg, on_follow_up)

        if self._pending_question_text:
            pending_text = self._pending_question_text
            self._pending_question_text = None
            self.show_pending_question(pending_text)

    def show_follow_up_answer(self, answer_text: str) -> None:
        if not self.is_alive():
            return
        answer_text = (answer_text or "").strip()
        if not answer_text:
            return

        parent = self._feedback_body or self
        bg = self.cget("bg")
        if self._follow_up_status is not None:
            self._follow_up_status.configure(text="")
        if self._follow_up_answer_frame is not None:
            self._follow_up_answer_frame.destroy()

        answer_frame = tk.Frame(parent, bg=bg)
        answer_frame.pack(fill="x", anchor="w", pady=(10, 0))
        self._follow_up_answer_frame = answer_frame
        tk.Label(
            answer_frame,
            text=t("qa.follow_up_answer_label"),
            bg=bg,
            fg=MUTED,
            font=(theme.FONT_UI, 9, "bold"),
            anchor="w",
        ).pack(fill="x")
        _rich_text_widget(
            answer_frame,
            answer_text,
            bg=bg,
            fg=TEXT,
            font=(theme.FONT_UI, 10),
        ).pack(fill="x", anchor="w", pady=(4, 0))

    def show_new_question(self, question: dict) -> None:
        if not self.is_alive():
            return
        self.question = question
        self._choice_var.set("")
        self._started_at = time.monotonic()
        self._build_question()

    def _build_question(self) -> None:
        if not self._clear_children():
            return
        self._mode = "question"
        self._pending_question_text = None
        self.configure(bg=QUESTION_BG)
        self._stripe(QUESTION_BORDER)

        body = tk.Frame(self, bg=QUESTION_BG)
        body.pack(fill="both", expand=True, padx=(18, 16), pady=16)

        qtype = self.question.get("question_type", "open")
        type_label = _type_label(qtype)
        if type_label:
            tk.Label(
                body,
                text=type_label,
                bg=QUESTION_BG,
                fg=MUTED,
                font=(theme.FONT_UI, 9, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(0, 5))

        _rich_text_widget(
            body,
            f"❓ {self.question.get('question', '')}",
            bg=QUESTION_BG,
            fg=TEXT,
            font=(theme.FONT_UI, 12, "bold"),
        ).pack(fill="x", anchor="w")

        if qtype == "qcm":
            self._build_choices(body)
        else:
            self._build_text_answer(body, qtype)

        actions = tk.Frame(body, bg=QUESTION_BG)
        actions.pack(fill="x", pady=(12, 0))

        rephrase_btn = theme.make_button(
            actions,
            text=t("qa.rephrase_question_btn"),
            command=self._on_rephrase,
            padx=12,
            pady=6,
            kind="warning",
        )
        rephrase_btn.pack(side="left")
        Tooltip(rephrase_btn, t("qa.rephrase_question_tip"))

        answer_btn = theme.make_button(
            actions,
            text=t("qa.submit_btn"),
            command=self._submit,
            padx=14,
            pady=6,
            kind="primary",
            font=(theme.FONT_UI, 10, "bold"),
        )
        answer_btn.pack(side="right")
        Tooltip(answer_btn, t("qa.submit_tip"))

    def _build_choices(self, parent) -> None:
        choices = self.question.get("choices") or []
        choices_frame = tk.Frame(parent, bg=QUESTION_BG)
        choices_frame.pack(fill="x", pady=(12, 0))
        for choice in choices:
            row = tk.Frame(
                choices_frame,
                bg=theme.SURFACE,
                highlightthickness=1,
                highlightbackground=theme.BORDER,
                padx=10,
                pady=7,
            )
            row.pack(fill="x", pady=4)
            btn = tk.Radiobutton(
                row,
                text="",
                variable=self._choice_var,
                value=choice,
                bg=theme.SURFACE,
                fg=TEXT,
                selectcolor=theme.ACCENT_SOFT,
                activebackground=theme.SURFACE,
                activeforeground=TEXT,
                anchor="w",
                justify="left",
                padx=0,
                pady=0,
                indicatoron=True,
                highlightthickness=0,
                relief=tk.FLAT,
                font=(theme.FONT_UI, 10),
            )
            btn.pack(side="left", anchor="n")
            text = _rich_text_widget(
                row,
                str(choice),
                bg=theme.SURFACE,
                fg=TEXT,
                font=(theme.FONT_UI, 10),
            )
            text.pack(side="left", fill="x", expand=True, padx=(4, 0))
            text.bind("<Button-1>", lambda _event, value=choice: self._choice_var.set(value))
            row.bind("<Button-1>", lambda _event, value=choice: self._choice_var.set(value))

    def _build_text_answer(self, parent, qtype: str) -> None:
        hint = _type_hint(qtype)
        if hint:
            tk.Label(
                parent,
                text=hint,
                bg=QUESTION_BG,
                fg=MUTED,
                font=(theme.FONT_UI, 9, "italic"),
                anchor="w",
            ).pack(fill="x", pady=(8, 0))

        answer = theme.style_entry(tk.Text(
            parent,
            height=4,
            wrap=tk.WORD,
            padx=10,
            pady=9,
            font=(theme.FONT_UI, 10),
        ))
        answer.pack(fill="x", pady=(8, 0))
        self._answer_widget = answer

    def _submit(self) -> None:
        if not self.is_alive():
            return
        answer = self._answer_text()
        if not answer:
            return
        elapsed_ms = int((time.monotonic() - self._started_at) * 1000)
        if self._on_reveal_mask:
            self._on_reveal_mask()
        self.show_loading()
        self._on_submit(answer, elapsed_ms)

    def clear_pending_status(self) -> None:
        if self._next_question_status is not None:
            try:
                self._next_question_status.destroy()
            except tk.TclError:
                pass
            self._next_question_status = None

    def remove_follow_up_form(self) -> None:
        if not self.is_alive():
            return
        if self._follow_up_frame is not None:
            self._follow_up_frame.destroy()
            self._follow_up_frame = None
            self._follow_up_input = None
            self._follow_up_button = None
            self._follow_up_status = None

    def _widget_exists(self, widget) -> bool:
        if widget is None:
            return False
        try:
            return bool(widget.winfo_exists())
        except tk.TclError:
            return False

    def _build_follow_up_form(self, parent, bg: str, on_follow_up) -> None:
        container = tk.Frame(parent, bg=bg)
        container.pack(fill="x")
        self._follow_up_frame = container

        tk.Frame(container, bg=QUESTION_BORDER, height=1).pack(fill="x", pady=(12, 10))
        tk.Label(
            container,
            text=t("qa.follow_up_title"),
            bg=bg,
            fg=MUTED,
            font=(theme.FONT_UI, 9, "bold"),
            anchor="w",
        ).pack(fill="x")

        entry = theme.style_entry(tk.Text(
            container,
            height=2,
            wrap=tk.WORD,
            padx=10,
            pady=8,
            font=(theme.FONT_UI, 10),
        ))
        entry.pack(fill="x", pady=(6, 0))
        self._follow_up_input = entry

        actions = tk.Frame(container, bg=bg)
        actions.pack(fill="x", pady=(8, 0))
        status = tk.Label(
            actions,
            text="",
            bg=bg,
            fg=MUTED,
            font=(theme.FONT_UI, 9, "italic"),
            anchor="w",
        )
        status.pack(side="left", fill="x", expand=True)
        self._follow_up_status = status

        button = theme.make_button(
            actions,
            text=t("qa.follow_up_send"),
            command=lambda: self._submit_follow_up(on_follow_up),
            padx=12,
            pady=6,
            kind="secondary",
        )
        button.pack(side="right")
        self._follow_up_button = button

    def _submit_follow_up(self, on_follow_up) -> None:
        if not self.is_alive():
            return
        if self._follow_up_input is None:
            return
        question = self._follow_up_input.get("1.0", "end").strip()
        if not question:
            return
        self._follow_up_input.configure(state=tk.DISABLED)
        if self._follow_up_button is not None:
            self._follow_up_button.configure(state=tk.DISABLED)
        if self._follow_up_status is not None:
            self._follow_up_status.configure(text=t("qa.follow_up_loading"))
        on_follow_up(question)

    def _answer_text(self) -> str:
        if self.question.get("question_type") == "qcm":
            return self._choice_var.get().strip()
        if self._answer_widget is None:
            return ""
        return self._answer_widget.get("1.0", "end").strip()

    def _stripe(self, color: str) -> None:
        stripe = tk.Frame(self, bg=color, width=5)
        stripe.pack(side="left", fill="y")


def _type_hint(qtype: str) -> str:
    return t(f"qa.hint.{qtype}") if qtype in {
        "open",
        "comprehension",
        "application",
        "visualization",
        "metacognition",
        "anticipation",
        "curiosity",
    } else ""


def _type_label(qtype: str) -> str:
    return t(f"qa.type.{qtype}") if qtype in {
        "qcm",
        "open",
        "comprehension",
        "application",
        "curiosity",
        "visualization",
        "metacognition",
        "anticipation",
    } else ""
