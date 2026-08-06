# ui/flashcards_page.py — Page flash cards
from __future__ import annotations

import math
import tkinter as tk
from tkinter import messagebox

from i18n import t
from ui import theme
from ui.rich_text import rich_text_widget
from ui.top_nav import Tooltip
from llm.ollama_client import generate_flashcard_tags_async
from services.flashcards import (
    DEFAULT_USER_ID,
    create_flashcard,
    delete_flashcards,
    existing_tags,
    fallback_tags,
    list_flashcards,
    review_flashcard,
)

BG = theme.BG
TEXT = theme.TEXT
MUTED = theme.MUTED
ACCENT = theme.ACCENT


class FlashcardReviewWidget(tk.Frame):
    def __init__(self, master, on_done, title: str | None = None, mode: str = "review", **kwargs):
        super().__init__(master, bg=BG, **kwargs)
        self._on_done = on_done
        self._title = title or t("flash.review_title")
        self._mode = mode  # "review" or "browse"
        self._cards: list[dict] = []
        self._index = 0
        self._showing_back = False
        self._animating = False
        self._flip_progress = 1.0
        self._flip_swapped = False
        self._flip_side = "front"
        self._flip_target_side = "back"
        self._card_tilt = 0.0
        self._card_scale = 1.0
        self._canvas: tk.Canvas | None = None
        self._card_window_refs: list[tk.Widget] = []

    def load(self, cards: list[dict], title: str | None = None) -> None:
        self._cards = list(cards or [])
        self._index = 0
        self._showing_back = False
        self._flip_progress = 1.0
        self._flip_swapped = False
        self._flip_side = "front"
        self._flip_target_side = "back"
        self._card_tilt = 0.0
        self._card_scale = 1.0
        self._title = title or self._title
        if not self._cards:
            self._show_empty()
            return
        self._show_current()

    def _clear(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._card_window_refs.clear()

    def _show_empty(self) -> None:
        self._clear()
        wrapper = tk.Frame(self, bg=BG)
        wrapper.pack(expand=True)
        tk.Label(wrapper, text=t("flash.no_cards"), bg=BG, fg=MUTED, font=(theme.FONT_UI, 12)).pack(pady=16)
        btn = theme.make_button(wrapper, text=t("flash.continue"), command=self._on_done, kind="primary", padx=18, pady=8)
        btn.pack()
        Tooltip(btn, t("flash.continue"))

    def _show_current(self) -> None:
        self._clear()
        card = self._cards[self._index]
        wrapper = tk.Frame(self, bg=BG)
        wrapper.pack(expand=True, fill="both")

        tk.Label(wrapper, text=self._title, bg=BG, fg=TEXT, font=(theme.FONT_TITLE, 24, "bold")).pack(pady=(12, 6))
        tk.Label(wrapper, text=f"{self._index + 1}/{len(self._cards)}", bg=BG, fg=MUTED, font=(theme.FONT_UI, 11, "bold")).pack()

        self._canvas = tk.Canvas(wrapper, width=780, height=580, bg=BG, highlightthickness=0)
        self._canvas.pack(fill="x", padx=46, pady=16)
        self._canvas.bind("<Configure>", lambda _event: self._draw_card())
        self._flip_progress = 1.0
        self._card_scale = 1.0
        self._draw_card()

        if self._mode == "browse":
            self._canvas.configure(cursor="hand2")
            self._canvas.bind("<Button-1>", lambda _event: self._on_card_click())
            hint = t("flash.click_continue") if self._showing_back else t("flash.click_flip")
            tk.Label(wrapper, text=hint, bg=BG, fg=MUTED, font=(theme.FONT_UI, 10, "italic")).pack(pady=(0, 6))
        else:
            flip_btn = theme.make_button(wrapper, text=t("flash.flip_btn"), command=self._flip_card, kind="primary", padx=18, pady=8)
            flip_btn.pack(pady=(0, 10))
            Tooltip(flip_btn, t("flash.flip_tip"))

            verdicts = tk.Frame(wrapper, bg=BG)
            verdicts.pack()
            for verdict, label_key, tip_key, kind in (
                ("incorrect", "flash.incorrect", "flash.incorrect_tip", "danger"),
                ("partial",   "flash.partial",   "flash.partial_tip",   "warning"),
                ("correct",   "flash.correct",   "flash.correct_tip",   "soft"),
            ):
                label = t(label_key)
                tip   = t(tip_key)
                btn = theme.make_button(
                    verdicts,
                    text=label,
                    command=lambda v=verdict: self._review_answer(v),
                    padx=14,
                    pady=7,
                    kind=kind,
                )
                btn.pack(side="left", padx=5)
                Tooltip(btn, tip)

            meta = _card_meta(card)
            if meta:
                tk.Label(wrapper, text=meta, bg=BG, fg=MUTED, font=(theme.FONT_UI, 10)).pack(pady=(12, 0))

    def _draw_card(self) -> None:
        if self._canvas is None:
            return
        if not self._cards or self._index >= len(self._cards):
            return
        canvas = self._canvas
        for widget in self._card_window_refs:
            try:
                widget.destroy()
            except tk.TclError:
                pass
        self._card_window_refs.clear()
        canvas.delete("card")
        canvas.delete("progress")
        canvas_width = max(720, canvas.winfo_width())
        full_width = max(380, min(700, canvas_width - 54))
        progress = self._flip_progress if self._animating else 1.0
        angle = progress * 180
        visible = abs(math.cos(math.radians(angle)))
        width = full_width * max(0.08, visible) * self._card_scale
        height = 400 - (1 - visible) * 18
        shadow_dx = 5 + (1 - visible) * 18
        shadow_dy = 7 + (1 - visible) * 5
        shadow_outline = theme.BORDER_STRONG if visible < 0.35 else theme.BORDER
        x0 = (canvas_width - width) / 2
        y0 = 26
        x1 = x0 + width
        y1 = y0 + height
        fill = theme.SURFACE if not self._showing_back else theme.WARNING_SOFT
        outline = theme.BORDER if not self._showing_back else theme.WARNING

        for offset in (3, 6, 9):
            theme.create_round_rect(
                canvas,
                x0 + shadow_dx + offset,
                y0 + shadow_dy + offset / 2,
                x1 + shadow_dx + offset,
                y1 + shadow_dy + offset / 2,
                radius=theme.RADIUS_LG,
                fill=theme.BG_ALT if offset == 3 else theme.BORDER,
                outline="",
                tags="card",
            )
        theme.create_round_rect(
            canvas,
            x0 + shadow_dx,
            y0 + shadow_dy,
            x1 + shadow_dx,
            y1 + shadow_dy,
            radius=theme.RADIUS_LG,
            fill=theme.SURFACE_SOFT,
            outline=shadow_outline,
            tags="card",
        )
        theme.create_round_rect(canvas, x0, y0, x1, y1, radius=theme.RADIUS_LG, fill=fill, outline=outline, width=2, tags="card")

        if visible <= 0.18:
            canvas.create_line(canvas_width / 2, y0 + 24, canvas_width / 2, y1 - 24, fill=outline, width=4, tags="card")
            return

        if width > 60:
            card = self._cards[self._index]
            text = card["back"] if self._showing_back else card["front"]
            canvas.create_text(
                x0 + 28,
                y0 + 28,
                text=t("flash.back_label") if self._showing_back else t("flash.front_label"),
                fill=theme.MUTED,
                font=(theme.FONT_UI, 10, "bold"),
                anchor="w",
                tags="card",
            )
            text_widget = rich_text_widget(
                canvas,
                text,
                bg=fill,
                fg=TEXT,
                font=(theme.FONT_TITLE, 23, "bold"),
                justify="center",
                height=10,
            )
            text_widget.configure(cursor="hand2" if self._mode == "browse" else "arrow")
            text_widget.bind("<Button-1>", lambda _event: self._on_card_click() if self._mode == "browse" else None)
            self._card_window_refs.append(text_widget)
            canvas.create_window(
                canvas_width / 2,
                y0 + height / 2,
                window=text_widget,
                width=max(80, min(full_width - 60, width - 50)),
                tags="card",
            )
            progress = ((self._index + 1) / max(1, len(self._cards))) * 100
            px0 = x0 + 28
            px1 = x1 - 28
            py = y1 - 24
            canvas.create_line(px0, py, px1, py, fill=theme.BORDER, width=8, capstyle=tk.ROUND, tags="progress")
            canvas.create_line(
                px0,
                py,
                px0 + (px1 - px0) * progress / 100.0,
                py,
                fill=theme.ACCENT,
                width=8,
                capstyle=tk.ROUND,
                tags="progress",
            )

    def _on_card_click(self) -> None:
        if self._animating or not self._cards:
            return
        if not self._showing_back:
            self._flip_card()
        else:
            self._index += 1
            self._showing_back = False
            if self._index >= len(self._cards):
                self._on_done()
            else:
                self._show_current()

    def _flip_card(self) -> None:
        if self._animating or not self._cards:
            return
        self._animating = True
        self._flip_progress = 0.0
        self._flip_swapped = False
        self._flip_side = "back" if self._showing_back else "front"
        self._flip_target_side = "front" if self._showing_back else "back"
        self._card_scale = 1.0

        def _update(progress: float) -> None:
            eased = theme.ease_in_out_cubic(progress)
            self._flip_progress = eased
            self._card_tilt = math.sin(eased * math.pi)
            if eased >= 0.5 and not self._flip_swapped:
                self._showing_back = not self._showing_back
                self._flip_swapped = True
            if eased >= 0.92:
                settle = (eased - 0.92) / 0.08
                self._card_scale = 1.02 - 0.02 * theme.ease_out_cubic(settle)
            else:
                self._card_scale = 1.0
            self._draw_card()

        def _done() -> None:
            self._flip_progress = 1.0
            self._card_scale = 1.0
            self._card_tilt = 0.0
            self._draw_card()
            self._animating = False

        theme.animate(self, 280, _update, _done)

    def _review_answer(self, verdict: str) -> None:
        if self._animating:
            return
        card = self._cards[self._index]
        review_flashcard(card["id"], verdict)
        self._index += 1
        self._showing_back = False
        self._flip_progress = 1.0
        self._card_scale = 1.0
        if self._index >= len(self._cards):
            self._on_done()
        else:
            self._show_current()


class FlashcardsPage(tk.Frame):
    def __init__(self, master, on_back, user_id: int = DEFAULT_USER_ID, **kwargs):
        super().__init__(master, bg=BG, **kwargs)
        self._on_back = on_back
        self.user_id = user_id
        self._cards: list[dict] = []
        self._row_cards: list[dict | None] = []
        self._doc_options: dict[str, int | None] = {t("flash.filter.all_docs"): None}
        self._tag_var = tk.StringVar(value="")
        self._difficulty_var = tk.StringVar(value=t("flash.filter.all_difficulty"))
        self._document_var = tk.StringVar(value=t("flash.filter.all_docs"))
        self._build()

    def load(self) -> None:
        self._show_list()

    def _build(self) -> None:
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=56, pady=(34, 0))
        back_btn = theme.make_button(top, text=t("nav.back"), command=self._on_back, kind="ghost", font=(theme.FONT_UI, 11, "bold"))
        back_btn.pack(side="left")
        Tooltip(back_btn, t("flash.page_back_tip"))

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=64, pady=(32, 18))
        tk.Label(header, text=t("flash.page_title"), bg=BG, fg=TEXT, font=(theme.FONT_TITLE, 28, "bold")).pack(anchor="w")
        tk.Label(header, text=t("flash.page_subtitle"), bg=BG, fg=MUTED, font=(theme.FONT_UI, 11)).pack(anchor="w", pady=(6, 0))

        actions = tk.Frame(self, bg=BG)
        actions.pack(fill="x", padx=64, pady=(0, 16))
        review_btn = theme.make_button(actions, text=t("flash.review_all_btn"), command=self._start_review, kind="primary", padx=16, pady=8)
        review_btn.pack(side="left")
        Tooltip(review_btn, t("flash.review_all_tip"))
        create_btn = theme.make_button(actions, text=t("flash.create_btn"), command=self._show_create_form, kind="secondary", padx=16, pady=8)
        create_btn.pack(side="left", padx=8)
        Tooltip(create_btn, t("flash.create_tip"))
        delete_btn = theme.make_button(actions, text=t("flash.delete_btn"), command=self._delete_selected, kind="danger", padx=16, pady=8)
        delete_btn.pack(side="left")
        Tooltip(delete_btn, t("flash.delete_tip"))

        self._body = tk.Frame(self, bg=BG)
        self._body.pack(fill="both", expand=True, padx=64, pady=(0, 40))

    def _clear_body(self) -> None:
        for child in self._body.winfo_children():
            child.destroy()

    def _show_list(self) -> None:
        self._clear_body()
        self._refresh_doc_options()
        filters = self._selected_filters()
        self._cards = list_flashcards(self.user_id, **filters)

        self._build_filters()
        list_frame = tk.Frame(self._body, bg=BG)
        list_frame.pack(fill="both", expand=True, pady=(12, 0))

        self._listbox = theme.style_listbox(tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED,
            font=(theme.FONT_UI, 11),
            activestyle="none",
        ))
        self._listbox.pack(side="left", fill="both", expand=True)
        scrollbar = tk.Scrollbar(list_frame, command=self._listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self._listbox.configure(yscrollcommand=scrollbar.set)
        self._row_cards = []

        if not self._cards:
            self._listbox.insert(tk.END, t("flash.no_filter"))
            self._row_cards.append(None)
            return

        current_group = None
        for card in self._cards:
            group = _card_group(card)
            if group != current_group:
                self._listbox.insert(tk.END, f"  {group}")
                self._listbox.itemconfig(tk.END, foreground=ACCENT, background=theme.ACCENT_SOFT)
                self._row_cards.append(None)
                current_group = group
            tags = ", ".join(card.get("tags") or [])
            difficulty = card.get("difficulty", 2)
            suffix = f"  ·  tags: {tags}" if tags else ""
            self._listbox.insert(tk.END, f"    {card['front']}  →  {card['back']}  ·  {t('flash.difficulty_suffix')} {difficulty}{suffix}")
            self._row_cards.append(card)

    def _build_filters(self) -> None:
        filters = tk.Frame(self._body, bg=BG)
        filters.pack(fill="x")

        tk.Label(filters, text=t("flash.filter.tag"), bg=BG, fg=MUTED, font=(theme.FONT_UI, 10, "bold")).pack(side="left")
        tag_entry = theme.style_entry(tk.Entry(filters, textvariable=self._tag_var, width=18, font=(theme.FONT_UI, 10)))
        tag_entry.pack(side="left", padx=(6, 16), ipady=5)
        tag_entry.bind("<Return>", lambda _event: self._show_list())

        tk.Label(filters, text=t("flash.filter.difficulty"), bg=BG, fg=MUTED, font=(theme.FONT_UI, 10, "bold")).pack(side="left")
        difficulty_menu = tk.OptionMenu(filters, self._difficulty_var, t("flash.filter.all_difficulty"), "1", "2", "3", command=lambda _value: self._show_list())
        _style_option_menu(difficulty_menu)
        difficulty_menu.pack(side="left", padx=(6, 16))

        tk.Label(filters, text=t("flash.filter.document"), bg=BG, fg=MUTED, font=(theme.FONT_UI, 10, "bold")).pack(side="left")
        document_menu = tk.OptionMenu(filters, self._document_var, *self._doc_options.keys(), command=lambda _value: self._show_list())
        _style_option_menu(document_menu)
        document_menu.pack(side="left", padx=(6, 16))

        apply_btn = theme.make_button(filters, text=t("flash.apply_btn"), command=self._show_list, kind="secondary", padx=12, pady=6)
        apply_btn.pack(side="left")
        Tooltip(apply_btn, t("flash.apply_tip"))
        reset_btn = theme.make_button(filters, text=t("flash.reset_btn"), command=self._reset_filters, kind="secondary", padx=12, pady=6)
        reset_btn.pack(side="left", padx=6)
        Tooltip(reset_btn, t("flash.reset_tip"))

    def _refresh_doc_options(self) -> None:
        cards = list_flashcards(self.user_id)
        all_docs_label = t("flash.filter.all_docs")
        options: dict[str, int | None] = {all_docs_label: None}
        for card in cards:
            doc_id = card.get("document_id")
            title = card.get("document_title") or t("flash.no_document")
            if doc_id is not None:
                options[title] = doc_id
        self._doc_options = options
        if self._document_var.get() not in self._doc_options:
            self._document_var.set(all_docs_label)

    def _selected_filters(self) -> dict:
        difficulty = self._difficulty_var.get()
        document = self._document_var.get()
        filters = {
            "document_id": self._doc_options.get(document),
            "tags": self._tag_var.get().strip() or None,
            "difficulty": int(difficulty) if difficulty in {"1", "2", "3"} else None,
        }
        return {key: value for key, value in filters.items() if value is not None}

    def _reset_filters(self) -> None:
        self._tag_var.set("")
        self._difficulty_var.set(t("flash.filter.all_difficulty"))
        self._document_var.set(t("flash.filter.all_docs"))
        self._show_list()

    def _show_create_form(self) -> None:
        self._clear_body()
        form = tk.Frame(self._body, bg=BG)
        form.pack(fill="x", anchor="n")
        front = _field(form, t("flash.form.front"))
        back = _field(form, t("flash.form.back"))

        def _save():
            front_text = front.get().strip()
            back_text = back.get().strip()
            if not front_text or not back_text:
                messagebox.showwarning(t("flash.incomplete_title"), t("flash.incomplete_msg"))
                return
            save_btn.configure(state=tk.DISABLED, text=t("flash.generating"))

            context = {
                "front": front_text,
                "back": back_text,
                "existing_tags": existing_tags(self.user_id),
                "existing_sections": [],
                "session_context": {},
            }

            def _persist(tags: list[str]) -> None:
                create_flashcard(
                    self.user_id,
                    front=front_text,
                    back=back_text,
                    tags=tags,
                    difficulty=2,
                    source="manual",
                )
                self._show_list()

            def _success(result: dict) -> None:
                self.after(0, lambda r=result: _persist(r.get("tags") or []))

            def _error(_message: str) -> None:
                tags = fallback_tags(front_text, back_text, existing_tags=context["existing_tags"])
                self.after(0, lambda: _persist(tags))

            generate_flashcard_tags_async(context, _success, _error)

        save_btn = theme.make_button(form, text=t("flash.save_btn"), command=_save, kind="primary", padx=16, pady=8)
        save_btn.pack(anchor="e", pady=(12, 0))
        Tooltip(save_btn, t("flash.save_tip"))

    def _delete_selected(self) -> None:
        if not hasattr(self, "_listbox"):
            return
        selected = list(self._listbox.curselection())
        cards = [self._row_cards[index] for index in selected if index < len(self._row_cards) and self._row_cards[index]]
        if not cards:
            return
        if not messagebox.askyesno(t("flash.delete_confirm_title"), t("flash.delete_confirm_msg")):
            return
        delete_flashcards([card["id"] for card in cards])
        self._show_list()

    def _start_review(self) -> None:
        cards = self._cards or list_flashcards(self.user_id)
        if not cards:
            messagebox.showinfo(t("flash.no_cards_title"), t("flash.no_cards_msg"))
            return
        self._clear_body()
        title = t("flash.review_session_title")
        widget = FlashcardReviewWidget(self._body, on_done=self._finish_review, title=title)
        widget.pack(fill="both", expand=True)
        widget.load(cards, title=title)

    def _finish_review(self) -> None:
        messagebox.showinfo(t("flash.review_done_title"), t("flash.review_done_msg"))
        self._show_list()

    def refresh_lang(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._doc_options = {t("flash.filter.all_docs"): None}
        self._difficulty_var.set(t("flash.filter.all_difficulty"))
        self._document_var.set(t("flash.filter.all_docs"))
        self._build()
        self._show_list()


def _field(parent, label: str) -> tk.Entry:
    tk.Label(parent, text=label, bg=BG, fg=TEXT, font=(theme.FONT_UI, 10, "bold")).pack(anchor="w", pady=(10, 3))
    entry = theme.style_entry(tk.Entry(parent, font=(theme.FONT_UI, 12)))
    entry.pack(fill="x", ipady=8)
    return entry


def _style_option_menu(menu: tk.OptionMenu) -> None:
    menu.configure(
        bg=theme.SURFACE,
        fg=TEXT,
        activebackground=theme.ACCENT_SOFT,
        activeforeground=TEXT,
        relief=tk.FLAT,
        highlightthickness=1,
        highlightbackground=theme.BORDER,
        font=(theme.FONT_UI, 10),
    )
    menu["menu"].configure(
        bg=theme.SURFACE,
        fg=TEXT,
        activebackground=theme.ACCENT_SOFT,
        activeforeground=TEXT,
        relief=tk.FLAT,
    )


def _card_group(card: dict) -> str:
    document = card.get("document_title") or t("flash.no_document")
    chapter = card.get("chapter_title")
    return f"{document} / {chapter}" if chapter else document


def _card_meta(card: dict) -> str:
    pieces = []
    if card.get("document_title"):
        pieces.append(card["document_title"])
    if card.get("chapter_title"):
        pieces.append(card["chapter_title"])
    if card.get("tags"):
        pieces.append(", ".join(card["tags"]))
    return " · ".join(pieces)
