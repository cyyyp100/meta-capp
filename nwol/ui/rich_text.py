# ui/rich_text.py — Texte Tk avec rendu LaTeX inline
from __future__ import annotations

import logging
import tkinter as tk

from core.math_text import (
    MATH_SPAN_PATTERN,
    contains_renderable_math,
    repair_common_inline_math_artifacts,
)

logger = logging.getLogger("UI.rich_text")

MATH_PATTERN = MATH_SPAN_PATTERN


def rich_text_widget(
    parent,
    text: str,
    bg: str,
    fg: str,
    font,
    *,
    justify: str = "left",
    height: int | None = None,
    text_tag: str = "rich_text",
) -> tk.Text:
    widget = tk.Text(
        parent,
        wrap=tk.WORD,
        height=height or rich_text_height(text),
        bg=bg,
        fg=fg,
        font=font,
        padx=0,
        pady=0,
        relief=tk.FLAT,
        borderwidth=0,
        highlightthickness=0,
        cursor="arrow",
    )
    widget.tag_configure(text_tag, foreground=fg, font=font, justify=justify)
    render_rich_text(widget, text, text_tag=text_tag)
    widget.configure(state=tk.DISABLED)
    return widget


def render_rich_text(widget, text: str, insert_pos: str = "end", text_tag: str = "rich_text") -> None:
    text = repair_common_inline_math_artifacts(text or "")
    old_state = str(widget.cget("state"))
    if old_state == tk.DISABLED:
        widget.configure(state=tk.NORMAL)

    image_refs = getattr(widget, "_image_refs", None)
    if image_refs is None:
        image_refs = []
        widget._image_refs = image_refs
    window_refs = getattr(widget, "_window_refs", None)
    if window_refs is None:
        window_refs = []
        widget._window_refs = window_refs

    mark = f"_rich_insert_{id(widget)}"
    widget.mark_set(mark, insert_pos)
    widget.mark_gravity(mark, tk.RIGHT)

    inline_max_h = _inline_formula_height(widget, text_tag)
    last = 0
    for match in MATH_PATTERN.finditer(text):
        if match.start() > last:
            widget.insert(mark, text[last:match.start()], text_tag)

        latex = next((group for group in match.groups() if group is not None), "").strip()
        display = match.group(1) is not None or match.group(2) is not None
        max_height = None if display else inline_max_h
        if latex:
            insert_formula_image(
                widget,
                mark,
                latex,
                display,
                image_refs,
                window_refs,
                text_tag,
                max_height=max_height,
            )
        last = match.end()

    if last < len(text):
        widget.insert(mark, text[last:], text_tag)

    try:
        widget.mark_unset(mark)
    except tk.TclError:
        pass
    if old_state == tk.DISABLED:
        widget.configure(state=tk.DISABLED)


def insert_formula_image(
    widget,
    mark: str,
    latex: str,
    display: bool,
    image_refs: list,
    window_refs: list,
    text_tag: str,
    max_height: int | None = None,
) -> None:
    try:
        from core.latex import formula_to_tk_image

        img = formula_to_tk_image(latex, display=display, max_height=max_height)
        if not img:
            raise ValueError("image vide")
        image_refs.append(img)
        if display:
            widget.insert(mark, "\n", text_tag)
        label = tk.Label(widget, image=img, bg=widget.cget("bg"), borderwidth=0, padx=0, pady=0)
        window_refs.append(label)
        widget.window_create(mark, window=label, padx=3, pady=1 if not display else 4)
        if display:
            widget.insert(mark, "\n", text_tag)
    except Exception as exc:
        logger.debug("Rendu LaTeX échoué %r : %s", latex, exc)
        try:
            from core.latex import latex_to_plain_text

            fallback = latex_to_plain_text(latex)
        except Exception:
            fallback = (latex or "").replace("$", "").strip()
        if display:
            widget.insert(mark, "\n", text_tag)
        widget.insert(mark, fallback, text_tag)
        if display:
            widget.insert(mark, "\n", text_tag)


def rich_text_height(text: str) -> int:
    text = repair_common_inline_math_artifacts(text or "")
    formula_count = len(MATH_PATTERN.findall(text))
    estimated_wraps = sum(max(0, len(line) // 72) for line in text.splitlines() or [""])
    return max(1, min(36, text.count("\n") + estimated_wraps + formula_count * 2 + 1))


def contains_math(text: str | None) -> bool:
    return contains_renderable_math(text)


def _inline_formula_height(widget, text_tag: str) -> int:
    try:
        import tkinter.font as tkfont

        tag_font = widget.tag_cget(text_tag, "font")
        font_obj = tkfont.Font(font=tag_font or widget.cget("font"))
        return max(26, int(font_obj.metrics("linespace") * 1.55))
    except Exception:
        return 28
