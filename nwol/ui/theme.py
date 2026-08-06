# ui/theme.py — Thème visuel partagé
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont

BG = "#F4F7F8"
BG_ALT = "#EAF1F3"
SURFACE = "#FFFFFF"
SURFACE_SOFT = "#F8FBFC"
BORDER = "#D6E1E6"
BORDER_STRONG = "#B9CBD3"
TEXT = "#20303A"
TEXT_SOFT = "#344B58"
MUTED = "#667985"
MUTED_LIGHT = "#93A3AC"
DISABLED_TEXT = "#AAB7BE"
ACCENT = "#2F7D8C"
ACCENT_HOVER = "#266979"
ACCENT_SOFT = "#E4F2F4"
ACCENT_SOFT_HOVER = "#D2E9ED"
DANGER = "#B65A4A"
DANGER_HOVER = "#93483C"
DANGER_SOFT = "#F9E8E4"
DANGER_SOFT_HOVER = "#F3D7D0"
WARNING = "#9A6B22"
WARNING_SOFT = "#FFF5DA"
SUCCESS = "#2F8A66"
SUCCESS_SOFT = "#E9F7F0"
QUESTION = "#EAF4FF"
QUESTION_BORDER = "#5B91C9"

FONT_UI = "Helvetica"
FONT_TITLE = "Georgia"
FONT_MONO = "Courier"

RADIUS_SM = 10
RADIUS_MD = 16
RADIUS_LG = 22
RADIUS_XL = 30

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 14
SPACE_LG = 22
SPACE_XL = 34

ANIM_FAST = 120
ANIM_NORMAL = 180
ANIM_SLOW = 280
ANIM_FESTIVE = 420

PREFERS_REDUCED_MOTION = False


BUTTON_STYLES = {
    "primary": {
        "bg": ACCENT_SOFT,
        "fg": ACCENT,
        "hover": ACCENT_SOFT_HOVER,
        "active": ACCENT_SOFT_HOVER,
        "border": ACCENT,
    },
    "secondary": {
        "bg": SURFACE,
        "fg": TEXT,
        "hover": "#EDF4F6",
        "active": "#E4EEF1",
    },
    "ghost": {
        "bg": BG,
        "fg": MUTED,
        "hover": "#EAF1F3",
        "active": "#DFEAEE",
    },
    "soft": {
        "bg": ACCENT_SOFT,
        "fg": ACCENT_HOVER,
        "hover": ACCENT_SOFT_HOVER,
        "active": ACCENT_SOFT_HOVER,
    },
    "danger": {
        "bg": DANGER_SOFT,
        "fg": DANGER,
        "hover": DANGER_SOFT_HOVER,
        "active": DANGER_SOFT_HOVER,
    },
    "warning": {
        "bg": WARNING_SOFT,
        "fg": WARNING,
        "hover": "#FFE9AF",
        "active": "#FFE9AF",
    },
}


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


def animate(widget, duration_ms: int, update, done=None, fps: int = 60):
    if PREFERS_REDUCED_MOTION or duration_ms <= 0:
        update(1.0)
        if done:
            done()
        return None

    steps = max(1, int(duration_ms / max(1, 1000 / fps)))
    frame_ms = max(1, int(duration_ms / steps))

    def tick(step: int = 0):
        progress = min(1.0, step / steps)
        update(progress)
        if step >= steps:
            if done:
                done()
        else:
            widget.after(frame_ms, lambda: tick(step + 1))

    tick()
    return None


def configure_root(root: tk.Tk) -> None:
    root.configure(bg=BG)
    root.option_add("*Font", f"{FONT_UI} 11")
    root.option_add("*selectBackground", ACCENT_SOFT_HOVER)
    root.option_add("*selectForeground", TEXT)
    root.option_add("*insertBackground", TEXT)


def style_button(button: tk.Button, kind: str = "secondary") -> tk.Button:
    style = BUTTON_STYLES.get(kind, BUTTON_STYLES["secondary"])
    border_color = style.get("border", BORDER)
    button.configure(
        bg=style["bg"],
        fg=style["fg"],
        activebackground=style["active"],
        activeforeground=style["fg"],
        disabledforeground=DISABLED_TEXT,
        relief=tk.FLAT,
        bd=0,
        highlightthickness=1,
        highlightbackground=border_color,
        highlightcolor=border_color,
        cursor="hand2",
        padx=14,
        pady=8,
        font=(FONT_UI, 10, "bold"),
    )

    def _enter(_event=None) -> None:
        if str(button.cget("state")) != tk.DISABLED:
            button.configure(bg=style["hover"])

    def _leave(_event=None) -> None:
        if str(button.cget("state")) != tk.DISABLED:
            button.configure(bg=style["bg"])

    button.bind("<Enter>", _enter, add="+")
    button.bind("<Leave>", _leave, add="+")
    return button


