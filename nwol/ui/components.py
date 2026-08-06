# ui/components.py — Composants visuels réutilisables
from __future__ import annotations

import math
import platform
import random
import tkinter as tk

from ui import theme
from ui.rich_text import rich_text_widget


def clamp_score(value: float) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def score_color(value: float) -> str:
    value = clamp_score(value)
    if value >= 75:
        return theme.SUCCESS
    if value >= 45:
        return theme.ACCENT
    return theme.WARNING


class CanvasWheelController:
    """Route mouse-wheel events from a canvas subtree to the canvas scroll view."""

    _CHILD_SCROLLABLE_CLASSES = {"Text", "Listbox"}
    _SEQUENCES = ("<MouseWheel>", "<Button-4>", "<Button-5>")

    def __init__(
        self,
        canvas: tk.Canvas,
        *roots: tk.Widget,
        units_per_notch: int = 2,
        max_units: int = 8,
        respect_child_scroll: bool = True,
    ):
        self.canvas = canvas
        self.roots = tuple(root for root in roots if root is not None)
        self.units_per_notch = max(1, int(units_per_notch))
        self.max_units = max(1, int(max_units))
        self.respect_child_scroll = respect_child_scroll
        self._platform = platform.system()
        self._refresh_job: str | None = None
        self._destroyed = False
        self._tag = f"NWoLWheel{ id(self) }"

        for sequence in self._SEQUENCES:
            self.canvas.bind_class(self._tag, sequence, self._on_mousewheel, add="+")

        for root in (self.canvas, *self.roots):
            root.bind("<Configure>", self._schedule_refresh, add="+")
        self.canvas.bind("<Destroy>", self.destroy, add="+")
        self.refresh()

    def refresh(self) -> None:
        if self._destroyed:
            return
        for root in (self.canvas, *self.roots):
            self._apply_tag(root)

    def destroy(self, _event=None) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        if self._refresh_job:
            try:
                self.canvas.after_cancel(self._refresh_job)
            except tk.TclError:
                pass
            self._refresh_job = None
        for sequence in self._SEQUENCES:
            try:
                self.canvas.unbind_class(self._tag, sequence)
            except tk.TclError:
                pass

    def _schedule_refresh(self, _event=None) -> None:
        if self._destroyed or self._refresh_job:
            return
        try:
            self._refresh_job = self.canvas.after_idle(self._run_scheduled_refresh)
        except tk.TclError:
            self._refresh_job = None

    def _run_scheduled_refresh(self) -> None:
        self._refresh_job = None
        self.refresh()

    def _apply_tag(self, widget: tk.Widget) -> None:
        try:
            tags = tuple(widget.bindtags())
            if self._tag not in tags:
                class_tag = widget.winfo_class()
                try:
                    class_index = tags.index(class_tag)
                except ValueError:
                    class_index = 1 if len(tags) > 1 else len(tags)
                widget.bindtags(tags[:class_index] + (self._tag,) + tags[class_index:])
            children = widget.winfo_children()
        except tk.TclError:
            return
        for child in children:
            self._apply_tag(child)

    def _on_mousewheel(self, event: tk.Event) -> str | None:
        pixels = self._event_pixels(event)
        if pixels == 0:
            return "break"
        if self.respect_child_scroll and self._child_can_scroll(getattr(event, "widget", None), pixels):
            return None
        if not self._canvas_can_scroll(pixels):
            return "break"
        if not self._scroll_canvas_pixels(pixels):
            return "break"
        return "break"

    def _event_pixels(self, event: tk.Event) -> float:
        num = getattr(event, "num", None)
        if num == 4:
            return -24.0 * self.units_per_notch
        if num == 5:
            return 24.0 * self.units_per_notch

        try:
            delta = float(getattr(event, "delta", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
        if delta == 0:
            return 0.0

        if self._platform == "Darwin" and abs(delta) < 120:
            pixels = -delta * 6.0
        else:
            pixels = -(delta / 120.0) * 24.0 * self.units_per_notch
        max_pixels = 24.0 * self.max_units
        return max(-max_pixels, min(max_pixels, pixels))

    def _child_can_scroll(self, widget: tk.Widget | None, pixels: float) -> bool:
        if widget is None or widget is self.canvas:
            return False
        try:
            if widget.winfo_class() not in self._CHILD_SCROLLABLE_CLASSES:
                return False
            first, last = widget.yview()
        except (tk.TclError, AttributeError):
            return False
        if last - first >= 0.999:
            return False
        return first > 0.001 if pixels < 0 else last < 0.999

    def _canvas_can_scroll(self, pixels: float) -> bool:
        try:
            first, last = self.canvas.yview()
        except tk.TclError:
            return False
        if last - first >= 0.999:
            return False
        return first > 0.001 if pixels < 0 else last < 0.999

    def _scroll_canvas_pixels(self, pixels: float) -> bool:
        try:
            bbox = self.canvas.bbox("all")
            if not bbox:
                return False
            content_height = max(1.0, float(bbox[3] - bbox[1]))
            viewport_height = max(1.0, float(self.canvas.winfo_height()))
            if content_height <= viewport_height:
                return False
            first, _last = self.canvas.yview()
            top = first * content_height
            target = max(0.0, min(content_height - viewport_height, top + pixels))
            self.canvas.yview_moveto(target / content_height)
            return True
        except tk.TclError:
            return False


def draw_sparkline(
    canvas: tk.Canvas,
    values,
    width: int,
    height: int,
    color: str = theme.ACCENT,
    *,
    tag: str = "sparkline",
) -> None:
    canvas.delete(tag)
    vals = [clamp_score(v) for v in (values or [])]
    width = max(80, int(width))
    height = max(34, int(height))
    pad_x = 8
    pad_y = 7
    canvas.create_line(
        pad_x,
        height - pad_y,
        width - pad_x,
        height - pad_y,
        fill=theme.BORDER,
        width=1,
        tags=tag,
    )
    if len(vals) < 2:
        y = height - pad_y - ((vals[0] if vals else 50.0) / 100.0) * (height - pad_y * 2)
        canvas.create_oval(width / 2 - 3, y - 3, width / 2 + 3, y + 3, fill=color, outline="", tags=tag)
        return

    span = max(1, len(vals) - 1)
    coords: list[float] = []
    for index, value in enumerate(vals):
        x = pad_x + (width - pad_x * 2) * index / span
        y = height - pad_y - (value / 100.0) * (height - pad_y * 2)
        coords.extend([x, y])

    canvas.create_line(*coords, fill=color, width=2, smooth=True, splinesteps=12, tags=tag)
    x0, y0 = coords[0], coords[1]
    x1, y1 = coords[-2], coords[-1]
    canvas.create_oval(x0 - 2, y0 - 2, x0 + 2, y0 + 2, fill=theme.MUTED_LIGHT, outline="", tags=tag)
    canvas.create_oval(x1 - 3, y1 - 3, x1 + 3, y1 + 3, fill=color, outline="", tags=tag)


class LoadingState(tk.Frame):
    def __init__(self, master, text: str = "Chargement en cours", **kwargs):
        super().__init__(master, bg=kwargs.pop("bg", theme.BG), **kwargs)
        self._text = text
        self._job: str | None = None
        self._idx = 0
        self._glyphs = ("·  ", "·· ", "···", " ··")
        self._label = tk.Label(
            self,
            text=text,
            bg=self.cget("bg"),
            fg=theme.MUTED,
            font=(theme.FONT_UI, 11, "italic"),
            padx=12,
            pady=10,
        )
        self._label.pack(anchor="w", fill="x")

    def start(self, text: str | None = None) -> None:
        if text is not None:
            self._text = text
        self.stop()
        self._idx = 0
        self._tick()

    def stop(self) -> None:
        if self._job:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _tick(self) -> None:
        if not self.winfo_exists():
            return
        glyph = self._glyphs[self._idx % len(self._glyphs)]
        self._label.configure(text=f"{self._text} {glyph}")
        self._idx += 1
        self._job = self.after(300, self._tick)

    def destroy(self) -> None:
        self.stop()
        super().destroy()


class ConfettiCanvas(tk.Canvas):
    _COLORS = (
        theme.ACCENT,
        theme.SUCCESS,
        theme.WARNING,
        theme.QUESTION_BORDER,
        theme.BORDER_STRONG,
    )

    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            height=54,
            bg=kwargs.pop("bg", theme.SURFACE),
            highlightthickness=0,
            **kwargs,
        )
        self._particles: list[dict] = []
        self._job: str | None = None
        self._running = False
        self._loop = False

    def start(self, duration_ms: int = 1000, loop: bool = True) -> None:
        self.stop()
        self._running = True
        self._loop = loop
        self._particles = self._spawn_particles(duration_ms)
        self._tick()

    def stop(self) -> None:
        self._running = False
        if self._job:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        self.delete("confetti")

    def _spawn_particles(self, duration_ms: int) -> list[dict]:
        width = max(320, self.winfo_width())
        height = max(44, self.winfo_height())
        count = 16
        particles: list[dict] = []
        for _ in range(count):
            particles.append({
                "x": random.randint(8, width - 8),
                "y": height + random.randint(0, 26),
                "dx": random.uniform(-0.45, 0.45),
                "dy": random.uniform(0.9, 2.1),
                "size": random.randint(3, 6),
                "age": random.randint(0, 10),
                "life": max(22, int(duration_ms / 34) + random.randint(-6, 8)),
                "color": random.choice(self._COLORS),
                "star": random.choice((True, False, False)),
            })
        return particles

    def _tick(self) -> None:
        if not self._running:
            return
        try:
            self.delete("confetti")
        except tk.TclError:
            return
        alive = False
        for particle in self._particles:
            particle["age"] += 1
            if particle["age"] <= particle["life"]:
                alive = True
            progress = min(1.0, particle["age"] / max(1, particle["life"]))
            x = particle["x"] + particle["dx"] * particle["age"] * 2.0
            y = particle["y"] - particle["dy"] * particle["age"] - math.sin(progress * math.pi) * 8
            size = particle["size"] * (1.0 - progress * 0.45)
            if size <= 1:
                continue
            if particle["star"]:
                self._star(x, y, size, particle["color"])
            else:
                self.create_oval(x - size, y - size, x + size, y + size, fill=particle["color"], outline="", tags="confetti")
        if not alive:
            if not self._loop:
                self.stop()
                return
            self._particles = self._spawn_particles(1000)
        self._job = self.after(34, self._tick)

    def _star(self, x: float, y: float, radius: float, color: str) -> None:
        points: list[float] = []
        for i in range(10):
            angle = -math.pi / 2 + i * math.pi / 5
            r = radius if i % 2 == 0 else radius * 0.45
            points.extend([x + math.cos(angle) * r, y + math.sin(angle) * r])
        self.create_polygon(points, fill=color, outline="", tags="confetti")

    def destroy(self) -> None:
        self.stop()
        super().destroy()


class AnimatedStatCard(tk.Frame):
    def __init__(self, master, label: str, value: str = "—", **kwargs):
        super().__init__(
            master,
            bg=kwargs.pop("bg", theme.SURFACE),
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            **kwargs,
        )
        self._label = tk.Label(
            self,
            text=label,
            bg=self.cget("bg"),
            fg=theme.MUTED,
            font=(theme.FONT_UI, 9, "bold"),
        )
        self._label.pack(anchor="w", padx=12, pady=(8, 0))
        self._value = tk.Label(
            self,
            text=value,
            bg=self.cget("bg"),
            fg=theme.TEXT,
            font=(theme.FONT_UI, 15, "bold"),
        )
        self._value.pack(anchor="w", padx=12, pady=(0, 9))

    def reveal(self, value: str) -> None:
        self._value.configure(text=value, fg=theme.MUTED)

        def _update(progress: float) -> None:
            eased = theme.ease_out_cubic(progress)
            size = 12 + int(3 * eased)
            self._value.configure(font=(theme.FONT_UI, size, "bold"), fg=theme.TEXT if progress >= 1 else theme.MUTED)

        theme.animate(self, theme.ANIM_NORMAL, _update)

    def set_value(self, value: str) -> None:
        self._value.configure(text=value, fg=theme.TEXT, font=(theme.FONT_UI, 15, "bold"))


class MetricSparkline(tk.Canvas):
    def __init__(self, master, values=None, color: str = theme.ACCENT, **kwargs):
        super().__init__(
            master,
            height=kwargs.pop("height", 44),
            bg=kwargs.pop("bg", theme.SURFACE),
            highlightthickness=0,
            **kwargs,
        )
        self._values = list(values or [])
        self._color = color
        self.bind("<Configure>", lambda event: self._redraw(event.width, event.height))

    def set_values(self, values, color: str | None = None) -> None:
        self._values = list(values or [])
        if color:
            self._color = color
        self._redraw(max(1, self.winfo_width()), max(1, self.winfo_height()))

    def _redraw(self, width: int, height: int) -> None:
        draw_sparkline(self, self._values, width, height, self._color)


class RadarChartCanvas(tk.Canvas):
    def __init__(self, master, labels: list[str], values: dict[str, float] | None = None, **kwargs):
        super().__init__(
            master,
            width=kwargs.pop("width", 320),
            height=kwargs.pop("height", 280),
            bg=kwargs.pop("bg", theme.SURFACE),
            highlightthickness=0,
            **kwargs,
        )
        self._labels = labels
        self._values = values or {}
        self.bind("<Configure>", lambda _event: self._redraw())

    def set_values(self, values: dict[str, float]) -> None:
        self._values = dict(values or {})
        self._redraw()

    def _redraw(self) -> None:
        self.delete("radar")
        labels = self._labels
        if not labels:
            return
        width = max(260, self.winfo_width())
        height = max(230, self.winfo_height())
        cx = width / 2
        cy = height / 2 + 8
        radius = min(width, height) * 0.31
        count = len(labels)

        for pct in (0.25, 0.5, 0.75, 1.0):
            points = self._radar_points(cx, cy, radius * pct, count)
            self.create_polygon(points, outline=theme.BORDER, fill="", width=1, tags="radar")
            if pct < 1:
                self.create_text(
                    cx + 4,
                    cy - radius * pct,
                    text=str(int(pct * 100)),
                    fill=theme.MUTED_LIGHT,
                    font=(theme.FONT_UI, 8),
                    anchor="w",
                    tags="radar",
                )

        value_points: list[float] = []
        for index, label in enumerate(labels):
            angle = -math.pi / 2 + index * 2 * math.pi / count
            axis_x = cx + math.cos(angle) * radius
            axis_y = cy + math.sin(angle) * radius
            self.create_line(cx, cy, axis_x, axis_y, fill=theme.BORDER_STRONG, width=1, tags="radar")
            label_x = cx + math.cos(angle) * (radius + 38)
            label_y = cy + math.sin(angle) * (radius + 32)
            anchor = "center"
            if math.cos(angle) > 0.35:
                anchor = "w"
            elif math.cos(angle) < -0.35:
                anchor = "e"
            self.create_text(
                label_x,
                label_y,
                text=label,
                fill=theme.TEXT_SOFT,
                font=(theme.FONT_UI, 9, "bold"),
                anchor=anchor,
                width=92,
                justify="center",
                tags="radar",
            )
            value = clamp_score(self._values.get(label, 50.0)) / 100.0
            value_points.extend([
                cx + math.cos(angle) * radius * value,
                cy + math.sin(angle) * radius * value,
            ])

        if len(value_points) >= 6:
            self.create_polygon(
                value_points,
                fill=theme.ACCENT_SOFT,
                outline=theme.ACCENT,
                width=2,
                tags="radar",
            )
            for x, y in zip(value_points[0::2], value_points[1::2]):
                self.create_oval(x - 4, y - 4, x + 4, y + 4, fill=theme.ACCENT, outline=theme.SURFACE, width=1, tags="radar")

    @staticmethod
    def _radar_points(cx: float, cy: float, radius: float, count: int) -> list[float]:
        points: list[float] = []
        for index in range(count):
            angle = -math.pi / 2 + index * 2 * math.pi / count
            points.extend([cx + math.cos(angle) * radius, cy + math.sin(angle) * radius])
        return points


class SectionCard(tk.Frame):
    def __init__(
        self,
        master,
        title: str,
        description: str = "",
        badge: str = "",
        *,
        bg: str = theme.SURFACE,
        **kwargs,
    ):
        super().__init__(
            master,
            bg=bg,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            padx=16,
            pady=14,
            **kwargs,
        )
        header = tk.Frame(self, bg=bg)
        header.pack(fill="x")
        tk.Label(header, text=title, bg=bg, fg=theme.TEXT, font=(theme.FONT_UI, 12, "bold"), anchor="w").pack(side="left", fill="x", expand=True)
        if badge:
            tk.Label(
                header,
                text=badge,
                bg=theme.ACCENT_SOFT,
                fg=theme.ACCENT_HOVER,
                font=(theme.FONT_UI, 9, "bold"),
                padx=8,
                pady=3,
            ).pack(side="right")
        if description:
            rich_text_widget(
                self,
                description,
                bg=bg,
                fg=theme.TEXT_SOFT,
                font=(theme.FONT_UI, 10),
            ).pack(fill="x", pady=(8, 0))


class FlipCardCanvas(tk.Canvas):
    """Canvas autonome pour les cartes simples ; les pages peuvent aussi utiliser sa logique."""

    def __init__(self, master, front: str = "", back: str = "", **kwargs):
        super().__init__(
            master,
            width=kwargs.pop("width", 700),
            height=kwargs.pop("height", 300),
            bg=kwargs.pop("bg", theme.BG),
            highlightthickness=0,
            **kwargs,
        )
        self.front = front
        self.back = back
        self.showing_back = False
        self._progress = 1.0
        self._swapped = False
        self._animating = False
        self.bind("<Configure>", lambda _event: self._draw())

    def set_content(self, front: str, back: str) -> None:
        self.front = front
        self.back = back
        self.showing_back = False
        self._progress = 1.0
        self._draw()

    def flip(self) -> None:
        if self._animating:
            return
        self._animating = True
        self._swapped = False

        def _update(progress: float) -> None:
            eased = theme.ease_in_out_cubic(progress)
            self._progress = eased
            if eased >= 0.5 and not self._swapped:
                self.showing_back = not self.showing_back
                self._swapped = True
            self._draw()

        def _done() -> None:
            self._progress = 1.0
            self._animating = False
            self._draw()

        theme.animate(self, theme.ANIM_SLOW, _update, _done)

    def _draw(self) -> None:
        self.delete("flip")
        width = max(360, self.winfo_width() - 36)
        height = max(200, self.winfo_height() - 34)
        progress = self._progress if self._animating else 1.0
        visible = abs(math.cos(math.radians(progress * 180)))
        draw_w = width * max(0.08, visible)
        draw_h = height - (1 - visible) * 16
        x0 = (self.winfo_width() - draw_w) / 2
        y0 = (self.winfo_height() - draw_h) / 2
        x1 = x0 + draw_w
        y1 = y0 + draw_h
        fill = theme.WARNING_SOFT if self.showing_back else theme.SURFACE
        outline = theme.WARNING if self.showing_back else theme.BORDER
        theme.create_round_rect(self, x0 + 5, y0 + 7, x1 + 5, y1 + 7, radius=theme.RADIUS_LG, fill=theme.BORDER, outline="", tags="flip")
        theme.create_round_rect(self, x0, y0, x1, y1, radius=theme.RADIUS_LG, fill=fill, outline=outline, width=2, tags="flip")
        if visible > 0.18:
            self.create_text(
                self.winfo_width() / 2,
                self.winfo_height() / 2,
                text=self.back if self.showing_back else self.front,
                fill=theme.TEXT,
                font=(theme.FONT_TITLE, 22, "bold"),
                width=max(90, draw_w - 48),
                justify="center",
                tags="flip",
            )
