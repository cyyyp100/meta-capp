# ui/session_exit_sas.py — Sas de sortie de session
from __future__ import annotations

import tkinter as tk

from i18n import t
from metacog.reflection import normalize_meta_cognition_questions
from ui import theme
from ui.components import CanvasWheelController, LoadingState
from ui.top_nav import Tooltip

BG = theme.BG
TEXT = theme.TEXT
MUTED = theme.MUTED
ACCENT = theme.ACCENT


class SessionExitSas(tk.Frame):
    def __init__(self, master, on_done, **kwargs):
        super().__init__(master, bg=BG, **kwargs)
        self._on_done = on_done
        self._summary: dict = {}
        self._llm_summary: dict = {}
        self._entries: list[tuple[str, tk.Text]] = []
        self._stat_labels: dict[str, tk.Label] = {}
        self._stat_cells: list[tk.Frame] = []
        self._phase = "idle"
        self._questions_ready = False
        self._analysis_ready = False
        self._required_answer_count = 3
        self._done_btn: tk.Button | None = None
        self._question_loader: LoadingState | None = None
        self._questions_wheel_controller: CanvasWheelController | None = None
        self._stats_reveal_jobs: list[str] = []
        self._question_reveal_jobs: list[str] = []
        self._stats_revealing = False
        self._build()

    def load(self, summary: dict, llm_result: dict | None = None, loading: bool = False) -> None:
        if loading:
            self.start_loading(summary, llm_expected=True)
            return

        self._summary = summary or {}
        self._llm_summary = {}
        self._apply_metrics(reveal=False)
        self.set_analysis(llm_result or {})

        raw_questions = ()
        if llm_result:
            llm_summary = _normalize_llm_summary(llm_result)
            raw_questions = (
                llm_summary.get("metacognitive_questions")
                or llm_summary.get("questions")
                or llm_result.get("questions")
                or ()
            )
        if raw_questions:
            self.set_questions(list(raw_questions), source="llm")
        else:
            self.set_questions([], source="fallback")

    def start_loading(self, summary: dict, llm_expected: bool) -> None:
        self._cancel_reveal_jobs()
        self._summary = summary or {}
        self._llm_summary = {}
        self._entries.clear()
        self._phase = "stats_reveal"
        self._questions_ready = False
        self._analysis_ready = not llm_expected
        self._apply_metrics(reveal=True)

        qualitative = (
            t("exit.llm_loading")
            if llm_expected
            else t("exit.offline_mode")
        )
        self._qualitative_lbl.configure(text=qualitative)
        self._set_done_enabled(False)

        if llm_expected:
            self._phase = "questions_loading"
            self._show_questions_loader(t("exit.loading_questions"))
        else:
            self._phase = "questions_loading"
            self._show_questions_loader(t("exit.loading_fallback"))

    def set_analysis(self, llm_result: dict | None) -> None:
        self._analysis_ready = True
        self._llm_summary = _normalize_llm_summary(llm_result)
        if not self._stats_revealing:
            self._apply_metrics(reveal=False)

        qualitative = self._llm_summary.get("qualitative_summary")
        if not qualitative:
            qualitative = t("exit.hint")
        self._qualitative_lbl.configure(text=qualitative)


    def set_questions(self, questions: list[str], source: str = "llm") -> None:
        self._cancel_question_jobs()
        if self._question_loader is not None:
            self._question_loader.destroy()
            self._question_loader = None

        normalized = normalize_meta_cognition_questions(
            questions or [],
            seed_context=self._summary.get("session_id"),
        )
        fallback = source != "llm" or not normalized
        if fallback:
            normalized = normalize_meta_cognition_questions(
                _build_contextual_fallback_questions(self._summary, self._llm_summary),
                seed_context=self._summary.get("session_id"),
            )
        if not normalized:
            normalized = [t("exit.default_q1"), t("exit.default_q2"), t("exit.default_q3")]

        self._questions_ready = True
        self._phase = "answering"
        self._render_questions(normalized[: self._required_answer_count], source="fallback" if fallback else source)

    def _apply_metrics(self, reveal: bool) -> None:
        metrics = dict(self._summary)
        for key in _METRIC_KEYS:
            if metrics.get(key) is None and key in self._llm_summary:
                metrics[key] = self._llm_summary[key]

        duration = int(metrics.get("duration_s") or 0)
        success_rate = float(metrics.get("success_rate") or 0.0)
        correct = int(metrics.get("answers_correct") or 0)
        total = int(metrics.get("answers_total") or 0)
        score = self._summary.get("session_score") or {}

        values = {
            "duration": f"{duration // 60:02d}:{duration % 60:02d}",
            "paragraphs": str(int(metrics.get("paragraphs_read") or 0)),
            "flashcards": str(int(metrics.get("flashcards_created") or 0)),
            "rephrasings": str(int(metrics.get("rephrasings_count") or 0)),
            "success": f"{int(round(success_rate * 100))}% ({correct}/{total})",
            "score": f"{int(round(score.get('context_comprehension', 50)))}",
        }

        self._cancel_stat_jobs()
        if reveal:
            self._stats_revealing = True
            for label in self._stat_labels.values():
                label.configure(text="—", fg=theme.MUTED)
            for index, key in enumerate(("duration", "paragraphs", "flashcards", "rephrasings", "success", "score")):
                job = self.after(index * 600, lambda k=key: self._reveal_stat(k, values[k]))
                self._stats_reveal_jobs.append(job)
            clear_job = self.after(6 * 300 + theme.ANIM_NORMAL, lambda: setattr(self, "_stats_revealing", False))
            self._stats_reveal_jobs.append(clear_job)
        else:
            self._stats_revealing = False
            for key, value in values.items():
                self._stat_labels[key].configure(text=value, fg=TEXT)

    def _reveal_stat(self, key: str, value: str) -> None:
        label = self._stat_labels.get(key)
        if label is None:
            return
        label.configure(text=value, fg=theme.MUTED)

        def _update(progress: float) -> None:
            size = 12 + int(3 * theme.ease_out_cubic(progress))
            label.configure(font=(theme.FONT_UI, size, "bold"), fg=TEXT if progress >= 1 else theme.MUTED)

        theme.animate(label, theme.ANIM_NORMAL, _update)

    def _build(self) -> None:
        center = tk.Frame(self, bg=BG)
        center.pack(fill="both", expand=True, padx=56, pady=36)

        tk.Label(
            center,
            text=t("exit.title"),
            bg=BG,
            fg=TEXT,
            font=(theme.FONT_TITLE, 28, "bold"),
            anchor="w",
        ).pack(anchor="w")

        stats = theme.surface_frame(center, bg=theme.SURFACE)
        stats.pack(fill="x", pady=(18, 16), ipady=10)

        for column, (key, label_key) in enumerate((
            ("duration",    "exit.stat.duration"),
            ("paragraphs",  "exit.stat.paragraphs"),
            ("flashcards",  "exit.stat.flashcards"),
            ("rephrasings", "exit.stat.rephrasings"),
            ("success",     "exit.stat.success"),
            ("score",       "exit.stat.score"),
        )):
            label = t(label_key)
            stats.grid_columnconfigure(column, weight=1)

            tk.Label(
                stats,
                text=label,
                bg=theme.SURFACE,
                fg=MUTED,
                font=(theme.FONT_UI, 9, "bold"),
            ).grid(
                row=0,
                column=column,
                sticky="w",
                padx=12,
                pady=(4, 0),
            )

            value = tk.Label(
                stats,
                text="—",
                bg=theme.SURFACE,
                fg=TEXT,
                font=(theme.FONT_UI, 15, "bold"),
            )
            value.grid(row=1, column=column, sticky="w", padx=12)
            self._stat_labels[key] = value
            self._stat_cells.append(stats)

        self._qualitative_lbl = tk.Label(
            center,
            text="",
            bg=theme.ACCENT_SOFT,
            fg=TEXT,
            font=(theme.FONT_UI, 13, "italic"),
            wraplength=800,
            justify="left",
            anchor="nw",
            padx=20,
            pady=18,
            highlightthickness=0,
        )
        self._qualitative_lbl.pack(fill="x")

        # Zone scrollable pour les questions
        scroll_outer = tk.Frame(center, bg=BG)
        scroll_outer.pack(fill="both", expand=True, pady=(4, 0))

        canvas = tk.Canvas(scroll_outer, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(scroll_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._questions_frame = tk.Frame(canvas, bg=BG)
        _win = canvas.create_window((0, 0), window=self._questions_frame, anchor="nw")
        self._questions_wheel_controller = CanvasWheelController(canvas, self._questions_frame)

        def _on_configure(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(_win, width=canvas.winfo_width())

        self._questions_frame.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_configure)

        done_btn = theme.make_button(
            center,
            text=t("exit.done_btn"),
            command=self._finish,
            padx=24,
            pady=10,
            kind="primary",
            font=(theme.FONT_UI, 12, "bold"),
        )
        done_btn.pack(anchor="e", pady=(14, 0))
        done_btn.configure(
            state="disabled",
            bg=theme.BORDER,
            fg=theme.DISABLED_TEXT,
            highlightbackground=theme.BORDER,
            cursor="arrow",
        )
        self._done_btn = done_btn
        Tooltip(done_btn, t("exit.done_tip"))

    def _show_questions_loader(self, text: str) -> None:
        for child in self._questions_frame.winfo_children():
            child.destroy()
        self._entries.clear()
        self._question_loader = LoadingState(self._questions_frame, text=text, bg=BG)
        self._question_loader.pack(fill="x", pady=(16, 0))
        self._question_loader.start(text)

    def _render_questions(self, questions: list[str], source: str = "llm") -> None:
        for child in self._questions_frame.winfo_children():
            child.destroy()

        self._entries.clear()
        self._set_done_enabled(False)

        if source == "fallback":
            tk.Label(
                self._questions_frame,
                text=t("exit.fallback_warning"),
                bg=theme.WARNING_SOFT,
                fg=theme.WARNING,
                font=(theme.FONT_UI, 10, "bold"),
                padx=10,
                pady=7,
            ).pack(anchor="w", fill="x", pady=(14, 2))

        rows: list[tk.Frame] = []
        for question in questions[: self._required_answer_count]:
            row = tk.Frame(self._questions_frame, bg=BG)
            rows.append(row)
            tk.Label(
                row,
                text=question,
                bg=BG,
                fg=TEXT,
                font=(theme.FONT_UI, 11, "bold"),
                wraplength=700,
                justify="left",
            ).pack(anchor="w", pady=(14, 4))

            entry = theme.style_entry(tk.Text(
                row,
                height=3,
                wrap=tk.WORD,
                padx=8,
                pady=6,
                font=(theme.FONT_UI, 11),
            ))
            entry.pack(fill="x")
            entry.bind("<KeyRelease>", lambda _event: self._refresh_done_state(), add="+")
            entry.bind("<FocusOut>", lambda _event: self._refresh_done_state(), add="+")
            self._entries.append((question, entry))

        for index, row in enumerate(rows):
            job = self.after(index * 110, lambda r=row: r.pack(fill="x"))
            self._question_reveal_jobs.append(job)

        self._refresh_done_state()

    def _refresh_done_state(self) -> None:
        self._set_done_enabled(self._can_finish())

    def _can_finish(self) -> bool:
        if len(self._entries) < self._required_answer_count:
            return False
        return all(entry.get("1.0", "end").strip() for _question, entry in self._entries[: self._required_answer_count])

    def _set_done_enabled(self, enabled: bool) -> None:
        if self._done_btn is not None:
            if enabled:
                self._done_btn.configure(
                    state="normal",
                    bg=theme.ACCENT_SOFT,
                    fg=theme.ACCENT,
                    activebackground=theme.ACCENT_SOFT_HOVER,
                    activeforeground=theme.ACCENT_HOVER,
                    highlightbackground=theme.ACCENT,
                    cursor="hand2",
                )
            else:
                self._done_btn.configure(
                    state="disabled",
                    bg=theme.BORDER,
                    fg=theme.DISABLED_TEXT,
                    highlightbackground=theme.BORDER,
                    cursor="arrow",
                )
        if enabled:
            self._phase = "ready_to_finish"
        elif self._questions_ready:
            self._phase = "answering"

    def _finish(self) -> None:
        if not self._can_finish():
            return
        responses = []

        for index, (question, entry) in enumerate(self._entries, start=1):
            answer = entry.get("1.0", "end").strip()
            responses.append({
                "question": question,
                "answer": answer,
                "order": index,
            })

        self._on_done({
            "summary": self._summary,
            "llm_summary": self._llm_summary,
            "responses": responses,
        })

    def _cancel_stat_jobs(self) -> None:
        for job in self._stats_reveal_jobs:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        self._stats_reveal_jobs.clear()
        self._stats_revealing = False

    def _cancel_question_jobs(self) -> None:
        for job in self._question_reveal_jobs:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        self._question_reveal_jobs.clear()

    def _cancel_reveal_jobs(self) -> None:
        self._cancel_stat_jobs()
        self._cancel_question_jobs()

    def refresh_lang(self) -> None:
        summary = self._summary
        llm_summary = self._llm_summary
        for child in self.winfo_children():
            child.destroy()
        self._entries = []
        self._stat_labels = {}
        self._stat_cells = []
        self._done_btn = None
        self._question_loader = None
        self._questions_wheel_controller = None
        self._stats_reveal_jobs = []
        self._question_reveal_jobs = []
        self._stats_revealing = False
        self._build()
        if summary or llm_summary:
            self._apply_metrics(reveal=False)
            qualitative = llm_summary.get("qualitative_summary") or t("exit.hint")
            self._qualitative_lbl.configure(text=qualitative)


_METRIC_KEYS = {
    "duration_s",
    "paragraphs_read",
    "flashcards_created",
    "rephrasings_count",
    "success_rate",
}


def _build_contextual_fallback_questions(summary: dict, llm_summary: dict) -> list[str]:
    """
    Génère des questions de secours contextualisées.

    Elles ne remplacent pas les questions LLM :
    elles servent uniquement si le LLM ne renvoie aucune question exploitable.
    """
    success_rate = float(summary.get("success_rate") or llm_summary.get("success_rate") or 0.0)
    paragraphs = int(summary.get("paragraphs_read") or llm_summary.get("paragraphs_read") or 0)
    flashcards = int(summary.get("flashcards_created") or llm_summary.get("flashcards_created") or 0)
    rephrasings = int(summary.get("rephrasings_count") or llm_summary.get("rephrasings_count") or 0)

    questions: list[str] = []

    if success_rate < 0.5:
        questions.append(t("exit.fallback.low_success"))
    elif success_rate < 0.8:
        questions.append(t("exit.fallback.mid_success"))
    else:
        questions.append(t("exit.fallback.high_success"))

    if rephrasings > 0:
        questions.append(t("exit.fallback.rephrasings"))
    elif flashcards > 0:
        questions.append(t("exit.fallback.flashcards"))
    else:
        questions.append(t("exit.fallback.no_cards"))

    if paragraphs >= 3:
        questions.append(t("exit.fallback.many_paragraphs"))
    else:
        questions.append(t("exit.fallback.few_paragraphs"))

    return questions


def _normalize_llm_summary(llm_result: dict | None) -> dict:
    if not llm_result:
        return {}

    summary = llm_result.get("session_summary") if isinstance(llm_result, dict) else None

    if isinstance(summary, dict):
        return summary

    return llm_result if isinstance(llm_result, dict) else {}
