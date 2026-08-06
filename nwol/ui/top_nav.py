# ui/top_nav.py — Barre de navigation supérieure de lecture
from __future__ import annotations

import tkinter as tk

from i18n import t
from ui import theme

BG = theme.SURFACE
TEXT = theme.TEXT
MUTED = theme.MUTED
ACCENT = theme.ACCENT
ALERT = theme.DANGER

_LLM_STYLES = {
    "available":   (theme.SUCCESS_SOFT, theme.SUCCESS),
    "unavailable": (theme.DANGER_SOFT,  ALERT),
    "generating":  (theme.ACCENT_SOFT,  ACCENT),
}
_LLM_LABEL_KEYS = {
    "available":   "nav.llm.available",
    "unavailable": "nav.llm.unavailable",
    "generating":  "nav.llm.generating",
}


class Tooltip:
    def __init__(self, widget, text: str, delay_ms: int = 1000):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _show(self):
        if self._tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self._tip,
            text=self.text,
            bg="#20303A",
            fg="#FFFFFF",
            font=(theme.FONT_UI, 10),
            padx=10,
            pady=6,
        ).pack()

    def _hide(self, _event=None):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tip:
            self._tip.destroy()
            self._tip = None

    def set_text(self, text: str) -> None:
        self.text = text
        if self._tip:
            self._hide()


class TopNav(tk.Frame):
    def __init__(
        self,
        master,
        on_back,
        on_play_pause,
        on_end_session,
        **kwargs,
    ):
        super().__init__(master, bg=BG, height=68, **kwargs)
        self._on_back = on_back
        self._on_play_pause = on_play_pause
        self._on_end_session = on_end_session
        self._is_playing = False
        self._ready = False
        self._last_engine: str = ""
        self._last_llm_status_key: str = ""
        self._chapter_title_full = ""
        self._build()
        self._ready = True

    def _build(self) -> None:
        self.pack_propagate(False)

        self.back_btn = _icon_button(self, "↩", self._on_back)
        self.back_btn.pack(side="left", padx=(16, 8), pady=12)
        self._back_tip = Tooltip(self.back_btn, t("nav.abandon_tip"))

        # Pack end_btn on the right BEFORE the expanding label so it reserves its space first
        self.end_btn = theme.make_button(
            self,
            text=t("nav.end_btn"),
            command=self._on_end_session,
            kind="danger",
        )
        self.end_btn.pack(side="right", padx=(8, 16), pady=12)
        self._end_tip = Tooltip(self.end_btn, t("nav.end_tip"))

        self.context_lbl = tk.Label(
            self,
            text="",
            bg=BG,
            fg=TEXT,
            font=(theme.FONT_UI, 12, "bold"),
            anchor="w",
        )
        self.context_lbl.pack(side="left", fill="x", expand=True, padx=8)
        self._context_tooltip = Tooltip(self.context_lbl, "")

        self.engine_lbl = tk.Label(
            self,
            text=t("nav.engine", engine=self._last_engine or "—"),
            bg=BG,
            fg=MUTED,
            font=(theme.FONT_UI, 10),
            width=16,
            anchor="w",
        )
        self.engine_lbl.pack(side="left", padx=(4, 8))

        self.play_btn = _icon_button(self, "▶", self._toggle_play)
        self.play_btn.pack(side="left", padx=4, pady=12)
        self.play_tip = Tooltip(self.play_btn, t("nav.play_tip"))

        self.llm_lbl = tk.Label(
            self,
            text="LLM : —",
            bg=BG,
            fg=MUTED,
            font=(theme.FONT_UI, 10),
            width=16,
            anchor="w",
            padx=8,
            pady=4,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
        )
        self.llm_lbl.pack(side="left", padx=(8, 2))

        self.timer_lbl = tk.Label(
            self,
            text="⏱ 00:00",
            bg=theme.SURFACE_SOFT,
            fg=theme.TEXT_SOFT,
            font=(theme.FONT_UI, 11, "bold"),
            width=9,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
        )
        self.timer_lbl.pack(side="left", padx=8)

    def bind_keyboard(self, root) -> None:
        root.bind("<space>", lambda _event: self._toggle_play(), add="+")

    _TITLE_MAX = 55

    def set_context(self, chapter_title: str, page: int, total_pages: int) -> None:
        title = chapter_title or "—"
        self._chapter_title_full = title
        if len(title) > self._TITLE_MAX:
            display = title[: self._TITLE_MAX].rstrip() + "…"
            self._context_tooltip.set_text(title)
        else:
            display = title
            self._context_tooltip.set_text("")
        self.context_lbl.configure(
            text=t("nav.chapter_ctx", title=display, page=page, total=total_pages)
        )

    def set_play_state(self, is_playing: bool) -> None:
        self._is_playing = is_playing
        self.play_btn.configure(text="⏸" if is_playing else "▶")
        self.play_tip.set_text(t("nav.pause_tip") if is_playing else t("nav.play_tip"))

    def set_engine(self, engine: str) -> None:
        self._last_engine = engine or ""
        self.engine_lbl.configure(text=t("nav.engine", engine=engine or "—"))

    def set_llm_status(self, status_key: str) -> None:
        self._last_llm_status_key = status_key
        bg, fg = _LLM_STYLES.get(status_key, (BG, MUTED))
        label = t(_LLM_LABEL_KEYS[status_key]) if status_key in _LLM_LABEL_KEYS else status_key
        self.llm_lbl.configure(text=f"LLM : {label}", bg=bg, fg=fg)

    def set_elapsed(self, seconds: int) -> None:
        minutes, secs = divmod(max(0, int(seconds)), 60)
        self.timer_lbl.configure(text=f"⏱ {minutes:02d}:{secs:02d}")

    def refresh_lang(self) -> None:
        self.end_btn.configure(text=t("nav.end_btn"))
        self._back_tip.set_text(t("nav.abandon_tip"))
        self._end_tip.set_text(t("nav.end_tip"))
        self.engine_lbl.configure(text=t("nav.engine", engine=self._last_engine or "—"))
        self.set_play_state(self._is_playing)
        if self._last_llm_status_key:
            self.set_llm_status(self._last_llm_status_key)

    def _toggle_play(self) -> None:
        self._on_play_pause()


def _icon_button(master, text: str, command) -> tk.Button:
    return theme.make_button(
        master,
        text=text,
        command=command,
        kind="secondary",
        width=3,
        font=(theme.FONT_UI, 14, "bold"),
    )
