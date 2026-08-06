# ui/home.py — Écran d'accueil MetaC-App
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog

import i18n as _i18n
from i18n import t
from db.user import DEFAULT_USER_ID, set_user_lang
from ui import theme
from ui.top_nav import Tooltip

BG = theme.BG
TILE_ON_BG = theme.SURFACE
TILE_ON_HOV = theme.ACCENT_SOFT
TILE_OFF_BG = "#EEF2F4"
TEXT_DARK = theme.TEXT
TEXT_MUTED = theme.MUTED
TEXT_DIS = theme.DISABLED_TEXT
TILE_WIDTH = 310
TILE_HEIGHT = 220
TILE_GAP = 14


FEATURES = [
    {"id": "import",     "icon": "📄", "active": True},
    {"id": "flashcards", "icon": "🗂", "active": True},
    {"id": "quiz",       "icon": "🧠", "active": True},
    {"id": "lang_learn", "icon": "🌍", "active": True},
]

_FEAT_KEYS: dict[str, tuple[str, str]] = {
    "import":     ("home.feat.import",      "home.feat.import_tip"),
    "flashcards": ("home.feat.flashcards",  "home.feat.flashcards_tip"),
    "quiz":       ("home.feat.quiz",        "home.feat.quiz_tip"),
    "lang_learn": ("home.feat.lang_learn", "home.feat.lang_learn_tip"),
}


class _Tile(tk.Frame):
    def __init__(self, parent, feature: dict, on_click, **kwargs):
        active = feature["active"]
        bg = TILE_ON_BG if active else TILE_OFF_BG
        super().__init__(
            parent,
            bg=bg,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.ACCENT,
            **kwargs,
        )
        self._feature = feature
        self._on_click = on_click
        self._bg = bg
        self._hover = TILE_ON_HOV if active else TILE_OFF_BG
        self._active = active
        self._build()

    def _build(self):
        fg = TEXT_DARK if self._active else TEXT_DIS
        icon_fg = theme.ACCENT if self._active else TEXT_DIS

        content = tk.Frame(self, bg=self._bg)
        content.place(relx=0.5, rely=0.48, anchor="center")

        icon = tk.Label(content, text=self._feature["icon"], font=(theme.FONT_UI, 32, "bold"), bg=self._bg, fg=icon_fg)
        icon.pack(pady=(0, 12))
        label = tk.Label(
            content,
            text=self._feature["label"],
            font=(theme.FONT_UI, 14, "bold" if self._active else "normal"),
            bg=self._bg,
            fg=fg,
            justify="center",
            wraplength=TILE_WIDTH - 38,
        )
        label.pack()

        if not self._active:
            tk.Label(
                content,
                text=t("home.soon"),
                font=(theme.FONT_UI, 10),
                bg=self._bg,
                fg=TEXT_DIS,
            ).pack(pady=(10, 0))

        if self._active:
            self.configure(cursor="hand2")
            for widget in (self, content, icon, label):
                widget.bind("<Enter>", self._enter)
                widget.bind("<Leave>", self._leave)
                widget.bind("<Button-1>", self._click)
        Tooltip(self, self._feature.get("tip", self._feature["label"]))

    def _enter(self, _event=None):
        if self._active:
            self.configure(highlightbackground=theme.ACCENT)
        self._paint(self._hover)

    def _leave(self, _event=None):
        self.configure(highlightbackground=theme.BORDER)
        self._paint(self._bg)

    def _click(self, _event=None):
        self._on_click(self._feature["id"])

    def _paint(self, color: str):
        self.configure(bg=color)
        self._paint_children(self, color)

    def _paint_children(self, widget, color: str):
        for child in widget.winfo_children():
            child.configure(bg=color)
            self._paint_children(child, color)


