# ui/metacog_explain_page.py — Page d'explication scientifique de la méta-cognition
from __future__ import annotations

from pathlib import Path
import tkinter as tk
from typing import Callable

import i18n
from ui import theme
from ui.components import CanvasWheelController
from ui.top_nav import Tooltip

BG = theme.BG
TEXT = theme.TEXT
MUTED = theme.MUTED
ACCENT = theme.ACCENT
SURFACE = theme.SURFACE
BORDER = theme.BORDER

_REFERENCE_AUTHORS: tuple[str, ...] = (
    "Flavell, J. H. (1979)",
    "Dunlosky, J., & Metcalfe, J. (2009)",
    "Zimmerman, B. J. (2002)",
    "Hattie, J., & Timperley, H. (2007)",
    "Roediger, H. L., & Karpicke, J. D. (2006)",
    "Dunlosky, J., Rawson, K. A., Marsh, E. J., Nathan, M. J., & Willingham, D. T. (2013)",
    "Ebbinghaus, H. (1885/1913)",
    "Cepeda, N. J., Pashler, H., Vul, E., Wixted, J. T., & Rohrer, D. (2006)",
    "Leitner, S. (1972/1973)",
    "Kornell, N., & Bjork, R. A. (2008)",
    "Taylor, K., & Rohrer, D. (2010)",
    "Bjork, E. L., & Bjork, R. A. (2011)",
    "Kang, M. J., Hsu, M., Krajbich, I. M., et al. (2009)",
    "Feynman, R. P. (1985)",
    "Chi, M. T. H., de Leeuw, N., Chiu, M.-H., & LaVancher, C. (1994)",
    "Loewenstein, G. (1994)",
    "Ainsworth, S. (2006)",
)


