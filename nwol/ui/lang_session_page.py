# ui/lang_session_page.py — Page de session langue (20 min)
from __future__ import annotations

import tkinter as tk

from i18n import t
from ui import theme
from ui.top_nav import Tooltip
from llm.lang_session import BLOCKS, SESSION_TOTAL_S, LangSession


# ── TimerBar ──────────────────────────────────────────────────────────────────

class TimerBar(tk.Frame):
    _BAR_H = 8
    _LABEL_H = 20
    _TOTAL_H = _BAR_H + _LABEL_H + 4

    def __init__(self, master, **kwargs):
        super().__init__(master, bg=theme.BG, height=self._TOTAL_H, **kwargs)
        self.pack_propagate(False)
        self._canvas: tk.Canvas | None = None
        self._label_ids: list[int] = []
        self._build()

    def _build(self) -> None:
        if self._canvas:
            self._canvas.destroy()
        self._label_ids = []
        self._canvas = tk.Canvas(
            self,
            height=self._TOTAL_H,
            bg=theme.BG,
            highlightthickness=0,
        )
        self._canvas.pack(fill="x", expand=True)
        self._canvas.bind("<Configure>", self._on_resize)
        self._draw(0, 0)

    def _on_resize(self, event) -> None:
        self._draw(0, 0)

    def update_state(self, elapsed_total: float, block_index: int) -> None:
        self._draw(elapsed_total, block_index)

    def _draw(self, elapsed_total: float, active_index: int) -> None:
        c = self._canvas
        if c is None:
            return
        c.delete("all")
        W = c.winfo_width() or 800
        if W < 10:
            return

        y_bar = 2
        total_s = SESSION_TOTAL_S

        # Background track
        c.create_rectangle(0, y_bar, W, y_bar + self._BAR_H,
                            fill=theme.BORDER, outline="")

        # Elapsed fill
        ratio = min(1.0, elapsed_total / total_s) if total_s > 0 else 0
        c.create_rectangle(0, y_bar, int(W * ratio), y_bar + self._BAR_H,
                            fill=theme.ACCENT, outline="")

        # Block dividers + labels
        acc = 0
        y_lbl = y_bar + self._BAR_H + 4
        for i, (name, dur) in enumerate(BLOCKS):
            acc += dur
            x = int(W * acc / total_s)
            if i < len(BLOCKS) - 1:
                c.create_line(x, y_bar, x, y_bar + self._BAR_H,
                              fill=theme.BG, width=2)

        # Block labels centered within each segment
        acc = 0
        for i, (name, dur) in enumerate(BLOCKS):
            x_start = int(W * acc / total_s)
            x_end = int(W * (acc + dur) / total_s)
            acc += dur
            cx = (x_start + x_end) // 2
            is_active = (i == active_index)
            fill = theme.ACCENT if is_active else theme.MUTED_LIGHT
            label_key = f"lang.session.block.{name}"
            label_text = t(label_key)
            fnt = (theme.FONT_UI, 9, "bold") if is_active else (theme.FONT_UI, 9)
            c.create_text(cx, y_lbl, text=label_text, fill=fill,
                          font=fnt, anchor="n")


# ── DialogView ────────────────────────────────────────────────────────────────

_SPEAKER_COLORS = {
    "A": theme.ACCENT,
    "B": theme.TEXT,
}