class HomeScreen(tk.Frame):
    def __init__(self, parent, on_import_pdf, on_flashcards=None, on_profile=None, on_quiz=None, on_lang_learn=None, streak: int = 1, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._on_import_pdf = on_import_pdf
        self._on_flashcards = on_flashcards
        self._on_profile = on_profile
        self._on_quiz = on_quiz
        self._on_lang_learn = on_lang_learn
        self._streak = streak
        _i18n.on_lang_change(self._on_lang_change)
        self._build()

    def destroy(self):
        _i18n.remove_lang_change(self._on_lang_change)
        super().destroy()

    def _build(self):
        shell = tk.Frame(self, bg=BG)
        shell.pack(fill="both", expand=True, padx=40, pady=28)

        header = tk.Frame(shell, bg=BG)
        header.pack(fill="x")

        left = tk.Frame(header, bg=BG)
        left.pack(side="left", fill="x", expand=True)

        tk.Label(
            left,
            text="MetaC-App",
            font=(theme.FONT_TITLE, 40, "bold"),
            bg=BG,
            fg=TEXT_DARK,
        ).pack(anchor="w")

        tk.Label(
            left,
            text=t("home.subtitle"),
            font=(theme.FONT_UI, 12),
            bg=BG,
            fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(4, 0))

        self._build_streak_badge(header)

        theme.divider(shell, pady=(22, 20))

        grid_zone = tk.Frame(shell, bg=BG)
        grid_zone.pack(fill="both", expand=True)

        grid = tk.Frame(grid_zone, bg=BG)
        grid.place(relx=0.5, rely=0.46, anchor="center")
        for index, feat in enumerate(FEATURES):
            row, col = divmod(index, 2)
            active = feat["active"]
            if feat["id"] == "flashcards":
                active = active and self._on_flashcards is not None
            if feat["id"] == "quiz":
                active = active and self._on_quiz is not None
            if feat["id"] == "lang_learn":
                active = active and self._on_lang_learn is not None
            label_key, tip_key = _FEAT_KEYS.get(feat["id"], ("home.feat.coming_soon", "home.feat.coming_soon_tip"))
            feature = {**feat, "label": t(label_key), "tip": t(tip_key), "active": active}
            tile = _Tile(grid, feature, on_click=self._tile_click, width=TILE_WIDTH, height=TILE_HEIGHT)
            tile.grid(row=row, column=col, padx=TILE_GAP, pady=TILE_GAP)
            tile.grid_propagate(False)

        # Bouton profil rond fixe en bas à gauche de la fenêtre
        if self._on_profile:
            self._build_profile_button()

    def _build_streak_badge(self, parent):
        label = t("home.streak.day") if self._streak == 1 else t("home.streak.days")
        badge = tk.Frame(
            parent,
            bg=theme.WARNING_SOFT,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
        )
        badge.pack(side="right", anchor="ne", pady=4)

        tk.Label(
            badge,
            text="🔥",
            font=(theme.FONT_UI, 20),
            bg=theme.WARNING_SOFT,
        ).pack(side="left", padx=(12, 4), pady=10)

        inner = tk.Frame(badge, bg=theme.WARNING_SOFT)
        inner.pack(side="left", padx=(0, 14), pady=8)

        tk.Label(
            inner,
            text=str(self._streak),
            font=(theme.FONT_UI, 20, "bold"),
            bg=theme.WARNING_SOFT,
            fg=theme.WARNING,
        ).pack(anchor="w")

        tk.Label(
            inner,
            text=label,
            font=(theme.FONT_UI, 9),
            bg=theme.WARNING_SOFT,
            fg=theme.WARNING,
        ).pack(anchor="w")

        streak_tip = t("home.streak.tip_plural", n=self._streak) if self._streak > 1 else t("home.streak.tip", n=self._streak)
        Tooltip(badge, streak_tip)

        # Language toggle — segmented FR | EN switch
        lang = _i18n.current_lang()

        toggle_wrap = tk.Frame(parent, bg=theme.BORDER_STRONG, highlightthickness=0)
        toggle_wrap.pack(side="right", anchor="ne", pady=14, padx=(0, 22))

        for code in ("fr", "en"):
            is_active = (code == lang)
            lbl = tk.Label(
                toggle_wrap,
                text=code.upper(),
                font=(theme.FONT_UI, 11, "bold"),
                bg=theme.SURFACE if is_active else theme.BG_ALT,
                fg=theme.TEXT if is_active else theme.MUTED_LIGHT,
                padx=14,
                pady=6,
                relief="raised" if is_active else "flat",
                cursor="arrow" if is_active else "hand2",
            )
            lbl.pack(side="left")
            if not is_active:
                lbl.bind("<Button-1>", lambda _e, c=code: self._set_lang(c))
                lbl.bind("<Enter>", lambda _e, w=lbl: w.configure(bg="#DDE4E8", fg=theme.MUTED))
                lbl.bind("<Leave>", lambda _e, w=lbl: w.configure(bg=theme.BG_ALT, fg=theme.MUTED_LIGHT))

        Tooltip(toggle_wrap, t("home.lang_tip"))

    def _build_profile_button(self):
        SIZE = 46
        btn_frame = tk.Frame(self, bg=BG, width=SIZE, height=SIZE)
        btn_frame.place(x=24, rely=1.0, y=-24, anchor="sw")
        btn_frame.pack_propagate(False)

        canvas = tk.Canvas(
            btn_frame,
            width=SIZE,
            height=SIZE,
            bg=BG,
            highlightthickness=0,
        )
        canvas.pack()

        # Cercle de fond
        canvas.create_oval(2, 2, SIZE - 2, SIZE - 2, fill=theme.ACCENT_SOFT, outline=theme.BORDER, width=1)
        # Icône
        canvas.create_text(SIZE // 2, SIZE // 2, text="👤", font=(theme.FONT_UI, 16))

        canvas.configure(cursor="hand2")
        canvas.bind("<Button-1>", lambda _e: self._on_profile())
        canvas.bind("<Enter>", lambda _e: canvas.itemconfigure(1, fill=theme.ACCENT_SOFT_HOVER))
        canvas.bind("<Leave>", lambda _e: canvas.itemconfigure(1, fill=theme.ACCENT_SOFT))
        Tooltip(canvas, t("home.profile_tip"))

    def _set_lang(self, lang_code: str):
        if _i18n.current_lang() != lang_code:
            set_user_lang(DEFAULT_USER_ID, lang_code)
            _i18n.set_lang(lang_code)

    def _toggle_lang(self):
        new_lang = "en" if _i18n.current_lang() == "fr" else "fr"
        set_user_lang(DEFAULT_USER_ID, new_lang)
        _i18n.set_lang(new_lang)

    def _on_lang_change(self):
        for child in self.winfo_children():
            child.destroy()
        self._build()

    def _tile_click(self, feature_id: str):
        if feature_id == "import":
            path = filedialog.askopenfilename(
                title=t("home.import_dialog"),
                filetypes=[(t("home.pdf_files"), "*.pdf"), (t("home.all_files"), "*.*")],
            )
            if path:
                self._on_import_pdf(path)
        elif feature_id == "flashcards" and self._on_flashcards:
            self._on_flashcards()
        elif feature_id == "quiz" and self._on_quiz:
            self._on_quiz()
        elif feature_id == "lang_learn" and self._on_lang_learn:
            self._on_lang_learn()
