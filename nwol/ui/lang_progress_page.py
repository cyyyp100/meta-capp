# ui/lang_progress_page.py — Vue progression du module langue
from __future__ import annotations

import tkinter as tk

import i18n as _i18n
from i18n import t
from ui import theme

_SPARK_W = 420
_SPARK_H = 90
_SPARK_PAD_X = 12
_SPARK_PAD_Y = 10


class LangProgressPage(tk.Frame):
    def __init__(self, master, on_back, on_start_session, **kwargs):
        super().__init__(master, bg=theme.BG, **kwargs)
        self._on_back = on_back
        self._on_start_session = on_start_session  # callable(profile, curriculum)
        self._profile: dict = {}
        self._curriculum: list = []
        self._progress: dict = {}
        self._build()
        _i18n.on_lang_change(self._on_lang_change)

    def destroy(self) -> None:
        _i18n.remove_lang_change(self._on_lang_change)
        super().destroy()

    # ── Public entry point ────────────────────────────────────────────────────

    def load(self, profile: dict, curriculum: list, progress: dict) -> None:
        self._profile = profile
        self._curriculum = curriculum
        self._progress = progress
        self._refresh()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # Top nav
        top = tk.Frame(self, bg=theme.BG)
        top.pack(fill="x", padx=56, pady=(34, 0))
        back_btn = theme.make_button(
            top,
            text=t("lang.progress.back"),
            command=self._on_back,
            kind="ghost",
            font=(theme.FONT_UI, 11, "bold"),
        )
        back_btn.pack(side="left")

        tk.Frame(self, bg=theme.BG).pack(fill="both", expand=True)

        card = tk.Frame(
            self,
            bg=theme.SURFACE,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
        )
        card.pack(anchor="center", padx=44)

        self._inner = tk.Frame(card, bg=theme.SURFACE)
        self._inner.pack(padx=54, pady=44)

        self._title_lbl = tk.Label(
            self._inner,
            text=t("lang.progress.title"),
            bg=theme.SURFACE,
            fg=theme.TEXT,
            font=(theme.FONT_TITLE, 28, "bold"),
        )
        self._title_lbl.pack()

        self._language_lbl = tk.Label(
            self._inner,
            text="",
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=(theme.FONT_UI, 13),
        )
        self._language_lbl.pack(pady=(4, 20))

        # Sparkline canvas
        self._spark_canvas = tk.Canvas(
            self._inner,
            width=_SPARK_W,
            height=_SPARK_H,
            bg=theme.SURFACE_SOFT,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
        )
        self._spark_canvas.pack(pady=(0, 20))

        # Stats row
        stats = tk.Frame(self._inner, bg=theme.SURFACE)
        stats.pack(fill="x", pady=(0, 16))

        self._lessons_lbl = tk.Label(
            stats,
            text="",
            bg=theme.SURFACE,
            fg=theme.TEXT,
            font=(theme.FONT_UI, 12),
        )
        self._lessons_lbl.pack(side="left", padx=(0, 28))

        self._score_lbl = tk.Label(
            stats,
            text="",
            bg=theme.SURFACE,
            fg=theme.TEXT,
            font=(theme.FONT_UI, 12),
        )
        self._score_lbl.pack(side="left", padx=(0, 28))

        self._phase_lbl = tk.Label(
            stats,
            text="",
            bg=theme.SURFACE,
            fg=theme.ACCENT,
            font=(theme.FONT_UI, 12, "bold"),
        )
        self._phase_lbl.pack(side="left")

        theme.divider(self._inner, pady=(0, 16))

        self._next_lbl = tk.Label(
            self._inner,
            text="",
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=(theme.FONT_UI, 12),
        )
        self._next_lbl.pack(anchor="w", pady=(0, 14))

        self._start_btn = theme.make_button(
            self._inner,
            text=t("lang.progress.start_next"),
            command=self._start_next,
            kind="primary",
            font=(theme.FONT_UI, 12, "bold"),
            padx=28,
            pady=11,
        )
        self._start_btn.pack(anchor="w")

        tk.Frame(self, bg=theme.BG).pack(fill="both", expand=True)

    def _refresh(self) -> None:
        language = self._profile.get("language", "")
        self._language_lbl.configure(text=language)

        total = self._progress.get("total_sessions", 0)
        avg = self._progress.get("avg_score", 0.0)
        phase = self._profile.get("phase", "passive")
        lesson_n = self._profile.get("current_lesson", 1)

        self._lessons_lbl.configure(
            text=t("lang.progress.lessons_done", n=total))
        self._score_lbl.configure(
            text=t("lang.progress.avg_score", pct=round(avg * 100)))
        phase_key = "lang.progress.phase_active" if phase == "active" else "lang.progress.phase_passive"
        self._phase_lbl.configure(text=t(phase_key))

        next_row = next(
            (r for r in self._curriculum if r.get("lesson_n") == lesson_n),
            self._curriculum[0] if self._curriculum else {},
        )
        next_theme = next_row.get("theme", "")
        self._next_lbl.configure(
            text=t("lang.progress.next_lesson", n=lesson_n, theme=next_theme))

        self._draw_sparkline(self._progress.get("sessions", []))

    def _draw_sparkline(self, sessions: list[dict]) -> None:
        c = self._spark_canvas
        c.delete("all")
        W, H = _SPARK_W, _SPARK_H
        px, py = _SPARK_PAD_X, _SPARK_PAD_Y

        if not sessions:
            c.create_text(W // 2, H // 2, text="—",
                          fill=theme.MUTED_LIGHT,
                          font=(theme.FONT_UI, 14))
            return

        scores = [float(s.get("score") or 0.0) for s in sessions]
        n = len(scores)

        x_step = (W - 2 * px) / max(n - 1, 1)
        y_range = H - 2 * py

        def _xy(i, score):
            x = px + i * x_step
            y = H - py - score * y_range
            return x, y

        # Baseline
        c.create_line(px, H - py, W - px, H - py,
                      fill=theme.BORDER, width=1)

        # Line segments
        for i in range(n - 1):
            x1, y1 = _xy(i, scores[i])
            x2, y2 = _xy(i + 1, scores[i + 1])
            c.create_line(x1, y1, x2, y2, fill=theme.ACCENT, width=2)

        # Points
        r = 4
        for i, score in enumerate(scores):
            x, y = _xy(i, score)
            c.create_oval(x - r, y - r, x + r, y + r,
                          fill=theme.ACCENT, outline=theme.SURFACE, width=2)

    def _start_next(self) -> None:
        self._on_start_session(self._profile, self._curriculum)

    def _on_lang_change(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._inner = None  # type: ignore[assignment]
        self._build()
        if self._profile:
            self._refresh()

    def refresh_lang(self) -> None:
        self._on_lang_change()