class MetacogExplanationPage(tk.Frame):
    """Page d'explication de la méta-cognition, entièrement traduite via i18n."""

    def __init__(self, master, on_back: Callable[[], None], **kwargs):
        super().__init__(master, bg=BG, **kwargs)
        self._on_back = on_back
        self._scroll_canvas: tk.Canvas | None = None
        self._scroll_window: int | None = None
        self._wheel_controller: CanvasWheelController | None = None
        self._body: tk.Frame | None = None
        self._diagram_img: object | None = None
        self._diagram_container: tk.Frame | None = None
        self._diagram_pil_source: object | None = None
        self._diagram_last_width: int = 0
        self._diagram_after_id: str | None = None
        self._build()
        i18n.on_lang_change(self._on_lang_change)
        self.bind("<Destroy>", lambda _: i18n.remove_lang_change(self._on_lang_change))

    def load(self) -> None:
        if self._scroll_canvas is not None:
            self._scroll_canvas.yview_moveto(0)
        self._load_diagram_image()

    # ── Scaffold (built once) ─────────────────────────────────────────────

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
        self._populate()

    # ── Content (rebuilt on lang change) ─────────────────────────────────

    def _populate(self) -> None:
        t = i18n.t

        top = tk.Frame(self._body, bg=BG)
        top.pack(fill="x", padx=56, pady=(34, 0))
        back_btn = theme.make_button(
            top,
            text=t("explain.back"),
            command=self._handle_back,
            kind="ghost",
            font=(theme.FONT_UI, 11, "bold"),
        )
        back_btn.pack(side="left")
        Tooltip(back_btn, t("explain.back_tip"))

        header = tk.Frame(self._body, bg=BG)
        header.pack(fill="x", padx=64, pady=(32, 16))
        tk.Label(
            header,
            text=t("explain.title"),
            bg=BG,
            fg=TEXT,
            font=(theme.FONT_TITLE, 27, "bold"),
        ).pack(anchor="w")
        _paragraph(header, t("explain.intro1"), bg=BG, fg=MUTED, font=(theme.FONT_UI, 12), pady=(8, 0))
        _paragraph(header, t("explain.intro2"), bg=BG, fg=MUTED, font=(theme.FONT_UI, 12), pady=(5, 0))
        _paragraph(header, t("explain.intro3"), bg=BG, fg=MUTED, font=(theme.FONT_UI, 12), pady=(5, 0))

        self._build_definition_section()
        self._build_software_methods_section()
        self._build_gauges_meaning_section()
        self._build_required_questions_section()
        self._build_flow_section()
        self._build_science_section()
        self._build_memory_methods_section()
        self._build_references_section()

    def _on_lang_change(self) -> None:
        if self._body is None:
            return
        try:
            if not self._body.winfo_exists():
                return
        except tk.TclError:
            return
        for child in self._body.winfo_children():
            child.destroy()
        self._diagram_container = None
        self._diagram_img = None
        self._diagram_pil_source = None
        self._diagram_last_width = 0
        self._diagram_after_id = None
        self._populate()

    # ── Sections ─────────────────────────────────────────────────────────

    def _build_definition_section(self) -> None:
        t = i18n.t
        section = _surface(self._body)
        _section_title(section, t("explain.def.title"))
        _paragraph(section, t("explain.def.p1"))
        _paragraph(section, t("explain.def.p2"), fg=TEXT)

    def _build_software_methods_section(self) -> None:
        t = i18n.t
        section = _surface(self._body)
        _section_title(section, t("explain.soft.title"))
        user_label = t("explain.soft.feat_user")
        sys_label = t("explain.soft.feat_sys")
        for i in range(9):
            _feature_card(
                section,
                t(f"explain.soft.{i}.title"),
                t(f"explain.soft.{i}.body"),
                t(f"explain.soft.{i}.user"),
                t(f"explain.soft.{i}.sys"),
                user_label,
                sys_label,
            )

    def _build_gauges_meaning_section(self) -> None:
        t = i18n.t
        section = _surface(self._body)
        _section_title(section, t("explain.gauges.title"))
        _paragraph(section, t("explain.gauges.intro"), fg=MUTED)
        for i in range(6):
            _card(section, t(f"explain.gauges.{i}.title"), t(f"explain.gauges.{i}.body"))

    def _build_required_questions_section(self) -> None:
        t = i18n.t
        section = _surface(self._body)
        _section_title(section, t("explain.req.title"))
        _paragraph(section, t("explain.req.p1"))
        _paragraph(section, t("explain.req.p2"), fg=MUTED)

    def _build_flow_section(self) -> None:
        t = i18n.t
        section = _surface(self._body)
        _section_title(section, t("explain.flow.title"))
        _paragraph(section, t("explain.flow.p1"))
        self._diagram_container = tk.Frame(section, bg=SURFACE)
        self._diagram_container.pack(fill="x", pady=(12, 4))
        self._diagram_container.bind("<Configure>", self._on_diagram_configure)

    def _build_science_section(self) -> None:
        t = i18n.t
        section = _surface(self._body)
        _section_title(section, t("explain.sci.title"))
        for i in range(8):
            _card(section, t(f"explain.sci.{i}.title"), t(f"explain.sci.{i}.body"))

    def _build_memory_methods_section(self) -> None:
        t = i18n.t
        section = _surface(self._body)
        _section_title(section, t("explain.mem.title"))
        _paragraph(section, t("explain.mem.intro"), fg=MUTED)
        for i in range(10):
            _card(section, t(f"explain.mem.{i}.title"), t(f"explain.mem.{i}.body"))

    def _build_references_section(self) -> None:
        t = i18n.t
        section = _surface(self._body, pady=(14, 40))
        _section_title(section, t("explain.refs.title"))
        _paragraph(section, t("explain.refs.intro"), fg=MUTED)
        for idx, author in enumerate(_REFERENCE_AUTHORS):
            frame = tk.Frame(section, bg=SURFACE)
            frame.pack(fill="x", pady=5)
            tk.Label(
                frame,
                text=author,
                bg=SURFACE,
                fg=TEXT,
                font=(theme.FONT_UI, 10, "bold"),
                anchor="w",
                justify="left",
            ).pack(anchor="w")
            _paragraph(frame, t(f"explain.refs.{idx}"), font=(theme.FONT_UI, 10), fg=MUTED, pady=(1, 0))

    # ── Diagram ───────────────────────────────────────────────────────────

    def _on_diagram_configure(self, event) -> None:
        w = event.width
        if w <= 1 or w == self._diagram_last_width:
            return
        # Debounce: cancel pending resize and schedule a fresh one
        if self._diagram_after_id is not None:
            try:
                self.after_cancel(self._diagram_after_id)
            except tk.TclError:
                pass
        self._diagram_after_id = self.after(180, lambda: self._apply_diagram_width(w))

    def _apply_diagram_width(self, w: int) -> None:
        self._diagram_after_id = None
        self._diagram_last_width = w
        self._load_diagram_image(available_width=w)

    def _load_diagram_image(self, available_width: int = 0) -> None:
        from PIL import Image, ImageTk

        container = self._diagram_container
        if container is None:
            return
        try:
            if not container.winfo_exists():
                return
        except tk.TclError:
            return

        root = Path(__file__).resolve().parents[2]
        lang = i18n.current_lang()
        png_name = "Meta-cog-schema-fr.png" if lang == "fr" else "Meta-cog-schema-en.png"
        png_path = root / "assets" / png_name
        tex_path = root / "assets" / "metacog_flow.tex"

        if not png_path.exists():
            for child in container.winfo_children():
                child.destroy()
            fallback = tk.Frame(container, bg=theme.SURFACE_SOFT, highlightthickness=1, highlightbackground=theme.BORDER)
            fallback.pack(fill="x")
            fallback.configure(padx=14, pady=12)
            _paragraph(
                fallback,
                f"Diagram not generated. LaTeX/TikZ source: "
                f"{tex_path.relative_to(root) if tex_path.exists() else 'assets/metacog_flow.tex'}.",
                bg=theme.SURFACE_SOFT,
                fg=MUTED,
                font=(theme.FONT_UI, 10, "italic"),
                pady=(0, 0),
            )
            return

        # Load or reuse cached PIL source image
        if self._diagram_pil_source is None:
            self._diagram_pil_source = Image.open(str(png_path))

        pil_src: Image.Image = self._diagram_pil_source
        w = available_width if available_width > 1 else (container.winfo_width() or 1000)
        if w <= 1:
            w = 1000

        ratio = w / pil_src.width
        new_h = max(1, int(pil_src.height * ratio))
        pil_scaled = pil_src.resize((w, new_h), Image.LANCZOS)

        photo = ImageTk.PhotoImage(pil_scaled)
        self._diagram_img = photo  # keep reference to prevent GC

        for child in container.winfo_children():
            child.destroy()
        tk.Label(container, image=self._diagram_img, bg=SURFACE).pack(anchor="center")

    # ── Canvas helpers ────────────────────────────────────────────────────

    def _on_body_configure(self, _event=None) -> None:
        if self._scroll_canvas is not None:
            self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        if self._scroll_canvas is not None and self._scroll_window is not None:
            self._scroll_canvas.itemconfigure(self._scroll_window, width=event.width)
            for label in self._body.winfo_children() if self._body else []:
                _refresh_wraplength(label, max(220, event.width - 160))

    def _handle_back(self) -> None:
        self._on_back()


