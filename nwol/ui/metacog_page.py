# ui/metacog_page.py — Page profil métacognitif
from __future__ import annotations

import tkinter as tk

from i18n import t
from services.stats import CRITERIA, SUBJECT_LABELS, get_metacog_overview
from ui import theme
from ui.components import CanvasWheelController, MetricSparkline, RadarChartCanvas, score_color
from ui.top_nav import Tooltip

BG = theme.BG
TEXT = theme.TEXT
MUTED = theme.MUTED
BAR_BG = theme.BORDER

def _label(criterion: str) -> str:
    return t(f"metacog.{criterion}")


def _radar_label(criterion: str) -> str:
    return t(f"metacog.radar.{criterion}")


def _description(criterion: str) -> str:
    return t(f"metacog.desc.{criterion}")


class MetacogPage(tk.Frame):
    def __init__(self, master, on_back, on_meta_explanation=None, **kwargs):
        super().__init__(master, bg=BG, **kwargs)
        self._on_back = on_back
        self._on_meta_explanation = on_meta_explanation
        self._scroll_canvas: tk.Canvas | None = None
        self._scroll_window: int | None = None
        self._wheel_controller: CanvasWheelController | None = None
        self._body: tk.Frame | None = None
        self._bars: dict[str, tuple[tk.Canvas, tk.Label]] = {}
        self._radar: RadarChartCanvas | None = None
        self._subject_detail_frames: list[tk.Frame] = []
        self._build()

    def load(self) -> None:
        overview = get_metacog_overview()
        user = overview["user"]
        criteria = overview["criteria"]

        global_score = overview["global_score"]
        trend = overview["trend"]
        trend_delta = trend["delta"]

        self._name_lbl.configure(text=user["name"])
        self._sessions_lbl.configure(text=t("metacog.sessions_label", n=overview["sessions_count"]))
        self._updated_lbl.configure(text=_format_date(overview["updated_at"] or "—"))
        self._global_score_lbl.configure(text=f"{int(round(global_score))}")
        self._trend_lbl.configure(
            text=_trend_label(trend["category"]),
            fg=theme.SUCCESS if trend_delta > 2 else theme.WARNING if trend_delta < -2 else theme.ACCENT_HOVER,
            bg=theme.SUCCESS_SOFT if trend_delta > 2 else theme.WARNING_SOFT if trend_delta < -2 else theme.ACCENT_SOFT,
        )

        if self._radar is not None:
            self._radar.set_values({_radar_label(c["key"]): c["value"] for c in criteria})

        self._render_compact_bars(criteria)
        self._render_criterion_cards(criteria)
        self._render_sparklines(criteria)
        self._render_subject_cards(overview["subjects"])

        if self._scroll_canvas is not None:
            self._scroll_canvas.yview_moveto(0)

    def _build(self) -> None:
        self._scroll_canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=self._scroll_canvas.yview)
        self._scroll_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._scroll_canvas.pack(side="left", fill="both", expand=True)

        self._body = tk.Frame(self._scroll_canvas, bg=BG)
        self._scroll_window = self._scroll_canvas.create_window((0, 0), window=self._body, anchor="nw")
        self._body.bind("<Configure>", self._on_body_configure)
        self._scroll_canvas.bind("<Configure>", self._on_canvas_configure)
        self._wheel_controller = CanvasWheelController(self._scroll_canvas, self._body)

        top = tk.Frame(self._body, bg=BG)
        top.pack(fill="x", padx=56, pady=(34, 0))
        back_btn = theme.make_button(
            top,
            text=t("metacog.back"),
            command=self._handle_back,
            kind="ghost",
            font=(theme.FONT_UI, 11, "bold"),
        )
        back_btn.pack(side="left")
        Tooltip(back_btn, t("metacog.back_tip"))

        self._build_summary()
        self._build_radar_section()
        self._build_criteria_cards_section()
        self._build_evolution_section()
        self._build_subjects_section()

    def _build_summary(self) -> None:
        card = theme.surface_frame(self._body, bg=theme.SURFACE)
        card.pack(fill="x", padx=64, pady=(32, 14))
        card.configure(padx=24, pady=22)

        left = tk.Frame(card, bg=theme.SURFACE)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=t("metacog.profile_title"), bg=theme.SURFACE, fg=TEXT, font=(theme.FONT_TITLE, 28, "bold")).pack(anchor="w")
        self._name_lbl = tk.Label(left, text=t("metacog.user_default"), bg=theme.SURFACE, fg=TEXT, font=(theme.FONT_UI, 13, "bold"))
        self._name_lbl.pack(anchor="w", pady=(8, 0))
        self._sessions_lbl = tk.Label(left, text=t("metacog.sessions_label", n=0), bg=theme.SURFACE, fg=MUTED, font=(theme.FONT_UI, 11))
        self._sessions_lbl.pack(anchor="w")
        self._updated_lbl = tk.Label(left, text="—", bg=theme.SURFACE, fg=MUTED, font=(theme.FONT_UI, 10))
        self._updated_lbl.pack(anchor="w", pady=(2, 0))

        right = tk.Frame(card, bg=theme.SURFACE)
        right.pack(side="right", padx=(24, 0))
        tk.Label(right, text=t("metacog.global_score"), bg=theme.SURFACE, fg=MUTED, font=(theme.FONT_UI, 9, "bold")).pack(anchor="e")
        self._global_score_lbl = tk.Label(right, text="50", bg=theme.SURFACE, fg=TEXT, font=(theme.FONT_UI, 30, "bold"))
        self._global_score_lbl.pack(anchor="e")
        self._trend_lbl = tk.Label(
            right,
            text="stable",
            bg=theme.ACCENT_SOFT,
            fg=theme.ACCENT_HOVER,
            font=(theme.FONT_UI, 10, "bold"),
            padx=10,
            pady=4,
        )
        self._trend_lbl.pack(anchor="e", pady=(4, 0))

        help_link = tk.Label(
            card,
            text=t("metacog.explanation_link"),
            bg=theme.SURFACE,
            fg=theme.ACCENT,
            cursor="hand2",
            font=(theme.FONT_UI, 10, "underline"),
        )
        help_link.pack(anchor="e", pady=(12, 0))
        help_link.bind("<Button-1>", self._open_metacog_explanation)
        help_link.bind("<Enter>", lambda _event: help_link.configure(fg=TEXT))
        help_link.bind("<Leave>", lambda _event: help_link.configure(fg=theme.ACCENT))
        Tooltip(help_link, t("metacog.explanation_tip"))

    def _build_radar_section(self) -> None:
        section = theme.surface_frame(self._body, bg=theme.SURFACE)
        section.pack(fill="x", padx=64, pady=(0, 14))
        section.configure(padx=22, pady=20)
        tk.Label(section, text=t("metacog.general_header"), bg=theme.SURFACE, fg=TEXT, font=(theme.FONT_UI, 13, "bold")).pack(anchor="w")

        row = tk.Frame(section, bg=theme.SURFACE)
        row.pack(fill="x", pady=(14, 0))
        self._radar = RadarChartCanvas(row, labels=[_radar_label(criterion) for criterion in CRITERIA], bg=theme.SURFACE)
        self._radar.pack(side="left", fill="both", expand=True, padx=(0, 24))

        self._compact_bars_frame = tk.Frame(row, bg=theme.SURFACE)
        self._compact_bars_frame.pack(side="right", fill="both", expand=True)

    def _build_criteria_cards_section(self) -> None:
        section = theme.surface_frame(self._body, bg=theme.SURFACE)
        section.pack(fill="x", padx=64, pady=(0, 14))
        section.configure(padx=22, pady=20)
        tk.Label(section, text=t("metacog.criteria_header"), bg=theme.SURFACE, fg=TEXT, font=(theme.FONT_UI, 13, "bold")).pack(anchor="w")
        self._criteria_cards_frame = tk.Frame(section, bg=theme.SURFACE)
        self._criteria_cards_frame.pack(fill="x", pady=(12, 0))

    def _build_evolution_section(self) -> None:
        section = theme.surface_frame(self._body, bg=theme.SURFACE)
        section.pack(fill="x", padx=64, pady=(0, 14))
        section.configure(padx=22, pady=20)
        tk.Label(section, text=t("metacog.evolution_header"), bg=theme.SURFACE, fg=TEXT, font=(theme.FONT_UI, 13, "bold")).pack(anchor="w")
        tk.Label(
            section,
            text=t("metacog.evolution_subtitle"),
            bg=theme.SURFACE,
            fg=MUTED,
            font=(theme.FONT_UI, 10),
        ).pack(anchor="w", pady=(2, 0))
        self._sparklines_frame = tk.Frame(section, bg=theme.SURFACE)
        self._sparklines_frame.pack(fill="x", pady=(12, 0))

    def _build_subjects_section(self) -> None:
        section = theme.surface_frame(self._body, bg=theme.SURFACE)
        section.pack(fill="x", padx=64, pady=(0, 40))
        section.configure(padx=22, pady=20)
        tk.Label(section, text=t("metacog.subjects_header"), bg=theme.SURFACE, fg=TEXT, font=(theme.FONT_UI, 13, "bold")).pack(anchor="w")
        self._subject_hint = tk.Label(
            section,
            text=t("metacog.subjects_hint"),
            bg=theme.SURFACE,
            fg=MUTED,
            font=(theme.FONT_UI, 10, "italic"),
        )
        self._subject_hint.pack(anchor="w", pady=(8, 0))
        self._subject_cards_frame = tk.Frame(section, bg=theme.SURFACE)
        self._subject_cards_frame.pack(fill="x", pady=(12, 0))

    def _render_compact_bars(self, criteria: list[dict]) -> None:
        for child in self._compact_bars_frame.winfo_children():
            child.destroy()
        self._bars.clear()
        for entry in criteria:
            criterion = entry["key"]
            value = entry["value"]
            row = tk.Frame(self._compact_bars_frame, bg=theme.SURFACE)
            row.pack(fill="x", pady=8)
            tk.Label(row, text=_label(criterion), bg=theme.SURFACE, fg=TEXT, font=(theme.FONT_UI, 10, "bold"), width=23, anchor="w").pack(side="left")
            canvas = tk.Canvas(row, height=16, bg=theme.SURFACE, highlightthickness=0)
            canvas.pack(side="left", fill="x", expand=True, padx=10)
            value_lbl = tk.Label(row, text=str(int(round(value))), bg=theme.SURFACE, fg=TEXT, font=(theme.FONT_UI, 10, "bold"), width=4)
            value_lbl.pack(side="right")
            canvas._metac_value = value
            canvas.bind("<Configure>", lambda event, c=canvas: self._resize_bar(c, event.width))
            self._bars[criterion] = (canvas, value_lbl)

    def _resize_bar(self, canvas: tk.Canvas, width: int) -> None:
        value = float(getattr(canvas, "_metac_value", 50.0))
        theme.draw_pill_bar(canvas, width, 12, value, fill=score_color(value), background=BAR_BG, tag="bar")

    def _render_criterion_cards(self, criteria: list[dict]) -> None:
        for child in self._criteria_cards_frame.winfo_children():
            child.destroy()
        self._criteria_cards_frame.columnconfigure(0, weight=1, uniform="criteria")
        self._criteria_cards_frame.columnconfigure(1, weight=1, uniform="criteria")

        for index, entry in enumerate(criteria):
            criterion = entry["key"]
            value = entry["value"]
            delta = entry["delta"]
            card = theme.surface_frame(self._criteria_cards_frame, bg=theme.SURFACE_SOFT)
            card.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0 if index % 2 == 0 else 8, 8 if index % 2 == 0 else 0), pady=7)
            card.configure(padx=16, pady=14)
            row = tk.Frame(card, bg=theme.SURFACE_SOFT)
            row.pack(fill="x")
            tk.Label(row, text=_label(criterion), bg=theme.SURFACE_SOFT, fg=TEXT, font=(theme.FONT_UI, 11, "bold")).pack(side="left", fill="x", expand=True)
            tk.Label(row, text=f"{int(round(value))}", bg=theme.SURFACE_SOFT, fg=score_color(value), font=(theme.FONT_UI, 15, "bold")).pack(side="right")
            tk.Label(card, text=_description(criterion), bg=theme.SURFACE_SOFT, fg=MUTED, font=(theme.FONT_UI, 9), wraplength=380, justify="left").pack(anchor="w", pady=(4, 8))
            bar = tk.Canvas(card, height=14, bg=theme.SURFACE_SOFT, highlightthickness=0)
            bar.pack(fill="x")
            bar.bind("<Configure>", lambda event, c=bar, v=value: theme.draw_pill_bar(c, event.width, 10, v, fill=score_color(v), background=theme.BORDER, tag="bar"))
            badge = tk.Label(
                card,
                text=_delta_label(delta),
                bg=theme.SUCCESS_SOFT if delta > 2 else theme.WARNING_SOFT if delta < -2 else theme.ACCENT_SOFT,
                fg=theme.SUCCESS if delta > 2 else theme.WARNING if delta < -2 else theme.ACCENT_HOVER,
                font=(theme.FONT_UI, 9, "bold"),
                padx=8,
                pady=3,
            )
            badge.pack(anchor="w", pady=(8, 0))

    def _render_sparklines(self, criteria: list[dict]) -> None:
        for child in self._sparklines_frame.winfo_children():
            child.destroy()

        has_history = any(len(entry["history"]) >= 2 for entry in criteria)
        if not has_history:
            tk.Label(
                self._sparklines_frame,
                text=t("metacog.sparkline_no_data"),
                bg=theme.SURFACE,
                fg=MUTED,
                font=(theme.FONT_UI, 10, "italic"),
            ).pack(anchor="w")
            return

        for entry in criteria:
            criterion = entry["key"]
            vals = entry["history"] or [entry["value"]]
            delta = entry["delta"]
            row = tk.Frame(self._sparklines_frame, bg=theme.SURFACE)
            row.pack(fill="x", pady=6)
            tk.Label(row, text=_label(criterion), bg=theme.SURFACE, fg=TEXT, font=(theme.FONT_UI, 10, "bold"), width=24, anchor="w").pack(side="left")
            spark = MetricSparkline(row, vals, color=score_color(vals[-1]), bg=theme.SURFACE, height=42)
            spark.pack(side="left", fill="x", expand=True, padx=12)
            tk.Label(row, text=f"{int(round(vals[-1]))}", bg=theme.SURFACE, fg=score_color(vals[-1]), font=(theme.FONT_UI, 10, "bold"), width=4).pack(side="right")
            tk.Label(row, text=_delta_label(delta), bg=theme.SURFACE, fg=MUTED, font=(theme.FONT_UI, 9), width=8).pack(side="right", padx=(6, 0))

    def _render_subject_cards(self, subjects: list[dict]) -> None:
        for child in self._subject_cards_frame.winfo_children():
            child.destroy()
        self._subject_detail_frames.clear()

        if not subjects:
            self._subject_hint.pack(anchor="w", pady=(8, 0))
            return
        self._subject_hint.pack_forget()

        self._subject_cards_frame.columnconfigure(0, weight=1, uniform="subjects")
        self._subject_cards_frame.columnconfigure(1, weight=1, uniform="subjects")

        for index, entry in enumerate(subjects):
            subject = entry["subject"]
            level = entry["level"]
            label = SUBJECT_LABELS.get(subject, subject.capitalize())
            history_values = entry["history"]

            card = theme.surface_frame(self._subject_cards_frame, bg=theme.SURFACE_SOFT)
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=(0 if index % 2 == 0 else 8, 8 if index % 2 == 0 else 0), pady=7)
            card.configure(padx=16, pady=14)

            header = tk.Frame(card, bg=theme.SURFACE_SOFT)
            header.pack(fill="x")
            tk.Label(header, text=label, bg=theme.SURFACE_SOFT, fg=TEXT, font=(theme.FONT_UI, 12, "bold"), anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(header, text=str(int(round(level))), bg=theme.SURFACE_SOFT, fg=score_color(level), font=(theme.FONT_UI, 17, "bold")).pack(side="right")

            canvas = tk.Canvas(card, height=16, bg=theme.SURFACE_SOFT, highlightthickness=0)
            canvas.pack(fill="x", pady=(8, 6))
            canvas.bind("<Configure>", lambda event, c=canvas, v=level: theme.draw_pill_bar(c, event.width, 12, v, fill=score_color(v), background=theme.BORDER, tag="bar"))

            spark = MetricSparkline(card, history_values, color=score_color(level), bg=theme.SURFACE_SOFT, height=42)
            spark.pack(fill="x")

            meta = tk.Frame(card, bg=theme.SURFACE_SOFT)
            meta.pack(fill="x", pady=(8, 0))
            tk.Label(meta, text=t("metacog.updates_label", n=len(history_values)), bg=theme.SURFACE_SOFT, fg=MUTED, font=(theme.FONT_UI, 9)).pack(side="left")
            tk.Label(meta, text=_recommendation_label(entry["recommendation"]), bg=theme.SURFACE_SOFT, fg=score_color(level), font=(theme.FONT_UI, 9, "bold")).pack(side="right")

            detail = tk.Frame(card, bg=theme.SURFACE_SOFT)
            self._subject_detail_frames.append(detail)
            details_btn = theme.make_button(
                card,
                text=t("metacog.details_btn"),
                command=lambda frame=detail, values=history_values, name=label: self._toggle_subject_detail(frame, values, name),
                kind="secondary",
                padx=10,
                pady=5,
                font=(theme.FONT_UI, 9, "bold"),
            )
            details_btn.pack(anchor="w", pady=(10, 0))

    def _toggle_subject_detail(self, frame: tk.Frame, values: list[float], label: str) -> None:
        if frame.winfo_ismapped():
            frame.pack_forget()
            return
        for detail in self._subject_detail_frames:
            detail.pack_forget()
        for child in frame.winfo_children():
            child.destroy()
        frame.pack(fill="x", pady=(8, 0))
        recent = values[-6:]
        tk.Label(frame, text=t("metacog.history_label", label=label), bg=theme.SURFACE_SOFT, fg=TEXT, font=(theme.FONT_UI, 9, "bold")).pack(anchor="w")
        tk.Label(
            frame,
            text=" → ".join(str(int(round(value))) for value in recent),
            bg=theme.SURFACE_SOFT,
            fg=MUTED,
            font=(theme.FONT_UI, 9),
            wraplength=360,
            justify="left",
        ).pack(anchor="w", pady=(3, 0))

    def _handle_back(self) -> None:
        self._on_back()

    def _open_metacog_explanation(self, _event=None) -> str:
        if callable(self._on_meta_explanation):
            self._on_meta_explanation()
            return "break"

        from ui.metacog_explain_page import MetacogExplanationPage

        window = tk.Toplevel(self)
        window.title(t("metacog.window_title"))
        window.configure(bg=BG)
        window.geometry("1280x860")
        try:
            window.transient(self.winfo_toplevel())
        except tk.TclError:
            pass

        page = MetacogExplanationPage(window, on_back=window.destroy)
        page.pack(fill="both", expand=True)
        page.load()
        return "break"

    def _on_body_configure(self, _event=None) -> None:
        if self._scroll_canvas is not None:
            self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        if self._scroll_canvas is not None and self._scroll_window is not None:
            self._scroll_canvas.itemconfigure(self._scroll_window, width=event.width)

    def refresh_lang(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._scroll_canvas = None
        self._scroll_window = None
        self._wheel_controller = None
        self._body = None
        self._bars = {}
        self._radar = None
        self._subject_detail_frames = []
        self._build()
        self.load()


def _delta_label(delta: float) -> str:
    if delta > 2:
        return f"+{int(round(delta))}"
    if delta < -2:
        return str(int(round(delta)))
    return t("metacog.trend.stable")


def _trend_label(category: str) -> str:
    return t(f"metacog.trend.{category}")


def _recommendation_label(category: str) -> str:
    return t(f"metacog.rec.{category}")


def _format_date(value: str) -> str:
    if not value or value == "—":
        return "—"
    return value.replace("T", " ")[:16]
