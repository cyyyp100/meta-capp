# ui/assistant_bubble.py — Bulle assistante flottante (Gemma) + panneau de dialogue
#
# La bulle incarne visuellement le LLM : un petit personnage Canvas pseudo-3D
# avec des yeux, déplaçable, toujours au-dessus du PDF sans gêner le texte.
# États : idle, reading, thinking, answering, intervention, unavailable.
# Un clic ouvre un panneau compact (question libre → réponse contextualisée).
from __future__ import annotations

import logging
import math
import tkinter as tk
from typing import Callable

from i18n import t
from ui import theme
from ui.rich_text import rich_text_widget as _rich_text_widget

logger = logging.getLogger("UI.assistant_bubble")

BUBBLE_SIZE = 68
_FRAME_MS = 140
_CLICK_SLOP_PX = 5

_BODY = "#2F7D8C"
_BODY_DARK = "#266979"
_BODY_LIGHT = "#5BA3B0"
_BODY_OFF = "#9FB3BA"
_EYE_WHITE = "#F4FBFC"
_PUPIL = "#13343C"
_BADGE = "#E5A33D"
_GLOW = "#E5C04B"  # lueur de progrès (jauge en forte hausse)

STATES = ("idle", "reading", "thinking", "answering", "intervention", "unavailable", "glow")