# ── Widget helpers ────────────────────────────────────────────────────────


def _surface(parent: tk.Widget, pady: tuple[int, int] = (8, 0)) -> tk.Frame:
    frame = theme.surface_frame(parent, bg=SURFACE)
    frame.pack(fill="x", padx=64, pady=pady)
    frame.configure(padx=18, pady=18)
    return frame


def _section_title(parent: tk.Widget, text: str) -> None:
    tk.Label(
        parent,
        text=text,
        bg=SURFACE,
        fg=TEXT,
        font=(theme.FONT_UI, 14, "bold"),
        anchor="w",
        justify="left",
    ).pack(fill="x", anchor="w", pady=(0, 8))


def _paragraph(
    parent: tk.Widget,
    text: str,
    bg: str = SURFACE,
    fg: str = TEXT,
    font: tuple = (theme.FONT_UI, 11),
    pady: tuple[int, int] = (4, 6),
) -> tk.Label:
    label = tk.Label(
        parent,
        text=text,
        bg=bg,
        fg=fg,
        font=font,
        justify="left",
        anchor="w",
        wraplength=860,
    )
    label.pack(fill="x", anchor="w", pady=pady)
    return label


def _card(parent: tk.Widget, title: str, body: str) -> None:
    frame = tk.Frame(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
    frame.pack(fill="x", pady=6)
    frame.configure(padx=12, pady=10)
    tk.Label(
        frame,
        text=title,
        bg=SURFACE,
        fg=TEXT,
        font=(theme.FONT_UI, 11, "bold"),
        justify="left",
        anchor="w",
    ).pack(fill="x", anchor="w")
    _paragraph(frame, body, font=(theme.FONT_UI, 10), fg=MUTED, pady=(4, 0))


def _feature_card(
    parent: tk.Widget,
    title: str,
    body: str,
    user_effect: str,
    system_effect: str,
    user_label: str,
    sys_label: str,
) -> None:
    frame = tk.Frame(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
    frame.pack(fill="x", pady=7)
    frame.configure(padx=14, pady=12)
    tk.Label(
        frame,
        text=title,
        bg=SURFACE,
        fg=TEXT,
        font=(theme.FONT_UI, 11, "bold"),
        justify="left",
        anchor="w",
    ).pack(fill="x", anchor="w")
    _paragraph(frame, body, font=(theme.FONT_UI, 10), fg=MUTED, pady=(4, 8))

    grid = tk.Frame(frame, bg=SURFACE)
    grid.pack(fill="x")
    grid.columnconfigure(0, weight=1, uniform="feature")
    grid.columnconfigure(1, weight=1, uniform="feature")
    for col, (label, text) in enumerate(((user_label, user_effect), (sys_label, system_effect))):
        box = tk.Frame(grid, bg=theme.SURFACE_SOFT, highlightthickness=1, highlightbackground=theme.BORDER)
        box.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 6 if col == 0 else 0))
        box.configure(padx=10, pady=8)
        tk.Label(box, text=label, bg=theme.SURFACE_SOFT, fg=TEXT, font=(theme.FONT_UI, 9, "bold"), anchor="w").pack(fill="x")
        _paragraph(box, text, bg=theme.SURFACE_SOFT, fg=MUTED, font=(theme.FONT_UI, 9), pady=(3, 0))


def _refresh_wraplength(widget: tk.Widget, wraplength: int) -> None:
    if isinstance(widget, tk.Label):
        try:
            widget.configure(wraplength=wraplength)
        except tk.TclError:
            pass
    for child in widget.winfo_children():
        _refresh_wraplength(child, wraplength)
