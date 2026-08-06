# ui/session_entry_sas.py — Sas d'entrée de session
from __future__ import annotations

import tkinter as tk

from i18n import t
from llm.ollama_client import generate_curiosity_hook_async
from ui import theme
from ui.top_nav import Tooltip

BG = theme.BG
TEXT = theme.TEXT
MUTED = theme.MUTED
ACCENT = theme.ACCENT

_TIMER_SIZE = 118


class SessionEntrySas(tk.Frame):
    def __init__(self, master, on_ready, on_back, **kwargs):
        super().__init__(master, bg=BG, **kwargs)
        self._on_ready = on_ready
        self._on_back = on_back
        self._remaining = 30
        self._timer_id = None
        self._timer_canvas = None
        self._timer_arc = None
        self._hook_request_id = 0
        self._static_fallback_lbl = None
        self._hook_lbl = None
        self._build()

    def load(
        self,
        filename: str,
        doc_title: str = "",
        chapter_title: str = "",
        profile: dict | None = None,
        subchapter_title: str = "",
        chapter_excerpt: str = "",
    ) -> None:
        self._file_lbl.configure(text=filename)
        self._remaining = 30
        self._count_lbl.configure(text="30")
        self._draw_timer()
        self._ready_btn.pack_forget()
        if self._timer_id:
            self.after_cancel(self._timer_id)
            self._timer_id = None
        self._hook_params = {
            "doc_title": doc_title or filename,
            "chapter_title": chapter_title,
            "subchapter_title": subchapter_title,
            "profile": profile or {},
        }
        self._load_curiosity_hook(
            chapter_excerpt=chapter_excerpt,
            **self._hook_params,
        )
        self._tick()

    def update_chapter_excerpt(self, chapter_excerpt: str) -> None:
        """Appelé depuis app.py quand l'extrait du chapitre est disponible en différé."""
        params = getattr(self, "_hook_params", None)
        if not params or not chapter_excerpt.strip():
            return
        self._load_curiosity_hook(chapter_excerpt=chapter_excerpt, **params)

    def _build(self) -> None:
        # Barre du haut avec retour
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=56, pady=(34, 0))
        back_btn = theme.make_button(
            top,
            text=t("entry.back"),
            command=self._on_back,
            kind="ghost",
            font=(theme.FONT_UI, 11, "bold"),
        )
        back_btn.pack(side="left")
        Tooltip(back_btn, t("entry.back_tip"))

        # Spacer haut pour centrage vertical
        tk.Frame(self, bg=BG).pack(fill="both", expand=True)

        # Carte centrale
        center = theme.surface_frame(self, bg=theme.SURFACE)
        center.pack(anchor="center", padx=44, pady=0)
        center.configure(padx=44, pady=34)

        tk.Label(
            center,
            text=t("entry.title"),
            bg=theme.SURFACE,
            fg=TEXT,
            font=(theme.FONT_TITLE, 28, "bold"),
        ).pack()

        self._file_lbl = tk.Label(
            center,
            text="",
            bg=theme.SURFACE,
            fg=MUTED,
            font=(theme.FONT_UI, 11),
        )
        self._file_lbl.pack(pady=(8, 22))

        # Static fallback affiché en permanence au-dessus de la Curiosity
        self._static_fallback_lbl = tk.Label(
            center,
            text=t("entry.static"),
            bg=theme.SURFACE,
            fg=TEXT,
            font=(theme.FONT_UI, 13),
            wraplength=520,
            justify="center",
        )
        self._static_fallback_lbl.pack(fill="x", pady=(0, 14))

        # Curiosity générée dynamiquement
        self._hook_frame = tk.Frame(
            center,
            bg=theme.ACCENT_SOFT,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            padx=16,
            pady=12,
        )
        self._hook_frame.pack(fill="x", pady=(0, 4))

        self._hook_lbl = tk.Label(
            self._hook_frame,
            text=t("entry.hook_loading"),
            bg=theme.ACCENT_SOFT,
            fg=TEXT,
            font=(theme.FONT_UI, 13, "italic"),
            wraplength=520,
            justify="center",
        )
        self._hook_lbl.pack(fill="x")

        # Timer avec canvas + label superposé
        timer_wrap = tk.Frame(center, bg=theme.SURFACE, width=_TIMER_SIZE, height=_TIMER_SIZE)
        timer_wrap.pack(pady=(24, 18))
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
            12,
            12,
            _TIMER_SIZE - 12,
            _TIMER_SIZE - 12,
            outline=theme.BORDER,
            width=9,
        )
        self._timer_arc = self._timer_canvas.create_arc(
            12,
            12,
            _TIMER_SIZE - 12,
            _TIMER_SIZE - 12,
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
            text=t("entry.ready_btn"),
            command=self._ready,
            kind="primary",
            padx=28,
            pady=11,
            font=(theme.FONT_UI, 12, "bold"),
        )
        Tooltip(self._ready_btn, t("entry.ready_tip"))

        # Spacer bas pour centrage vertical
        tk.Frame(self, bg=BG).pack(fill="both", expand=True)

    def _tick(self) -> None:
        self._count_lbl.configure(text=str(self._remaining))
        self._draw_timer()
        if self._remaining == 15:
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
        self._on_ready()

    def _load_curiosity_hook(
        self,
        doc_title: str,
        chapter_title: str,
        subchapter_title: str,
        chapter_excerpt: str,
        profile: dict,
    ) -> None:
        self._hook_request_id += 1
        request_id = self._hook_request_id

        if not chapter_excerpt.strip():
            self._show_hook_fallback_if_current(request_id)
            return

        self._show_hook_loading()

        def _success(result: dict) -> None:
            self.after(0, lambda r=result, rid=request_id: self._show_hook_if_current(rid, r))

        def _error(_message: str) -> None:
            self.after(0, lambda rid=request_id: self._show_hook_fallback_if_current(rid))

        try:
            generate_curiosity_hook_async(
                doc_title,
                chapter_title,
                subchapter_title,
                chapter_excerpt,
                profile,
                _success,
                _error,
            )
        except Exception:
            self._show_hook_fallback_if_current(request_id)

    def _show_hook_loading(self) -> None:
        if self._hook_lbl is not None:
            self._hook_lbl.configure(
                text=t("entry.hook_loading"),
                fg=MUTED,
            )

    def _show_hook_if_current(self, request_id: int, result: dict) -> None:
        if request_id != self._hook_request_id:
            return

        hook = (result.get("curiosity_hook") or "").strip()
        if not hook:
            self._show_hook_fallback_if_current(request_id)
            return

        if self._hook_lbl is not None:
            self._hook_lbl.configure(text=hook, fg=TEXT)

    def _show_hook_fallback_if_current(self, request_id: int) -> None:
        if request_id != self._hook_request_id:
            return

        if self._hook_lbl is not None:
            self._hook_lbl.configure(
                text=t("entry.hook_fallback"),
                fg=TEXT,
            )

    def refresh_lang(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._timer_canvas = None
        self._timer_arc = None
        self._static_fallback_lbl = None
        self._hook_lbl = None
        self._build()