class DialogView(tk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=theme.SURFACE, **kwargs)
        self._show_phonetic = tk.BooleanVar(value=False)
        self._show_translation = tk.BooleanVar(value=True)
        self._dialogue: list[dict] = []
        self._build()

    def _build(self) -> None:
        # Toggle controls
        ctrl = tk.Frame(self, bg=theme.SURFACE)
        ctrl.pack(fill="x", padx=20, pady=(12, 6))

        tk.Checkbutton(
            ctrl,
            text=t("lang.session.phonetic_btn"),
            variable=self._show_phonetic,
            bg=theme.SURFACE,
            fg=theme.MUTED,
            activebackground=theme.SURFACE,
            font=(theme.FONT_UI, 11),
            command=self._refresh_lines,
        ).pack(side="left", padx=(0, 16))

        tk.Checkbutton(
            ctrl,
            text=t("lang.session.translation_btn"),
            variable=self._show_translation,
            bg=theme.SURFACE,
            fg=theme.MUTED,
            activebackground=theme.SURFACE,
            font=(theme.FONT_UI, 11),
            command=self._refresh_lines,
        ).pack(side="left")

        # Scrollable area
        scroll_wrap = tk.Frame(self, bg=theme.SURFACE)
        scroll_wrap.pack(fill="both", expand=True, padx=4)

        self._canvas = tk.Canvas(scroll_wrap, bg=theme.SURFACE, highlightthickness=0)
        scrollbar = tk.Scrollbar(scroll_wrap, orient="vertical",
                                 command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._inner = tk.Frame(self._canvas, bg=theme.SURFACE)
        self._inner_id = self._canvas.create_window(
            (0, 0), window=self._inner, anchor="nw"
        )

        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind("<Button-4>", self._on_mousewheel)
        self._canvas.bind("<Button-5>", self._on_mousewheel)

    def _on_inner_configure(self, _event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._canvas.itemconfigure(self._inner_id, width=event.width)

    def _on_mousewheel(self, event) -> None:
        if event.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._canvas.yview_scroll(1, "units")
        else:
            self._canvas.yview_scroll(int(-event.delta / 60), "units")

    def load_dialogue(self, dialogue: list[dict]) -> None:
        self._dialogue = dialogue
        self._refresh_lines()

    def _refresh_lines(self) -> None:
        for child in self._inner.winfo_children():
            child.destroy()

        show_phonetic = self._show_phonetic.get()
        show_translation = self._show_translation.get()

        for i, line in enumerate(self._dialogue):
            row = tk.Frame(
                self._inner,
                bg=theme.SURFACE_SOFT if i % 2 == 0 else theme.SURFACE,
                padx=16,
                pady=8,
            )
            row.pack(fill="x")

            speaker = (line.get("speaker") or "A").upper()
            spk_color = _SPEAKER_COLORS.get(speaker, theme.TEXT)

            # Speaker label
            tk.Label(
                row,
                text=speaker,
                bg=row.cget("bg"),
                fg=spk_color,
                font=(theme.FONT_UI, 12, "bold"),
                width=3,
                anchor="n",
            ).pack(side="left", anchor="n", pady=(3, 0))

            # Text column
            col = tk.Frame(row, bg=row.cget("bg"))
            col.pack(side="left", fill="x", expand=True, padx=(8, 0))

            target = (line.get("target") or "").strip()
            tk.Label(
                col,
                text=target,
                bg=col.cget("bg"),
                fg=theme.TEXT,
                font=(theme.FONT_UI, 13),
                wraplength=580,
                justify="left",
                anchor="w",
            ).pack(fill="x", anchor="w")

            if show_phonetic:
                phonetic = (line.get("phonetic") or "").strip()
                if phonetic:
                    tk.Label(
                        col,
                        text=phonetic,
                        bg=col.cget("bg"),
                        fg=theme.MUTED,
                        font=(theme.FONT_UI, 11, "italic"),
                        wraplength=580,
                        justify="left",
                        anchor="w",
                    ).pack(fill="x", anchor="w")

            if show_translation:
                translation = (line.get("translation") or "").strip()
                if translation:
                    tk.Label(
                        col,
                        text=translation,
                        bg=col.cget("bg"),
                        fg=theme.MUTED_LIGHT,
                        font=(theme.FONT_UI, 11),
                        wraplength=580,
                        justify="left",
                        anchor="w",
                    ).pack(fill="x", anchor="w")

        self._canvas.yview_moveto(0)


# ── TranslationExerciseView ───────────────────────────────────────────────────

class TranslationExerciseView(tk.Frame):
    """Active-phase rappel block: user translates each dialogue line into the target language."""

    def __init__(self, master, profile: dict, lesson_data: dict, **kwargs):
        super().__init__(master, bg=theme.SURFACE, **kwargs)
        self._profile = profile
        self._lesson_data = lesson_data
        self._entries: list[tuple[dict, tk.Text]] = []  # (line_dict, entry_widget)
        self._result_frames: list[tk.Frame] = []
        self._validate_btn: tk.Widget | None = None
        self._build()

    def _build(self) -> None:
        canvas = tk.Canvas(self, bg=theme.SURFACE, highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=theme.SURFACE)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(
            inner_id, width=e.width))

        dialogue = self._lesson_data.get("dialogue", [])
        for line in dialogue:
            translation = (line.get("translation") or "").strip()
            if not translation:
                continue
            row = tk.Frame(inner, bg=theme.SURFACE, padx=24, pady=10)
            row.pack(fill="x")

            tk.Label(
                row,
                text=translation,
                bg=theme.SURFACE,
                fg=theme.MUTED,
                font=(theme.FONT_UI, 11, "italic"),
                wraplength=580,
                justify="left",
                anchor="w",
            ).pack(fill="x", anchor="w")

            entry = tk.Text(
                row,
                height=1,
                font=(theme.FONT_UI, 12),
                bg=theme.BG_ALT,
                fg=theme.TEXT,
                relief="flat",
                wrap="word",
                padx=8,
                pady=6,
            )
            entry.pack(fill="x", anchor="w", pady=(4, 0))

            result_frame = tk.Frame(row, bg=theme.SURFACE)
            result_frame.pack(fill="x", anchor="w")

            self._entries.append((line, entry))
            self._result_frames.append(result_frame)

            theme.divider(inner, pady=(0, 0))

        btn_row = tk.Frame(inner, bg=theme.SURFACE, padx=24, pady=16)
        btn_row.pack(fill="x")
        self._validate_btn = theme.make_button(
            btn_row,
            text=t("lang.session.validate_btn"),
            command=self._validate_all,
            kind="primary",
            font=(theme.FONT_UI, 12, "bold"),
            padx=22,
            pady=9,
        )
        self._validate_btn.pack(side="left")

    def _validate_all(self) -> None:
        if self._validate_btn:
            self._validate_btn.configure(state="disabled")
        language = self._profile.get("language", "")
        profile_id = self._profile.get("id")
        lesson_n = self._profile.get("current_lesson", 1)

        for i, (line, entry) in enumerate(self._entries):
            target = (line.get("target") or "").strip()
            attempt = entry.get("1.0", "end-1c").strip()
            result_frame = self._result_frames[i]

            if not attempt:
                continue

            entry.configure(state="disabled")

            lbl = tk.Label(
                result_frame,
                text=t("lang.session.correction_loading"),
                bg=theme.SURFACE,
                fg=theme.MUTED,
                font=(theme.FONT_UI, 11, "italic"),
            )
            lbl.pack(anchor="w", pady=(4, 0))

            from llm.ollama_client import generate_lang_correction_async

            def _success(result: dict, _frame=result_frame, _lbl=lbl,
                         _target=target, _attempt=attempt,
                         _pid=profile_id, _ln=lesson_n):
                self.after(0, lambda: self._show_correction(
                    result, _frame, _lbl, _target, _pid, _ln))

            def _error(_msg: str, _frame=result_frame, _lbl=lbl):
                self.after(0, lambda: _lbl.configure(
                    text="—", fg=theme.MUTED))

            try:
                generate_lang_correction_async(language, target, attempt,
                                               _success, _error)
            except Exception:
                lbl.configure(text="—", fg=theme.MUTED)

    def _show_correction(
        self,
        result: dict,
        frame: tk.Frame,
        loading_lbl: tk.Label,
        target: str,
        profile_id: int | None,
        lesson_n: int,
    ) -> None:
        loading_lbl.destroy()
        verdict = result.get("verdict", "incorrect")
        feedback = (result.get("feedback") or "").strip()
        corrections = result.get("corrections", [])

        verdict_map = {
            "correct":   (t("lang.session.correct"),   theme.SUCCESS),
            "partial":   (t("lang.session.partial"),   theme.WARNING),
            "incorrect": (t("lang.session.incorrect"), theme.DANGER),
        }
        verdict_text, verdict_color = verdict_map.get(
            verdict, (t("lang.session.incorrect"), theme.DANGER))

        tk.Label(
            frame,
            text=verdict_text,
            bg=theme.SURFACE,
            fg=verdict_color,
            font=(theme.FONT_UI, 11, "bold"),
        ).pack(anchor="w", pady=(4, 0))

        if feedback:
            tk.Label(
                frame,
                text=feedback,
                bg=theme.SURFACE,
                fg=theme.MUTED,
                font=(theme.FONT_UI, 11, "italic"),
                wraplength=580,
                justify="left",
                anchor="w",
            ).pack(fill="x", anchor="w")

        for corr in corrections:
            original = corr.get("original", "")
            corrected = corr.get("corrected", "")
            reason = corr.get("reason", "")
            if original and corrected:
                tk.Label(
                    frame,
                    text=f"{original} → {corrected}",
                    bg=theme.SURFACE,
                    fg=theme.TEXT,
                    font=(theme.FONT_MONO, 11),
                    anchor="w",
                ).pack(anchor="w")
            if reason:
                tk.Label(
                    frame,
                    text=reason,
                    bg=theme.SURFACE,
                    fg=theme.MUTED,
                    font=(theme.FONT_UI, 10, "italic"),
                    wraplength=580,
                    anchor="w",
                ).pack(anchor="w")

        if verdict != "correct" and profile_id:
            from db.lang_db import save_lang_error
            for corr in corrections:
                word = (corr.get("original") or "").strip()
                if word:
                    try:
                        save_lang_error(profile_id, lesson_n, "traduction",
                                        word, target)
                    except Exception:
                        pass


# ── LangSessionPage ───────────────────────────────────────────────────────────

class LangSessionPage(tk.Frame):
    def __init__(self, master, on_end, on_back, **kwargs):
        super().__init__(master, bg=theme.BG, **kwargs)
        self._on_end = on_end     # callable(summary: dict)
        self._on_back = on_back
        self._session: LangSession | None = None
        self._tick_id = None
        self._lesson_data: dict = {}
        self._profile: dict = {}
        self._curriculum: list = []
        self._active_tab = "dialogue"
        self._tab_btns: dict[str, tk.Widget] = {}
        self._content_frames: dict[str, tk.Frame] = {}
        self._dialog_view: DialogView | None = None
        self._translation_view: TranslationExerciseView | None = None
        self._notes_panel: tk.Frame | None = None
        self._exercises_panel: tk.Frame | None = None
        self._timer_bar: TimerBar | None = None
        self._loading_lbl: tk.Label | None = None
        self._build()

    # ── Public entry point ────────────────────────────────────────────────────

    def load(self, profile: dict, curriculum: list) -> None:
        self._profile = profile
        self._curriculum = curriculum
        self._stop_session()
        self._reset_exercises_panel()
        if self._translation_view:
            self._translation_view.destroy()
            self._translation_view = None
        self._show_loading()
        lesson_n = profile.get("current_lesson", 1)
        self._try_load_lesson(lesson_n)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # Top bar
        top = tk.Frame(self, bg=theme.BG)
        top.pack(fill="x", padx=40, pady=(20, 0))

        back_btn = theme.make_button(
            top,
            text=t("lang.session.back"),
            command=self._on_back_click,
            kind="ghost",
            font=(theme.FONT_UI, 11, "bold"),
        )
        back_btn.pack(side="left")
        Tooltip(back_btn, t("lang.session.back_tip"))

        # TimerBar
        self._timer_bar = TimerBar(self)
        self._timer_bar.pack(fill="x", padx=40, pady=(14, 0))

        # Tab bar
        tab_bar = tk.Frame(self, bg=theme.BG)
        tab_bar.pack(fill="x", padx=40, pady=(14, 0))
        for tab_id in ("dialogue", "notes", "exercices"):
            key = f"lang.session.tab_{tab_id}"
            btn = tk.Button(
                tab_bar,
                text=t(key),
                bg=theme.ACCENT if tab_id == "dialogue" else theme.BG_ALT,
                fg=theme.SURFACE if tab_id == "dialogue" else theme.MUTED,
                font=(theme.FONT_UI, 11, "bold"),
                relief="flat",
                cursor="hand2",
                padx=18,
                pady=7,
                borderwidth=0,
                command=lambda tid=tab_id: self._switch_tab(tid),
            )
            btn.pack(side="left", padx=(0, 4))
            self._tab_btns[tab_id] = btn

        theme.divider(self, pady=(10, 0))

        # Content area
        self._content_area = tk.Frame(self, bg=theme.BG)
        self._content_area.pack(fill="both", expand=True, padx=40, pady=(0, 20))

        # Loading label (shown before lesson data arrives)
        self._loading_lbl = tk.Label(
            self._content_area,
            text=t("lang.session.loading"),
            bg=theme.BG,
            fg=theme.MUTED,
            font=(theme.FONT_UI, 14, "italic"),
        )
        self._loading_lbl.place(relx=0.5, rely=0.4, anchor="center")

        # Dialogue tab
        dialogue_frame = tk.Frame(self._content_area, bg=theme.SURFACE,
                                  highlightthickness=1,
                                  highlightbackground=theme.BORDER)
        dialogue_frame.place(relwidth=1, relheight=1)
        self._dialog_view = DialogView(dialogue_frame)
        self._dialog_view.pack(fill="both", expand=True)
        self._content_frames["dialogue"] = dialogue_frame

        # Notes tab
        notes_frame = tk.Frame(self._content_area, bg=theme.SURFACE,
                               highlightthickness=1,
                               highlightbackground=theme.BORDER)
        notes_frame.place(relwidth=1, relheight=1)
        self._notes_panel = notes_frame
        self._content_frames["notes"] = notes_frame

        # Exercices tab
        exercises_frame = tk.Frame(self._content_area, bg=theme.SURFACE,
                                   highlightthickness=1,
                                   highlightbackground=theme.BORDER)
        exercises_frame.place(relwidth=1, relheight=1)
        self._exercises_panel = exercises_frame
        tk.Label(
            exercises_frame,
            text=t("lang.session.exercise_placeholder"),
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=(theme.FONT_UI, 13, "italic"),
        ).place(relx=0.5, rely=0.4, anchor="center")
        self._content_frames["exercices"] = exercises_frame

        # Start with loading visible
        self._loading_lbl.lift()

    # ── Lesson loading ────────────────────────────────────────────────────────

    def _show_loading(self) -> None:
        if self._loading_lbl:
            self._loading_lbl.lift()
            self._loading_lbl.configure(text=t("lang.session.loading"))

    def _hide_loading(self) -> None:
        if self._loading_lbl:
            self._loading_lbl.lower()

    def _try_load_lesson(self, lesson_n: int) -> None:
        from db.lang_db import get_lesson_cache
        profile_id = self._profile.get("id")
        cached = get_lesson_cache(profile_id, lesson_n) if profile_id else None
        if cached:
            self._start_session(cached)
            return

        language = self._profile.get("language", "")
        curriculum_row = next(
            (r for r in self._curriculum if r.get("lesson_n") == lesson_n),
            self._curriculum[0] if self._curriculum else {},
        )
        from llm.ollama_client import generate_lang_lesson_async

        def _success(result: dict) -> None:
            self.after(0, lambda: self._on_lesson_generated(lesson_n, result))

        def _error(msg: str) -> None:
            self.after(0, self._on_lesson_error)

        generate_lang_lesson_async(language, lesson_n, curriculum_row, _success, _error)

    def _on_lesson_generated(self, lesson_n: int, result: dict) -> None:
        from db.lang_db import save_lesson_cache
        profile_id = self._profile.get("id")
        if profile_id:
            save_lesson_cache(
                profile_id, lesson_n,
                dialogue=result.get("dialogue", []),
                notes=result.get("notes", {}),
                vocabulary=result.get("vocabulary", []),
            )
        self._start_session(result)

    def _on_lesson_error(self) -> None:
        if self._loading_lbl:
            self._loading_lbl.configure(
                text="Erreur lors de la génération de la leçon.",
                fg=theme.DANGER,
            )

    # ── Session control ───────────────────────────────────────────────────────

    def _start_session(self, lesson_data: dict) -> None:
        self._lesson_data = lesson_data
        self._populate_dialogue(lesson_data.get("dialogue", []))
        self._populate_notes(lesson_data.get("notes", {}))
        self._hide_loading()
        self._switch_tab("dialogue")

        self._create_flashcards_from_vocabulary()

        self._session = LangSession(
            profile=self._profile,
            lesson_data=lesson_data,
            on_block_change=self._on_block_change,
            on_session_end=self._on_session_end,
            on_repetition_start=self._prefetch_exercises,
        )
        self._session.start()
        self._schedule_tick()

    def _reset_exercises_panel(self) -> None:
        if self._exercises_panel is None:
            return
        for child in self._exercises_panel.winfo_children():
            child.destroy()
        tk.Label(
            self._exercises_panel,
            text=t("lang.session.exercise_placeholder"),
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=(theme.FONT_UI, 13, "italic"),
        ).place(relx=0.5, rely=0.4, anchor="center")

    def _create_flashcards_from_vocabulary(self) -> None:
        from db.flashcards import save_flashcard
        from db.user import DEFAULT_USER_ID
        language = self._profile.get("language", "lang")
        lesson_n = self._profile.get("current_lesson", 1)
        vocabulary = self._lesson_data.get("vocabulary", [])
        tags = [f"lang:{language.lower()}", f"lesson:{lesson_n}", "vocabulaire"]
        for item in vocabulary:
            word = (item.get("word") or "").strip()
            translation = (item.get("translation") or "").strip()
            if word and translation:
                try:
                    save_flashcard(
                        user_id=DEFAULT_USER_ID,
                        question_id=None,
                        front=word,
                        back=translation,
                        tags=tags,
                        source="lang_auto",
                    )
                except Exception:
                    pass

    def _prefetch_exercises(self) -> None:
        from db.lang_db import (get_exercises_cache, get_lang_session_count,
                                get_lang_errors_for_revision)
        profile_id = self._profile.get("id")
        lesson_n = self._profile.get("current_lesson", 1)
        if not profile_id:
            return
        language = self._profile.get("language", "")

        session_count = get_lang_session_count(profile_id)
        use_revision = (
            session_count > 0
            and session_count % 7 == 0
            and bool(get_lang_errors_for_revision(profile_id, limit=1))
        )
        ex_type = "revision" if use_revision else "qcm"

        cached = get_exercises_cache(profile_id, lesson_n, ex_type)
        if cached:
            self.after(0, lambda: self._on_exercises_ready(cached))
            return

        dialogue = self._lesson_data.get("dialogue", [])
        vocabulary = self._lesson_data.get("vocabulary", [])

        def _success(result: dict) -> None:
            from db.lang_db import save_exercises_cache
            save_exercises_cache(profile_id, lesson_n, ex_type, result)
            self.after(0, lambda: self._on_exercises_ready(result))

        def _error(msg: str) -> None:
            pass

        if use_revision:
            errors = get_lang_errors_for_revision(profile_id)
            from llm.ollama_client import generate_lang_revision_quiz_async
            generate_lang_revision_quiz_async(language, errors, _success, _error)
        else:
            from llm.ollama_client import generate_lang_exercises_async
            generate_lang_exercises_async(language, lesson_n, dialogue, vocabulary,
                                          _success, _error)

    def _on_exercises_ready(self, data: dict) -> None:
        if self._exercises_panel is None:
            return
        for child in self._exercises_panel.winfo_children():
            child.destroy()
        self._build_exercises_ui(data)

    def _build_exercises_ui(self, data: dict) -> None:
        exercises = data.get("exercises", [])
        if not exercises:
            tk.Label(
                self._exercises_panel,
                text=t("lang.session.exercise_placeholder"),
                bg=theme.SURFACE,
                fg=theme.MUTED,
                font=(theme.FONT_UI, 13, "italic"),
            ).place(relx=0.5, rely=0.4, anchor="center")
            return

        canvas = tk.Canvas(self._exercises_panel, bg=theme.SURFACE,
                           highlightthickness=0)
        scrollbar = tk.Scrollbar(self._exercises_panel, orient="vertical",
                                 command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=theme.SURFACE)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(
            inner_id, width=e.width))

        for ex in exercises:
            self._add_qcm_widget(inner, ex)

    def _add_qcm_widget(self, parent: tk.Frame, ex: dict) -> None:
        card = tk.Frame(parent, bg=theme.SURFACE, padx=28, pady=20)
        card.pack(fill="x")
        theme.divider(parent, pady=(0, 0))

        tk.Label(
            card,
            text=ex.get("question", ""),
            bg=theme.SURFACE,
            fg=theme.TEXT,
            font=(theme.FONT_UI, 13, "bold"),
            wraplength=600,
            justify="left",
            anchor="w",
        ).pack(fill="x", anchor="w", pady=(0, 12))

        correct_letter = (ex.get("correct") or "A").upper()
        chosen = tk.StringVar(value="")
        result_lbl = tk.Label(card, text="", bg=theme.SURFACE,
                              font=(theme.FONT_UI, 12, "bold"))

        choice_btns: list[tk.Label] = []

        for choice in ex.get("choices", []):
            letter = choice[:1].upper() if choice else "?"
            choice_lbl = tk.Label(
                card,
                text=choice,
                bg=theme.SURFACE,
                fg=theme.TEXT,
                font=(theme.FONT_UI, 12),
                cursor="hand2",
                wraplength=580,
                justify="left",
                anchor="w",
                padx=8,
                pady=4,
            )
            choice_lbl.pack(fill="x", anchor="w")
            choice_btns.append(choice_lbl)

            def _select(ltr=letter, lbl=choice_lbl):
                chosen.set(ltr)
                for b in choice_btns:
                    b.configure(bg=theme.SURFACE, fg=theme.TEXT)
                lbl.configure(bg=theme.ACCENT_SOFT, fg=theme.ACCENT)

            choice_lbl.bind("<Button-1>", lambda _e, fn=_select: fn())
            choice_lbl.bind("<Enter>", lambda _e, b=choice_lbl: b.configure(
                bg=theme.ACCENT_SOFT) if chosen.get() != letter else None)
            choice_lbl.bind("<Leave>", lambda _e, b=choice_lbl, ltr=letter: b.configure(
                bg=theme.ACCENT_SOFT if chosen.get() == ltr else theme.SURFACE))

        def _validate(
            btns=choice_btns,
            correct=correct_letter,
            explanation=ex.get("explanation", ""),
            var=chosen,
            lbl=result_lbl,
        ):
            answer = var.get()
            if not answer:
                return
            for b in btns:
                letter = (b.cget("text") or "")[:1].upper()
                if letter == correct:
                    b.configure(bg=theme.SUCCESS_SOFT, fg=theme.SUCCESS)
                elif letter == answer and answer != correct:
                    b.configure(bg=theme.DANGER_SOFT, fg=theme.DANGER)
            if answer == correct:
                lbl.configure(text=t("lang.session.correct"), fg=theme.SUCCESS)
            else:
                lbl.configure(text=t("lang.session.incorrect"), fg=theme.DANGER)
            lbl.pack(anchor="w", pady=(8, 0))
            if explanation:
                tk.Label(
                    card,
                    text=explanation,
                    bg=theme.SURFACE,
                    fg=theme.MUTED,
                    font=(theme.FONT_UI, 11, "italic"),
                    wraplength=600,
                    justify="left",
                    anchor="w",
                ).pack(fill="x", anchor="w", pady=(4, 0))
            validate_btn.configure(state="disabled")

        validate_btn = theme.make_button(
            card,
            text=t("lang.session.validate_btn"),
            command=_validate,
            kind="primary",
            font=(theme.FONT_UI, 11, "bold"),
            padx=18,
            pady=7,
        )
        validate_btn.pack(anchor="w", pady=(10, 0))

    def _stop_session(self) -> None:
        if self._tick_id:
            self.after_cancel(self._tick_id)
            self._tick_id = None
        if self._session:
            self._session.stop()
            self._session = None

    def _schedule_tick(self) -> None:
        self._tick_id = self.after(500, self._tick)

    def _tick(self) -> None:
        if self._session and self._session.is_running:
            self._session.tick()
            if self._timer_bar:
                self._timer_bar.update_state(
                    self._session.elapsed_total,
                    self._session.block_index,
                )
            self._tick_id = self.after(500, self._tick)
        else:
            self._tick_id = None

    def _on_block_change(self, name: str, index: int) -> None:
        phase = self._profile.get("phase", "passive")
        if name == "rappel" and phase == "active":
            self._show_translation_view()
            self._switch_tab("dialogue")
            return

        tab_map = {
            "rappel":     "dialogue",
            "ecoute":     "dialogue",
            "lecture":    "dialogue",
            "repetition": "dialogue",
            "notes":      "notes",
            "exercices":  "exercices",
        }
        target_tab = tab_map.get(name, "dialogue")
        self._switch_tab(target_tab)

    def _show_translation_view(self) -> None:
        dialogue_frame = self._content_frames.get("dialogue")
        if dialogue_frame is None:
            return
        if self._translation_view:
            self._translation_view.destroy()
        self._translation_view = TranslationExerciseView(
            dialogue_frame,
            profile=self._profile,
            lesson_data=self._lesson_data,
        )
        self._translation_view.place(relwidth=1, relheight=1)
        self._translation_view.lift()

    def _on_session_end(self, summary: dict) -> None:
        self.after(0, lambda: self._on_end(summary))

    # ── Navigation ────────────────────────────────────────────────────────────

    def _on_back_click(self) -> None:
        self._stop_session()
        self._on_back()

    # ── Tab system ────────────────────────────────────────────────────────────

    def _switch_tab(self, tab_id: str) -> None:
        self._active_tab = tab_id
        for tid, btn in self._tab_btns.items():
            if tid == tab_id:
                btn.configure(bg=theme.ACCENT, fg=theme.SURFACE)
            else:
                btn.configure(bg=theme.BG_ALT, fg=theme.MUTED)
        frame = self._content_frames.get(tab_id)
        if frame:
            frame.lift()

    # ── Content population ────────────────────────────────────────────────────

    def _populate_dialogue(self, dialogue: list[dict]) -> None:
        if self._dialog_view:
            self._dialog_view.load_dialogue(dialogue)

    def _populate_notes(self, notes: dict) -> None:
        if self._notes_panel is None:
            return
        for child in self._notes_panel.winfo_children():
            child.destroy()

        sections = [
            ("notes_grammar",       notes.get("grammar", "")),
            ("notes_pronunciation", notes.get("pronunciation", "")),
            ("notes_cultural",      notes.get("cultural", "")),
        ]

        canvas = tk.Canvas(self._notes_panel, bg=theme.SURFACE, highlightthickness=0)
        scrollbar = tk.Scrollbar(self._notes_panel, orient="vertical",
                                 command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=theme.SURFACE)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner(e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas(e):
            canvas.itemconfigure(inner_id, width=e.width)

        inner.bind("<Configure>", _on_inner)
        canvas.bind("<Configure>", _on_canvas)

        for key, content in sections:
            if not content:
                continue
            section = tk.Frame(inner, bg=theme.SURFACE, padx=28, pady=16)
            section.pack(fill="x")

            tk.Label(
                section,
                text=t(f"lang.session.{key}"),
                bg=theme.SURFACE,
                fg=theme.ACCENT,
                font=(theme.FONT_UI, 12, "bold"),
            ).pack(anchor="w")

            tk.Label(
                section,
                text=content,
                bg=theme.SURFACE,
                fg=theme.TEXT,
                font=(theme.FONT_UI, 12),
                wraplength=620,
                justify="left",
                anchor="w",
            ).pack(fill="x", anchor="w", pady=(4, 0))

            theme.divider(inner, pady=(0, 0))

    # ── i18n ──────────────────────────────────────────────────────────────────

    def refresh_lang(self) -> None:
        pass  # Labels rebuilt on next load() call
