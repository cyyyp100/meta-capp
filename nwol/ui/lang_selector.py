# ui/lang_selector.py — Sélecteur de langue pour le module Assimil
from __future__ import annotations

import tkinter as tk

import i18n as _i18n
from i18n import t
from ui import theme
from ui.top_nav import Tooltip
from db.user import DEFAULT_USER_ID
from db.lang_db import get_or_create_lang_profile, get_curriculum, save_curriculum
from llm.ollama_client import generate_lang_curriculum_async

_LANGUAGES = [
    "Portugais",
    "Espagnol",
    "Anglais",
    "Italien",
    "Allemand",
    "Japonais",
    "Mandarin",
]


class LangSelectorPage(tk.Frame):
    def __init__(self, master, on_start, on_back, **kwargs):
        super().__init__(master, bg=theme.BG, **kwargs)
        self._on_start = on_start  # callable(profile: dict, curriculum: list[dict])
        self._on_back = on_back
        self._selected_lang = tk.StringVar(value=_LANGUAGES[0])
        self._status_var = tk.StringVar(value="")
        self._generating = False
        self._start_btn: tk.Widget | None = None
        self._status_lbl: tk.Label | None = None
        self._build()
        _i18n.on_lang_change(self._on_lang_change)

    def destroy(self) -> None:
        _i18n.remove_lang_change(self._on_lang_change)
        super().destroy()

    def _build(self) -> None:
        # Top nav
        top = tk.Frame(self, bg=theme.BG)
        top.pack(fill="x", padx=56, pady=(34, 0))
        back_btn = theme.make_button(
            top,
            text=t("lang.selector.back"),
            command=self._on_back,
            kind="ghost",
            font=(theme.FONT_UI, 11, "bold"),
        )
        back_btn.pack(side="left")
        Tooltip(back_btn, t("lang.selector.back_tip"))

        # Vertical centering spacers
        tk.Frame(self, bg=theme.BG).pack(fill="both", expand=True)

        # Central card
        card = tk.Frame(
            self,
            bg=theme.SURFACE,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
        )
        card.pack(anchor="center", padx=44)

        inner = tk.Frame(card, bg=theme.SURFACE)
        inner.pack(padx=54, pady=44)

        tk.Label(
            inner,
            text=t("lang.selector.title"),
            bg=theme.SURFACE,
            fg=theme.TEXT,
            font=(theme.FONT_TITLE, 28, "bold"),
        ).pack()

        tk.Label(
            inner,
            text=t("lang.selector.subtitle"),
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=(theme.FONT_UI, 12),
        ).pack(pady=(8, 20))

        # Language radio buttons in two columns
        radio_frame = tk.Frame(inner, bg=theme.SURFACE)
        radio_frame.pack()
        col_count = 2
        for i, lang in enumerate(_LANGUAGES):
            col = i % col_count
            row = i // col_count
            rb = tk.Radiobutton(
                radio_frame,
                text=lang,
                value=lang,
                variable=self._selected_lang,
                bg=theme.SURFACE,
                fg=theme.TEXT,
                selectcolor=theme.ACCENT_SOFT,
                activebackground=theme.SURFACE,
                font=(theme.FONT_UI, 13),
                cursor="hand2",
            )
            rb.grid(row=row, column=col, sticky="w", padx=(0, 28), pady=3)

        # Status label
        self._status_lbl = tk.Label(
            inner,
            textvariable=self._status_var,
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=(theme.FONT_UI, 11),
            wraplength=380,
        )
        self._status_lbl.pack(pady=(18, 0))

        # Start button
        self._start_btn = theme.make_button(
            inner,
            text=t("lang.selector.btn"),
            command=self._on_start_click,
            kind="primary",
            font=(theme.FONT_UI, 12, "bold"),
            padx=28,
            pady=11,
        )
        self._start_btn.pack(pady=(12, 0))
        Tooltip(self._start_btn, t("lang.selector.btn_tip"))

        tk.Frame(self, bg=theme.BG).pack(fill="both", expand=True)

    def _on_start_click(self) -> None:
        if self._generating:
            return
        language = self._selected_lang.get()
        profile = get_or_create_lang_profile(DEFAULT_USER_ID, language)
        curriculum = get_curriculum(language)
        if curriculum:
            self._status_var.set(t("lang.selector.ready", n=len(curriculum)))
            self._on_start(profile, curriculum)
            return

        self._generating = True
        if self._start_btn:
            self._start_btn.configure(state="disabled")
        if self._status_lbl:
            self._status_lbl.configure(fg=theme.MUTED)
        self._status_var.set(t("lang.selector.generating"))

        def _success(result: dict) -> None:
            lessons = result.get("lessons", [])
            save_curriculum(language, lessons)
            full = get_curriculum(language)
            self.after(0, lambda p=profile, c=full: self._on_generation_done(p, c))

        def _error(msg: str) -> None:
            self.after(0, self._on_generation_error)

        generate_lang_curriculum_async(language, _success, _error)

    def _on_generation_done(self, profile: dict, curriculum: list) -> None:
        self._generating = False
        if self._start_btn:
            self._start_btn.configure(state="normal")
        self._status_var.set(t("lang.selector.ready", n=len(curriculum)))
        self._on_start(profile, curriculum)

    def _on_generation_error(self) -> None:
        self._generating = False
        if self._start_btn:
            self._start_btn.configure(state="normal")
        if self._status_lbl:
            self._status_lbl.configure(fg=theme.DANGER if hasattr(theme, "DANGER") else "#B65A4A")
        self._status_var.set(t("lang.selector.error"))

    def _on_lang_change(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._start_btn = None
        self._status_lbl = None
        self._build()

    def refresh_lang(self) -> None:
        self._on_lang_change()