class AssistantBubble(tk.Canvas):
    """Bulle Canvas animée. Le parent la positionne avec ``place``."""

    def __init__(
        self,
        parent,
        on_click: Callable[[], None],
        on_moved: Callable[[int, int], None] | None = None,
        **kwargs,
    ):
        super().__init__(
            parent,
            width=BUBBLE_SIZE,
            height=BUBBLE_SIZE,
            highlightthickness=0,
            bg=kwargs.pop("bg", theme.SURFACE_SOFT),
            cursor="hand2",
            **kwargs,
        )
        self._on_click = on_click
        self._on_moved = on_moved
        self._state = "idle"
        self._frame = 0
        self._anim_id: str | None = None

        self._drag_start: tuple[int, int] | None = None
        self._drag_origin: tuple[int, int] | None = None
        self._dragging = False

        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)

        self._draw()
        self._tick()

    # ------------------------------------------------------------------
    # État
    # ------------------------------------------------------------------
    def set_state(self, state: str) -> None:
        if state not in STATES or state == self._state:
            return
        self._state = state
        self._frame = 0
        self._draw()

    @property
    def state(self) -> str:
        return self._state

    def set_canvas_bg(self, color: str) -> None:
        self.configure(bg=color)

    def raise_widget(self) -> None:
        """Remonte la bulle au-dessus des autres widgets.

        ``lift``/``tkraise`` sont shadowés sur Canvas par ``tag_raise``
        (items du canvas) : il faut passer par ``tk.Misc`` explicitement.
        """
        tk.Misc.tkraise(self)

    def destroy(self) -> None:  # noqa: D102 — arrêt propre de l'animation
        if self._anim_id is not None:
            try:
                self.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None
        super().destroy()

    # ------------------------------------------------------------------
    # Animation
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        self._frame += 1
        try:
            self._draw()
        except tk.TclError:
            return
        self._anim_id = self.after(_FRAME_MS, self._tick)

    def _draw(self) -> None:
        self.delete("all")
        c = BUBBLE_SIZE / 2
        breath = math.sin(self._frame * 0.35)
        bob = breath * 1.6 if self._state in {"idle", "reading"} else 0.0
        r = 24 + (0.8 if self._state == "thinking" else 0.0)

        if self._state in {"intervention", "glow"}:
            # Anneau pulsant : ambre = intervention, doré = lueur de progrès.
            pulse = 3.0 + 2.4 * (1 + math.sin(self._frame * 0.55)) / 2
            self.create_oval(
                c - r - pulse, c - r - pulse + bob, c + r + pulse, c + r + pulse + bob,
                outline=_BADGE if self._state == "intervention" else _GLOW, width=2,
            )

        body = _BODY_OFF if self._state == "unavailable" else _BODY
        # Ombre portée + corps + reflet : pseudo-3D sans dépendance.
        self.create_oval(c - r + 2, c - r + 5 + bob, c + r + 2, c + r + 5 + bob,
                         fill=_BODY_DARK if self._state != "unavailable" else "#8C9EA5", outline="")
        self.create_oval(c - r, c - r + bob, c + r, c + r + bob, fill=body, outline="")
        self.create_oval(c - r + 6, c - r + 4 + bob, c + 2, c - 2 + bob,
                         fill=_BODY_LIGHT if self._state != "unavailable" else "#B7C6CC", outline="")

        self._draw_eyes(c, bob)
        self._draw_accessories(c, r, bob)

    def _draw_eyes(self, c: float, bob: float) -> None:
        eye_y = c - 4 + bob
        eye_dx = 9
        ew, eh = 6.5, 8.5

        if self._state == "unavailable":
            for sign in (-1, 1):
                x = c + sign * eye_dx
                self.create_line(x - 5, eye_y, x + 5, eye_y, fill=_PUPIL, width=2, capstyle=tk.ROUND)
            return

        if self._state in {"answering", "glow"}:
            # Yeux heureux : arcs vers le bas.
            for sign in (-1, 1):
                x = c + sign * eye_dx
                self.create_arc(x - 6, eye_y - 5, x + 6, eye_y + 7,
                                start=30, extent=120, style=tk.ARC, outline=_PUPIL, width=2.5)
            return

        blink = self._state == "idle" and (self._frame % 34) in (0, 1)
        if blink:
            for sign in (-1, 1):
                x = c + sign * eye_dx
                self.create_line(x - 5, eye_y + 1, x + 5, eye_y + 1, fill=_PUPIL, width=2, capstyle=tk.ROUND)
            return

        if self._state == "reading":
            look_x = math.sin(self._frame * 0.5) * 2.6
            look_y = 1.0
        elif self._state == "thinking":
            look_x = 2.0
            look_y = -2.6
        elif self._state == "intervention":
            look_x, look_y = 0.0, 0.0
        else:
            look_x = math.sin(self._frame * 0.12) * 1.2
            look_y = 0.4

        for sign in (-1, 1):
            x = c + sign * eye_dx
            self.create_oval(x - ew, eye_y - eh, x + ew, eye_y + eh, fill=_EYE_WHITE, outline="")
            px, py = x + look_x, eye_y + look_y
            self.create_oval(px - 2.8, py - 2.8, px + 2.8, py + 2.8, fill=_PUPIL, outline="")
            self.create_oval(px - 0.8, py - 1.8, px + 0.8, py - 0.4, fill=_EYE_WHITE, outline="")

    def _draw_accessories(self, c: float, r: float, bob: float) -> None:
        if self._state == "thinking":
            # Points de réflexion qui défilent au-dessus de la tête.
            phase = self._frame % 3
            for i in range(3):
                size = 2.6 if i == phase else 1.6
                x = c - 8 + i * 8
                y = c - r - 6 + bob
                self.create_oval(x - size, y - size, x + size, y + size,
                                 fill=_BODY_LIGHT, outline="")
        elif self._state == "intervention":
            self.create_oval(c + r - 12, c - r + bob - 2, c + r + 4, c - r + bob + 14,
                             fill=_BADGE, outline="")
            self.create_text(c + r - 4, c - r + bob + 6, text="!",
                             font=(theme.FONT_UI, 10, "bold"), fill="#FFFFFF")
        elif self._state == "unavailable":
            self.create_text(c + r - 6, c - r + bob + 6, text="z",
                             font=(theme.FONT_UI, 10, "bold"), fill=theme.MUTED)
        elif self._state in {"answering", "glow"}:
            # Petite bouche souriante.
            self.create_arc(c - 7, c + 4 + bob, c + 7, c + 13 + bob,
                            start=200, extent=140, style=tk.ARC, outline=_EYE_WHITE, width=2)

    # ------------------------------------------------------------------
    # Drag & clic
    # ------------------------------------------------------------------
    def _on_press(self, event) -> None:
        self._drag_start = (event.x_root, event.y_root)
        info = self.place_info()
        try:
            self._drag_origin = (int(float(info.get("x", 0))), int(float(info.get("y", 0))))
        except (TypeError, ValueError):
            self._drag_origin = (0, 0)
        self._dragging = False

    def _on_motion(self, event) -> None:
        if self._drag_start is None or self._drag_origin is None:
            return
        dx = event.x_root - self._drag_start[0]
        dy = event.y_root - self._drag_start[1]
        if abs(dx) > _CLICK_SLOP_PX or abs(dy) > _CLICK_SLOP_PX:
            self._dragging = True
        if not self._dragging:
            return
        new_x = self._drag_origin[0] + dx
        new_y = self._drag_origin[1] + dy
        parent = self.master
        max_x = max(0, parent.winfo_width() - BUBBLE_SIZE)
        max_y = max(0, parent.winfo_height() - BUBBLE_SIZE)
        new_x = max(0, min(max_x, new_x))
        new_y = max(0, min(max_y, new_y))
        self.place_configure(x=new_x, y=new_y)

    def _on_release(self, event) -> None:
        was_dragging = self._dragging
        self._drag_start = None
        self._drag_origin = None
        self._dragging = False
        if was_dragging:
            if self._on_moved is not None:
                info = self.place_info()
                try:
                    self._on_moved(int(float(info.get("x", 0))), int(float(info.get("y", 0))))
                except (TypeError, ValueError):
                    pass
            return
        self._on_click()


