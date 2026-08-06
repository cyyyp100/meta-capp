# ui/lang_entry_sas.py — Sas d'entrée pour le module langue
from __future__ import annotations

import tkinter as tk

import i18n as _i18n
from i18n import t
from llm.ollama_client import generate_lang_curiosity_async
from ui import theme
from ui.top_nav import Tooltip

BG = theme.BG
TEXT = theme.TEXT
MUTED = theme.MUTED
ACCENT = theme.ACCENT

_TIMER_SIZE = 118


class LangEntrySas(tk.Frame):
    def __init__(self, master, on_ready, on_back, **kwargs):
        super().__init__(master, bg=BG, **kwargs)
        self._on_ready = on_ready   # callable(profile, curriculum)
        self._on_back = on_back
        self._remaining = 30
        self._timer_id = None
        self._timer_canvas = None
        self._timer_arc = None
        self._count_lbl = None
        self._ready_btn = None
        self._hook_request_id = 0
        self._hook_lbl = None
        self._cultural_lbl = None
        self._lesson_lbl = None
        self._profile: dict = {}
        self._curriculum: list = []
        self._build()
        _i18n.on_lang_change(self._on_lang_change)

    def destroy(self) -> None:
        _i18n.remove_lang_change(self._on_lang_change)
        if self._timer_id:
            self.after_cancel(self._timer_id)
            self._timer_id = None
        super().destroy()

    def load(self, profile: dict, curriculum: list) -> None:
        self._profile = profile
        self._curriculum = curriculum

        lesson_n = profile.get("current_lesson", 1)
        lesson_row = next(
            (r for r in curriculum if r.get("lesson_n") == lesson_n),
            curriculum[0] if curriculum else {},
        )
        theme_text = lesson_row.get("theme", "")
        grammar_point = lesson_row.get("grammar_point", "")
        language = profile.get("language", "")

        if self._lesson_lbl is not None:
            self._lesson_lbl.configure(
                text=t("lang.sas.lesson", n=lesson_n, theme=theme_text)
            )

        self._remaining = 30
        if self._count_lbl is not None:
            self._count_lbl.configure(text="30")
        self._draw_timer()
        if self._ready_btn is not None:
            self._ready_btn.pack_forget()
        if self._timer_id:
            self.after_cancel(self._timer_id)
            self._timer_id = None

        self._load_curiosity_hook(language, lesson_n, theme_text, grammar_point)
        self._tick()

    def _build(self) -> None:
        # Top nav
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=56, pady=(34, 0))
        back_btn = theme.make_button(
            top,
            text=t("lang.sas.back"),
            command=self._on_back,
            kind="ghost",
            font=(theme.FONT_UI, 11, "bold"),
        )
        back_btn.pack(side="left")
        Tooltip(back_btn, t("lang.sas.back_tip"))

        tk.Frame(self, bg=BG).pack(fill="both", expand=True)

        center = theme.surface_frame(self, bg=theme.SURFACE)
        center.pack(anchor="center", padx=44, pady=0)
        center.configure(padx=44, pady=34)

        tk.Label(
            center,
            text=t("lang.sas.title"),
            bg=theme.SURFACE,
            fg=TEXT,
            font=(theme.FONT_TITLE, 28, "bold"),
        ).pack()

        self._lesson_lbl = tk.Label(
            center,
            text="",
            bg=theme.SURFACE,
            fg=MUTED,
            font=(theme.FONT_UI, 13, "bold"),
        )
        self._lesson_lbl.pack(pady=(6, 4))

        tk.Label(
            center,
            text=t("lang.sas.static"),
            bg=theme.SURFACE,
            fg=TEXT,
            font=(theme.FONT_UI, 13),
            wraplength=520,
            justify="center",
        ).pack(fill="x", pady=(6, 14))

        # Curiosity hook — blue box
        hook_frame = tk.Frame(
            center,
            bg=theme.ACCENT_SOFT,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            padx=16,
            pady=12,
        )
        hook_frame.pack(fill="x", pady=(0, 8))

        self._hook_lbl = tk.Label(
            hook_frame,
            text=t("lang.sas.hook_loading"),
            bg=theme.ACCENT_SOFT,
            fg=TEXT,
            font=(theme.FONT_UI, 13, "italic"),
            wraplength=520,
            justify="center",
        )
        self._hook_lbl.pack(fill="x")

        # Cultural note — yellow box
        cultural_frame = tk.Frame(
            center,
            bg=theme.WARNING_SOFT,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            padx=16,
            pady=12,
        )
        cultural_frame.pack(fill="x", pady=(0, 4))

        tk.Label(
            cultural_frame,
            text=t("lang.sas.cultural"),
            bg=theme.WARNING_SOFT,
            fg=theme.WARNING,
            font=(theme.FONT_UI, 10, "bold"),
        ).pack(anchor="w")

        self._cultural_lbl = tk.Label(
            cultural_frame,
            text="",
            bg=theme.WARNING_SOFT,
            fg=TEXT,
            font=(theme.FONT_UI, 12),
            wraplength=520,
            justify="left",
        )
        self._cultural_lbl.pack(fill="x")

        # Timer circle
        timer_wrap = tk.Frame(center, bg=theme.SURFACE, width=_TIMER_SIZE, height=_TIMER_SIZE)
        timer_wrap.pack(pady=(22, 16))
        timer_wrap.pack_propagate(False)

        self._timer_canvas = tk.Canvas(
            timer_wrap,
            width=_TIMER_SIZE,
            height=_TIMER_SIZE,
            bg=theme.SURFACE,
            highlightthickness=0,
        )
        self._timer_canvas.place(x=0, y=0)
        self._timer_canvas.create_oval(
            12, 12, _TIMER_SIZE - 12, _TIMER_SIZE - 12,
            outline=theme.BORDER,
            width=9,
        )
        self._timer_arc = self._timer_canvas.create_arc(
            12, 12, _TIMER_SIZE - 12, _TIMER_SIZE - 12,
            start=90,
            extent=-360,
            outline=ACCENT,
            width=9,
            style=tk.ARC,
        )

        self._count_lbl = tk.Label(
            timer_wrap,
            text="30",
            bg=theme.SURFACE,
            fg=ACCENT,
            font=(theme.FONT_TITLE, 33, "bold"),
        )
        self._count_lbl.place(x=_TIMER_SIZE // 2, y=_TIMER_SIZE // 2, anchor="center")

        self._ready_btn = theme.make_button(
            center,
            text=t("lang.sas.ready_btn"),
            command=self._ready,
            kind="primary",
            padx=28,
            pady=11,
            font=(theme.FONT_UI, 12, "bold"),
        )
        Tooltip(self._ready_btn, t("lang.sas.ready_tip"))

        tk.Frame(self, bg=BG).pack(fill="both", expand=True)

    def _tick(self) -> None:
        if self._count_lbl is not None:
            self._count_lbl.configure(text=str(self._remaining))
        self._draw_timer()
        if self._remaining == 15 and self._ready_btn is not None:
            self._ready_btn.pack()
        if self._remaining <= 0:
            return
        self._remaining -= 1
        self._timer_id = self.after(1000, self._tick)

    def _draw_timer(self) -> None:
        if self._timer_canvas is None or self._timer_arc is None:
            return
        ratio = max(0.0, min(1.0, self._remaining / 30.0))
        self._timer_canvas.itemconfigure(self._timer_arc, extent=-360 * ratio)

    def _ready(self) -> None:
        if self._timer_id:
            self.after_cancel(self._timer_id)
            self._timer_id = None
        self._on_ready(self._profile, self._curriculum)

    def _load_curiosity_hook(
        self, language: str, lesson_n: int, theme_text: str, grammar_point: str
    ) -> None:
        self._hook_request_id += 1
        request_id = self._hook_request_id

        if not language:
            self._show_hook_fallback_if_current(request_id)
            return

        self._show_hook_loading()

        def _success(result: dict) -> None:
            self.after(0, lambda r=result, rid=request_id: self._show_hook_if_current(rid, r))

        def _error(_message: str) -> None:
            self.after(0, lambda rid=request_id: self._show_hook_fallback_if_current(rid))

        try:
            generate_lang_curiosity_async(
                language, lesson_n, theme_text, grammar_point, _success, _error
            )
        except Exception:
            self._show_hook_fallback_if_current(request_id)

    def _show_hook_loading(self) -> None:
        if self._hook_lbl is not None:
            self._hook_lbl.configure(text=t("lang.sas.hook_loading"), fg=MUTED)
        if self._cultural_lbl is not None:
            self._cultural_lbl.configure(text="")

    def _show_hook_if_current(self, request_id: int, result: dict) -> None:
        if request_id != self._hook_request_id:
            return

        hook = (result.get("curiosity_hook") or "").strip()
        if not hook:
            self._show_hook_fallback_if_current(request_id)
            return

        if self._hook_lbl is not None:
            self._hook_lbl.configure(text=hook, fg=TEXT)

        cultural = (result.get("cultural_note") or "").strip()
        if self._cultural_lbl is not None:
            self._cultural_lbl.configure(text=cultural)

    def _show_hook_fallback_if_current(self, request_id: int) -> None:
        if request_id != self._hook_request_id:
            return

        if self._hook_lbl is not None:
            self._hook_lbl.configure(text=t("lang.sas.hook_fallback"), fg=TEXT)

    def _on_lang_change(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._timer_canvas = None
        self._timer_arc = None
        self._count_lbl = None
        self._ready_btn = None
        self._hook_lbl = None
        self._cultural_lbl = None
        self._lesson_lbl = None
        self._build()

    def refresh_lang(self) -> None:
        self._on_lang_change()