def make_button(parent, text: str, command=None, kind: str = "secondary", **kwargs) -> tk.Button:
    button = tk.Button(parent, text=text, command=command)
    style_button(button, kind=kind)
    if kwargs:
        button.configure(**kwargs)
    return button


def make_label(parent, text: str = "", role: str = "body", **kwargs) -> tk.Label:
    styles = {
        "title": {"font": (FONT_TITLE, 30, "bold"), "fg": TEXT},
        "subtitle": {"font": (FONT_UI, 12), "fg": MUTED},
        "section": {"font": (FONT_UI, 12, "bold"), "fg": TEXT},
        "body": {"font": (FONT_UI, 11), "fg": TEXT},
        "muted": {"font": (FONT_UI, 10), "fg": MUTED},
        "metric": {"font": (FONT_UI, 17, "bold"), "fg": TEXT},
    }
    style = styles.get(role, styles["body"])
    return tk.Label(parent, text=text, bg=kwargs.pop("bg", BG), **style, **kwargs)


def surface_frame(parent, bg: str = SURFACE, **kwargs) -> tk.Frame:
    return tk.Frame(
        parent,
        bg=bg,
        highlightthickness=1,
        highlightbackground=kwargs.pop("highlightbackground", BORDER),
        highlightcolor=kwargs.pop("highlightcolor", BORDER),
        **kwargs,
    )


def divider(parent, padx: int = 0, pady: tuple[int, int] = (0, 0)) -> tk.Frame:
    line = tk.Frame(parent, bg=BORDER, height=1)
    line.pack(fill="x", padx=padx, pady=pady)
    return line


def style_entry(entry: tk.Entry | tk.Text) -> tk.Entry | tk.Text:
    entry.configure(
        bg=SURFACE,
        fg=TEXT,
        relief=tk.FLAT,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=ACCENT,
        insertbackground=TEXT,
    )
    return entry


def style_listbox(listbox: tk.Listbox) -> tk.Listbox:
    listbox.configure(
        bg=SURFACE,
        fg=TEXT,
        selectbackground=ACCENT_SOFT_HOVER,
        selectforeground=TEXT,
        relief=tk.FLAT,
        bd=0,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=ACCENT,
        activestyle="none",
    )
    return listbox


def title_font(size: int = 30, weight: str = "bold") -> tkfont.Font:
    return tkfont.Font(family=FONT_TITLE, size=size, weight=weight)


def ui_font(size: int = 11, weight: str = "normal") -> tkfont.Font:
    return tkfont.Font(family=FONT_UI, size=size, weight=weight)


def create_round_rect(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float, radius: float = 18, **kwargs):
    radius = max(2, min(radius, abs(x1 - x0) / 2, abs(y1 - y0) / 2))
    points = [
        x0 + radius, y0,
        x1 - radius, y0,
        x1, y0,
        x1, y0 + radius,
        x1, y1 - radius,
        x1, y1,
        x1 - radius, y1,
        x0 + radius, y1,
        x0, y1,
        x0, y1 - radius,
        x0, y0 + radius,
        x0, y0,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=16, **kwargs)


def draw_pill_bar(
    canvas: tk.Canvas,
    width: int,
    height: int,
    value: float,
    *,
    fill: str = ACCENT,
    background: str = BORDER,
    tag: str = "bar",
) -> None:
    canvas.delete(tag)
    width = max(12, int(width))
    height = max(6, int(height))
    value = max(0.0, min(100.0, float(value)))
    y = height / 2
    margin = height / 2
    x0 = margin
    x1 = max(x0 + 1, width - margin)
    canvas.create_line(x0, y, x1, y, fill=background, width=height, capstyle=tk.ROUND, tags=tag)
    if value > 0:
        x_fill = x0 + (x1 - x0) * value / 100.0
        canvas.create_line(x0, y, x_fill, y, fill=fill, width=height, capstyle=tk.ROUND, tags=tag)