class AssistantPanel(tk.Frame):
    """Panneau compact ouvert par la bulle : question libre, réponses, modes."""

    def __init__(
        self,
        parent,
        on_submit: Callable[[str], None],
        on_close: Callable[[], None],
        on_mode_change: Callable[[str], None],
        on_create_flashcard: Callable[[], None],
        on_focus_mode: Callable[[], None] | None = None,
        **kwargs,
    ):
        super().__init__(
            parent,
            bg=theme.SURFACE,
            highlightthickness=1,
            highlightbackground=theme.BORDER_STRONG,
            **kwargs,
        )
        self._on_submit = on_submit
        self._on_close = on_close
        self._on_mode_change = on_mode_change
        self._on_create_flashcard = on_create_flashcard
        self._on_focus_mode = on_focus_mode
        self._busy = False
        self._unavailable = False
        self._has_answer = False
        self._focus_active = False
        self._mode_var = tk.StringVar(value="normal")
        self._build()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build(self) -> None:
        header = tk.Frame(self, bg=theme.ACCENT_SOFT)
        header.pack(fill="x")
        tk.Label(
            header,
            text=t("assistant.title"),
            bg=theme.ACCENT_SOFT,
            fg=theme.ACCENT,
            font=(theme.FONT_UI, 11, "bold"),
        ).pack(side="left", padx=(12, 4), pady=7)

        close_btn = tk.Label(
            header, text="✕", bg=theme.ACCENT_SOFT, fg=theme.MUTED,
            font=(theme.FONT_UI, 11, "bold"), cursor="hand2", padx=8,
        )
        close_btn.pack(side="right", pady=4)
        close_btn.bind("<Button-1>", lambda _e: self._on_close())

        self._mode_menu = tk.OptionMenu(header, self._mode_var, *("discret", "normal", "coach"),
                                        command=lambda value: self._on_mode_change(value))
        self._mode_menu.configure(
            bg=theme.ACCENT_SOFT, fg=theme.TEXT_SOFT, activebackground=theme.ACCENT_SOFT_HOVER,
            relief=tk.FLAT, highlightthickness=0, font=(theme.FONT_UI, 9), bd=0,
        )
        self._mode_menu["menu"].configure(font=(theme.FONT_UI, 10))
        self._mode_menu.pack(side="right", pady=4)
        tk.Label(
            header, text=t("assistant.mode_label"), bg=theme.ACCENT_SOFT,
            fg=theme.MUTED, font=(theme.FONT_UI, 9),
        ).pack(side="right")

        # Fil de conversation
        convo_wrap = tk.Frame(self, bg=theme.SURFACE)
        convo_wrap.pack(fill="both", expand=True, padx=2, pady=(2, 0))
        self._convo_canvas = tk.Canvas(convo_wrap, bg=theme.SURFACE, highlightthickness=0, height=230)
        scroll = tk.Scrollbar(convo_wrap, orient="vertical", command=self._convo_canvas.yview)
        self._convo_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self._convo_canvas.pack(side="left", fill="both", expand=True)
        self._convo = tk.Frame(self._convo_canvas, bg=theme.SURFACE)
        self._convo_window = self._convo_canvas.create_window(0, 0, anchor="nw", window=self._convo)
        self._convo.bind(
            "<Configure>",
            lambda _e: self._convo_canvas.configure(scrollregion=self._convo_canvas.bbox("all")),
        )
        self._convo_canvas.bind(
            "<Configure>",
            lambda e: self._convo_canvas.itemconfigure(self._convo_window, width=e.width),
        )
        for widget in (self._convo_canvas, self._convo):
            widget.bind("<MouseWheel>", self._on_wheel)
            widget.bind("<Button-4>", lambda _e: self._convo_canvas.yview_scroll(-2, "units"))
            widget.bind("<Button-5>", lambda _e: self._convo_canvas.yview_scroll(2, "units"))

        self._hint_lbl = tk.Label(
            self._convo,
            text=t("assistant.hint"),
            bg=theme.SURFACE,
            fg=theme.MUTED_LIGHT,
            font=(theme.FONT_UI, 10, "italic"),
            wraplength=300,
            justify="left",
        )
        self._hint_lbl.pack(fill="x", padx=10, pady=10)

        # Statut + flashcard
        footer = tk.Frame(self, bg=theme.SURFACE)
        footer.pack(fill="x", padx=10)
        self._status_lbl = tk.Label(
            footer, text="", bg=theme.SURFACE, fg=theme.MUTED,
            font=(theme.FONT_UI, 9, "italic"), anchor="w",
        )
        self._status_lbl.pack(side="left", fill="x", expand=True)
        self._flashcard_btn = theme.make_button(
            footer, text=t("assistant.create_flashcard"),
            command=self._on_create_flashcard, kind="soft",
            padx=8, pady=3, font=(theme.FONT_UI, 9),
        )
        self._focus_btn = None
        if self._on_focus_mode is not None:
            self._focus_btn = theme.make_button(
                footer, text=t("assistant.focus_btn"),
                command=self._on_focus_mode, kind="soft",
                padx=8, pady=3, font=(theme.FONT_UI, 9),
            )
            self._focus_btn.pack(side="right", padx=(0, 6), pady=(0, 2))
            self._apply_focus_label()

        # Saisie
        input_row = tk.Frame(self, bg=theme.SURFACE)
        input_row.pack(fill="x", padx=10, pady=(4, 10))
        self._entry = theme.style_entry(tk.Text(
            input_row, height=2, wrap=tk.WORD, padx=8, pady=6, font=(theme.FONT_UI, 10),
        ))
        self._entry.pack(side="left", fill="both", expand=True)
        self._entry.bind("<Return>", self._on_return)
        self._entry.bind("<Shift-Return>", lambda _e: None)
        self._send_btn = theme.make_button(
            input_row, text=t("assistant.send"), command=self._submit,
            kind="primary", padx=10, pady=6, font=(theme.FONT_UI, 10, "bold"),
        )
        self._send_btn.pack(side="right", padx=(8, 0))

    def _on_wheel(self, event) -> None:
        if event.delta:
            self._convo_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    def focus_input(self) -> None:
        try:
            self._entry.focus_set()
        except tk.TclError:
            pass

    def set_mode(self, mode: str) -> None:
        self._mode_var.set(mode)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = tk.DISABLED if busy or self._unavailable else tk.NORMAL
        try:
            self._send_btn.configure(state=state)
            self._entry.configure(state=state)
        except tk.TclError:
            return
        self._status_lbl.configure(text=t("assistant.thinking") if busy else "")

    def set_unavailable(self, unavailable: bool) -> None:
        self._unavailable = unavailable
        if unavailable:
            self._status_lbl.configure(text=t("assistant.unavailable"))
            self._send_btn.configure(state=tk.DISABLED)
            self._entry.configure(state=tk.DISABLED)
        else:
            self._status_lbl.configure(text="")
            if not self._busy:
                self._send_btn.configure(state=tk.NORMAL)
                self._entry.configure(state=tk.NORMAL)

    def set_status(self, text: str) -> None:
        self._status_lbl.configure(text=text)

    def set_focus_active(self, active: bool) -> None:
        self._focus_active = bool(active)
        self._apply_focus_label()

    def _apply_focus_label(self) -> None:
        if self._focus_btn is None:
            return
        key = "assistant.focus_stop" if self._focus_active else "assistant.focus_btn"
        try:
            self._focus_btn.configure(text=t(key))
        except tk.TclError:
            pass

    def add_user_message(self, text: str) -> None:
        self._hide_hint()
        bubble = tk.Frame(self._convo, bg=theme.ACCENT_SOFT,
                          highlightthickness=1, highlightbackground=theme.BORDER)
        bubble.pack(fill="x", padx=(46, 10), pady=(6, 0), anchor="e")
        _rich_text_widget(
            bubble, text, bg=theme.ACCENT_SOFT, fg=theme.TEXT, font=(theme.FONT_UI, 10),
        ).pack(fill="x", padx=10, pady=8)
        self._scroll_to_end()

    def add_assistant_message(self, text: str, page_note: str = "") -> None:
        self._hide_hint()
        bubble = tk.Frame(self._convo, bg=theme.SURFACE_SOFT,
                          highlightthickness=1, highlightbackground=theme.BORDER)
        bubble.pack(fill="x", padx=(10, 46), pady=(6, 0), anchor="w")
        if page_note:
            tk.Label(
                bubble, text=page_note, bg=theme.SURFACE_SOFT, fg=theme.MUTED,
                font=(theme.FONT_UI, 8, "italic"), anchor="w",
            ).pack(fill="x", padx=10, pady=(6, 0))
        _rich_text_widget(
            bubble, text, bg=theme.SURFACE_SOFT, fg=theme.TEXT, font=(theme.FONT_UI, 10),
        ).pack(fill="x", padx=10, pady=8)
        self._has_answer = True
        if not self._flashcard_btn.winfo_ismapped():
            self._flashcard_btn.pack(side="right", pady=(0, 2))
        self._scroll_to_end()

    def add_meta_message(self, text: str) -> None:
        self._hide_hint()
        tk.Label(
            self._convo, text=text, bg=theme.SURFACE, fg=theme.MUTED,
            font=(theme.FONT_UI, 9, "italic"), wraplength=300, justify="left",
        ).pack(fill="x", padx=10, pady=(6, 0))
        self._scroll_to_end()

    def show_flashcard_review(self, front: str, back: str, on_verdict: Callable[[str], None]) -> None:
        """Mini-révision dans le fil : recto → révéler → verso → auto-évaluation."""
        self._hide_hint()
        bubble = tk.Frame(self._convo, bg=theme.SURFACE_SOFT,
                          highlightthickness=1, highlightbackground=theme.BORDER)
        bubble.pack(fill="x", padx=(10, 46), pady=(6, 0), anchor="w")
        tk.Label(
            bubble, text=t("assistant.flashcard_review_title"), bg=theme.SURFACE_SOFT,
            fg=theme.MUTED, font=(theme.FONT_UI, 8, "italic"), anchor="w",
        ).pack(fill="x", padx=10, pady=(6, 0))
        _rich_text_widget(
            bubble, front, bg=theme.SURFACE_SOFT, fg=theme.TEXT, font=(theme.FONT_UI, 10),
        ).pack(fill="x", padx=10, pady=(4, 0))

        def _on_done(verdict: str, row: tk.Frame) -> None:
            try:
                row.destroy()
            except tk.TclError:
                pass
            tk.Label(
                bubble, text=t("assistant.review_done"), bg=theme.SURFACE_SOFT,
                fg=theme.MUTED, font=(theme.FONT_UI, 9, "italic"), anchor="w",
            ).pack(fill="x", padx=10, pady=(0, 8))
            self._scroll_to_end()
            on_verdict(verdict)

        def _reveal() -> None:
            try:
                reveal_btn.destroy()
            except tk.TclError:
                pass
            _rich_text_widget(
                bubble, back, bg=theme.SURFACE_SOFT, fg=theme.TEXT, font=(theme.FONT_UI, 10),
            ).pack(fill="x", padx=10, pady=(4, 0))
            verdict_row = tk.Frame(bubble, bg=theme.SURFACE_SOFT)
            verdict_row.pack(fill="x", padx=10, pady=(6, 8))
            for verdict, key in (
                ("correct", "assistant.review_correct"),
                ("partial", "assistant.review_partial"),
                ("incorrect", "assistant.review_incorrect"),
            ):
                theme.make_button(
                    verdict_row, text=t(key),
                    command=lambda v=verdict, r=verdict_row: _on_done(v, r),
                    kind="soft", padx=8, pady=3, font=(theme.FONT_UI, 9),
                ).pack(side="left", padx=(0, 6))
            self._scroll_to_end()

        reveal_btn = theme.make_button(
            bubble, text=t("assistant.review_reveal"), command=_reveal,
            kind="soft", padx=10, pady=4, font=(theme.FONT_UI, 9, "bold"),
        )
        reveal_btn.pack(anchor="w", padx=10, pady=(6, 8))
        self._scroll_to_end()

    def read_input(self) -> str:
        try:
            return self._entry.get("1.0", "end").strip()
        except tk.TclError:
            return ""

    def clear_input(self) -> None:
        try:
            self._entry.delete("1.0", "end")
        except tk.TclError:
            pass

    def refresh_lang(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._has_answer = False
        self._build()

    # ------------------------------------------------------------------
    # Interne
    # ------------------------------------------------------------------
    def _on_return(self, _event):
        self._submit()
        return "break"

    def _submit(self) -> None:
        if self._busy or self._unavailable:
            return
        text = self.read_input()
        if not text:
            return
        self.clear_input()
        self._on_submit(text)

    def _hide_hint(self) -> None:
        if self._hint_lbl is not None and self._hint_lbl.winfo_ismapped():
            self._hint_lbl.pack_forget()

    def _scroll_to_end(self) -> None:
        self._convo.update_idletasks()
        self._convo_canvas.configure(scrollregion=self._convo_canvas.bbox("all"))
        self._convo_canvas.yview_moveto(1.0)


class InterventionToast(tk.Frame):
    """Petit message non bloquant affiché près de la bulle."""

    def __init__(
        self,
        parent,
        message: str,
        action_label: str = "",
        on_action: Callable[[], None] | None = None,
        on_dismiss: Callable[[], None] | None = None,
        auto_hide_ms: int = 14000,
        **kwargs,
    ):
        super().__init__(
            parent,
            bg=theme.SURFACE,
            highlightthickness=1,
            highlightbackground=theme.ACCENT,
            **kwargs,
        )
        self._on_dismiss = on_dismiss
        self._hide_id: str | None = None

        body = tk.Frame(self, bg=theme.SURFACE)
        body.pack(fill="both", padx=10, pady=8)
        top = tk.Frame(body, bg=theme.SURFACE)
        top.pack(fill="x")
        tk.Label(
            top, text=message, bg=theme.SURFACE, fg=theme.TEXT,
            font=(theme.FONT_UI, 10), wraplength=260, justify="left",
        ).pack(side="left", fill="x", expand=True)
        close = tk.Label(top, text="✕", bg=theme.SURFACE, fg=theme.MUTED,
                         font=(theme.FONT_UI, 10, "bold"), cursor="hand2", padx=4)
        close.pack(side="right", anchor="n")
        close.bind("<Button-1>", lambda _e: self.dismiss())

        if action_label and on_action is not None:
            theme.make_button(
                body, text=action_label,
                command=lambda: (self.dismiss(), on_action()),
                kind="soft", padx=10, pady=4, font=(theme.FONT_UI, 9, "bold"),
            ).pack(anchor="e", pady=(8, 0))

        if auto_hide_ms > 0:
            self._hide_id = self.after(auto_hide_ms, self.dismiss)

    def dismiss(self) -> None:
        if self._hide_id is not None:
            try:
                self.after_cancel(self._hide_id)
            except Exception:
                pass
            self._hide_id = None
        callback = self._on_dismiss
        self._on_dismiss = None
        try:
            self.destroy()
        except tk.TclError:
            pass
        if callback:
            callback()
