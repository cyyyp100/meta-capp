# ui/scroll_reader.py — Lecteur PDF scroll libre + bulle assistante
#
# Le PDF complet est affiché en scroll libre avec rendu progressif des pages
# (placeholders → PNG haute résolution autour du viewport). Plus aucun verrou
# de progression : la page dominante du viewport pilote ReaderState.current_page
# et la mémoire de session. Le système pédagogique reste entier mais passe en
# arrière-plan : jauges calculées et enregistrées (plus affichées), questions
# pédagogiques posées par l'assistant (bulle Gemma) au lieu d'un gate par page.
from __future__ import annotations

import logging
import queue
import threading
import time
import tkinter as tk

from config.settings import (
    FOCUS_DEFAULT_MIN,
    READER_PHOTO_CACHE_PAGES,
    READER_PRELOAD_PAGES,
    READER_RENDER_ZOOM,
    READER_SNAPSHOT_ZOOM,
)
from db.answers import get_recurring_struggles
from db.flashcards import get_due_flashcards, get_related_flashcards, save_flashcard, update_review
from db.page_dwell import save_page_dwell
from db.questions import save_assistant_exchange
from db.rephrasing import save_rephrasing
from db.user import (
    DEFAULT_USER_ID,
    get_assistant_prefs,
    save_assistant_mode,
    save_bubble_position,
)
from i18n import t
from llm.ollama_client import (
    answer_user_question_async,
    decide_intervention_async,
    generate_chapter_summary_async,
    generate_curiosity_hook_async,
    generate_rephrasing_async,
)
from pdf_viewer.page_renderer import render_page
from pdf_viewer.pdf_document import PdfDocument
from reader.context_snapshot import PageContextSnapshot, make_snapshot
from reader.highlights import find_quote_rects, rects_to_canvas
from reader.intervention import AssistantInterventionPolicy
from reader.session_memory import SessionMemory
from ui import theme
from ui.assistant_bubble import BUBBLE_SIZE, AssistantBubble, AssistantPanel, InterventionToast
from ui.inline_qa_block import QABlock
from ui.top_nav import TopNav

logger = logging.getLogger("UI.scroll_reader")

_PAGE_GAP = 18
_PAGE_MARGIN_X = 26
_MIN_WORDS_FOR_QA = 5
_POLICY_TICK_MS = 5000
_DEFAULT_BUBBLE_REL = (0.88, 0.78)
_PANEL_WIDTH = 352
_PANEL_HEIGHT = 396

# Surlignage LLM : couleur par intention de citation (stipple 50 % sur page blanche).
_HIGHLIGHT_COLORS = {
    "key": "#F2C12E",        # passage clé — jaune
    "explain": "#4D9DE0",    # passage expliqué — bleu
    "reference": "#5FBF77",  # passage cité en appui — vert
}


class ScrollReaderPage(tk.Frame):
    def __init__(self, parent, on_back, on_end_session, **kwargs):
        super().__init__(parent, bg=theme.BG, **kwargs)
        self._on_back = on_back
        self._on_end_session = on_end_session

        # Contexte d'apprentissage (injecté par l'app)
        self.state = None
        self.companion = None
        self.session_mgr = None
        self.llm_available: bool | None = None

        # Document
        self._doc: PdfDocument | None = None
        self._pdf_path = ""
        self._filename = ""
        self._doc_id: int | None = None
        self._page_count = 0
        self._chapters: list[dict] = []
        self._page_texts: dict[int, str] = {}

        # Mise en page / rendu progressif
        self._aspects: list[float] = []
        self._page_sizes_pts: list[tuple[float, float]] = []
        self._layout: list[tuple[float, float]] = []
        self._layout_width = 0
        self._photos: dict[int, object] = {}
        self._photo_width: dict[int, int] = {}
        self._render_pending: set[int] = set()
        self._render_generation = 0
        self._render_queue: queue.Queue = queue.Queue()
        self._render_worker: threading.Thread | None = None
        self._relayout_id: str | None = None
        self._viewport_id: str | None = None

        # Surlignages LLM (groupe → {page, items[{quote, purpose, rects points PDF}]})
        self._highlights: dict[str, dict] = {}
        self._hl_scroll_id: str | None = None

        # Assistant
        self._memory = SessionMemory()
        self._prefs = {"mode": "normal", "bubble_rel_x": None, "bubble_rel_y": None}
        self._exchanges: list[dict] = []
        self._last_exchange: dict | None = None
        # Mémoire longue chargée une fois au démarrage de session (pas de DB au tick).
        self._related_flashcards: list[dict] = []
        self._due_flashcard: dict | None = None
        # Mode focus : interventions coupées jusqu'à cet instant monotonic.
        self._focus_until: float | None = None
        self._toast: InterventionToast | None = None
        self._bubble_state_reset_id: str | None = None
        self._policy_tick_id: str | None = None
        self._policy: AssistantInterventionPolicy | None = None

        # Fin de chapitre (récap + anticipation), une célébration max par chapitre
        self._celebrated_chapters: set[int] = set()

        # Q&R pédagogique
        self._active_qa: QABlock | None = None
        self._follow_up_qa: QABlock | None = None
        self._qa_close_id: str | None = None

        # Session
        self._session_active = False
        self._timer_id: str | None = None

        self._build()

    # ------------------------------------------------------------------
    # Construction UI
    # ------------------------------------------------------------------
    def _build(self) -> None:
        self.top_nav = TopNav(
            self,
            on_back=self._on_back,
            on_play_pause=lambda: None,
            on_end_session=self._on_end_session,
        )
        self.top_nav.pack(fill="x")
        # Lecture libre : ni bouton play, ni libellé moteur.
        for widget in (self.top_nav.play_btn, self.top_nav.engine_lbl):
            try:
                widget.pack_forget()
            except Exception:
                pass

        body = tk.Frame(self, bg=theme.BG)
        body.pack(fill="both", expand=True)

        page_zone = theme.surface_frame(body, bg=theme.SURFACE_SOFT)
        page_zone.pack(fill="both", expand=True, padx=14, pady=(10, 12))
        self._overlay_host = page_zone

        self._canvas = tk.Canvas(page_zone, bg=theme.SURFACE_SOFT, highlightthickness=0)
        self._scrollbar = tk.Scrollbar(page_zone, orient="vertical", command=self._on_scrollbar)
        self._canvas.configure(yscrollcommand=self._on_yscroll)
        self._scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind("<Button-4>", lambda _e: self._scroll_units(-3))
        self._canvas.bind("<Button-5>", lambda _e: self._scroll_units(3))
        self._canvas.bind("<Button-1>", lambda _e: self._canvas.focus_set())
        self._canvas.bind("<Up>", lambda _e: self._scroll_units(-2))
        self._canvas.bind("<Down>", lambda _e: self._scroll_units(2))
        self._canvas.bind("<Prior>", lambda _e: self._scroll_pages(-1))
        self._canvas.bind("<Next>", lambda _e: self._scroll_pages(1))
        self._canvas.bind("<Home>", lambda _e: self._scroll_to(0.0))
        self._canvas.bind("<End>", lambda _e: self._scroll_to(1.0))

        # Bulle assistante + panneau (au-dessus du PDF)
        self._bubble = AssistantBubble(
            self._overlay_host,
            on_click=self._toggle_panel,
            on_moved=self._on_bubble_moved,
            bg=theme.SURFACE_SOFT,
        )
        self._panel = AssistantPanel(
            self._overlay_host,
            on_submit=self._on_user_question,
            on_close=self._hide_panel,
            on_mode_change=self._on_mode_change,
            on_create_flashcard=self._create_flashcard_from_answer,
            on_focus_mode=self._toggle_focus_mode,
        )
        self._panel_visible = False

        # Panneau Q&R pédagogique (questions autonomes du LLM)
        self._qa_panel = theme.surface_frame(self._overlay_host, bg=theme.SURFACE)
        qa_header = tk.Frame(self._qa_panel, bg=theme.SURFACE)
        qa_header.pack(fill="x")
        self._qa_title = tk.Label(
            qa_header, text=t("reader.qa_title"), bg=theme.SURFACE, fg=theme.MUTED,
            font=(theme.FONT_UI, 9, "bold"), anchor="w",
        )
        self._qa_title.pack(side="left", padx=10, pady=(6, 2))
        qa_close = tk.Label(
            qa_header, text=t("reader.qa_ignore"), bg=theme.SURFACE, fg=theme.MUTED,
            font=(theme.FONT_UI, 9), cursor="hand2", padx=10,
        )
        qa_close.pack(side="right", pady=(6, 2))
        qa_close.bind("<Button-1>", lambda _e: self._hide_qa_panel())
        self._qa_host = tk.Frame(self._qa_panel, bg=theme.SURFACE)
        self._qa_host.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._qa_visible = False

    # ------------------------------------------------------------------
    # API publique (appelée par l'app)
    # ------------------------------------------------------------------
    def set_llm_available(self, available: bool) -> None:
        self.llm_available = available
        self.top_nav.set_llm_status("available" if available else "unavailable")
        if available:
            if self._bubble.state == "unavailable":
                self._bubble.set_state("idle")
            self._panel.set_unavailable(False)
        else:
            self._bubble.set_state("unavailable")
            self._panel.set_unavailable(True)

    def set_document(
        self,
        filename: str,
        pdf_path: str,
        page_count: int,
        doc_id: int | None,
        chapters: list[dict] | None = None,
    ) -> None:
        self._close_doc()
        self._filename = filename
        self._pdf_path = str(pdf_path)
        self._page_count = int(page_count or 0)
        self._doc_id = doc_id
        self._chapters = sorted(chapters or [], key=lambda ch: int(ch.get("page_start") or 1))
        self._page_texts = {}
        self._doc = PdfDocument(self._pdf_path)
        try:
            self._doc.open()
            sizes = self._doc.page_sizes()
            self._aspects = [h / w if w else 1.414 for w, h in sizes]
            self._page_sizes_pts = sizes
        except Exception as exc:
            logger.error("Ouverture PDF impossible : %s", exc)
            self._doc = None
            self._aspects = [1.414] * self._page_count
            self._page_sizes_pts = []

    def set_learning_context(self, companion, session_mgr, filename: str) -> None:
        self.companion = companion
        self.session_mgr = session_mgr
        self._filename = filename or self._filename

    def start_session(self) -> None:
        """Démarre la lecture libre du document entier."""
        self._session_active = True
        self._render_generation += 1
        self._memory = SessionMemory()
        self._exchanges = []
        self._last_exchange = None
        self._prefs = get_assistant_prefs()
        self._panel.set_mode(self._prefs["mode"])
        self._load_long_term_memory()
        self._policy = AssistantInterventionPolicy(
            memory=self._memory,
            get_mode=lambda: self._prefs["mode"],
            get_gauges=self._current_gauges,
            get_current_page=lambda: self.state.current_page if self.state else 1,
            get_page_text=self._page_text,
            request_decision=self._request_intervention_decision,
            on_intervention=self._handle_intervention,
            get_due_flashcard=lambda: self._due_flashcard,
        )

        if self.state is not None:
            self.state.doc_title = self._filename
            self.state.chapter_title = ""
            self.state.total_pages = self._page_count
            self.state.mark_page_seen(1)
        self._memory.on_page_view(1)

        self._ensure_render_worker()
        self._highlights.clear()
        self._celebrated_chapters.clear()
        self._focus_until = None
        self._panel.set_focus_active(False)
        self._hide_qa_panel()
        self._hide_panel()
        self._dismiss_toast()
        self._relayout(force=True)
        self._scroll_to(0.0)
        self._place_bubble_initial()
        self._bubble.set_state("idle" if self.llm_available is not False else "unavailable")
        self.top_nav.set_context(self._filename, 1, self._page_count)
        self._start_timer()
        self._schedule_policy_tick()

    def flush_session_memory(self) -> None:
        """Persiste le dwell/visites par page (appelé par l'app avant la fin de session)."""
        if self.session_mgr is None:
            return
        try:
            self._memory.flush()
            save_page_dwell(
                self.session_mgr.session_id,
                self._memory.dwell_by_page,
                self._memory.visits_by_page,
            )
        except Exception as exc:
            logger.debug("Dwell de session non persisté : %s", exc)

    def clear(self) -> None:
        self._session_active = False
        self._render_generation += 1
        self._stop_timer()
        if self._policy_tick_id is not None:
            try:
                self.after_cancel(self._policy_tick_id)
            except Exception:
                pass
            self._policy_tick_id = None
        self._dismiss_toast()
        self._hide_qa_panel()
        self._hide_panel()
        self._highlights.clear()
        self._photos.clear()
        self._photo_width.clear()
        self._render_pending.clear()
        try:
            self._canvas.delete("all")
        except Exception:
            pass

    def refresh_lang(self) -> None:
        if hasattr(self.top_nav, "refresh_lang"):
            self.top_nav.refresh_lang()
        self._qa_title.configure(text=t("reader.qa_title"))
        self._panel.refresh_lang()
        self._panel.set_mode(self._prefs["mode"])

    # ------------------------------------------------------------------
    # Snapshot de contexte (capture au submit)
    # ------------------------------------------------------------------
    def make_snapshot(self) -> PageContextSnapshot:
        page = self.state.current_page if self.state else 1
        return make_snapshot(
            page_number=page,
            page_text=self._page_text(page),
            image_path=self._snapshot_image(page),
            doc_id=self._doc_id,
            doc_title=self._filename,
            chapter_title=self._estimate_chapter_title(page),
            gauges=self._current_gauges(),
            history=self.state.session_history if self.state else [],
        )

    def _snapshot_image(self, page: int) -> str | None:
        try:
            return render_page(self._pdf_path, page, zoom=READER_SNAPSHOT_ZOOM)
        except Exception:
            return None

    def _page_text(self, page: int) -> str:
        if page not in self._page_texts:
            self._page_texts[page] = self._doc.raw_text(page) if self._doc else ""
        return self._page_texts[page]

    def _estimate_chapter_title(self, page: int) -> str:
        title = ""
        for chapter in self._chapters:
            if int(chapter.get("page_start") or 1) <= page:
                title = str(chapter.get("title") or "")
            else:
                break
        return title

    def _estimate_chapter_id(self, page: int) -> int | None:
        chapter_id = None
        for chapter in self._chapters:
            if int(chapter.get("page_start") or 1) <= page:
                chapter_id = chapter.get("id")
            else:
                break
        return chapter_id

    def _current_gauges(self) -> dict:
        return self.session_mgr.current_gauges() if self.session_mgr else {}

    def _load_long_term_memory(self) -> None:
        """Charge une fois par session : difficultés passées, flashcards liées et dues."""
        try:
            struggles = get_recurring_struggles(DEFAULT_USER_ID, doc_id=self._doc_id)
            if not struggles:
                struggles = get_recurring_struggles(DEFAULT_USER_ID)
        except Exception as exc:
            logger.debug("Difficultés passées non chargées : %s", exc)
            struggles = []
        if self.companion is not None:
            self.companion.past_struggles = struggles
        try:
            self._related_flashcards = get_related_flashcards(DEFAULT_USER_ID, doc_id=self._doc_id)
        except Exception as exc:
            logger.debug("Flashcards liées non chargées : %s", exc)
            self._related_flashcards = []
        try:
            due = get_due_flashcards(DEFAULT_USER_ID, limit=1, doc_id=self._doc_id)
            if not due:
                due = get_due_flashcards(DEFAULT_USER_ID, limit=1)
            self._due_flashcard = due[0] if due else None
        except Exception as exc:
            logger.debug("Flashcards dues non chargées : %s", exc)
            self._due_flashcard = None

    # ------------------------------------------------------------------
    # Surlignage LLM (citations localisées dans la page rendue)
    # ------------------------------------------------------------------
    def _show_highlights(self, page: int, items: list[dict], group: str) -> None:
        """Surligne les citations LLM sur une page. Échec silencieux par citation."""
        self._clear_highlights(group)
        if not items or self._doc is None or not self._layout:
            return
        if page < 1 or page > len(self._layout):
            return
        resolved: list[dict] = []
        for item in items:
            quote = str((item or {}).get("quote") or "")
            try:
                rects = find_quote_rects(lambda s: self._doc.search_text(page, s), quote)
            except Exception as exc:
                logger.debug("Localisation citation impossible : %s", exc)
                rects = []
            if rects:
                resolved.append({
                    "quote": quote,
                    "purpose": str((item or {}).get("purpose") or "explain"),
                    "rects": rects,
                })
        if not resolved:
            return
        self._highlights[group] = {"page": page, "items": resolved}
        self._draw_highlight_group(group)
        self._scroll_to_first_highlight(group)

    def _draw_highlight_group(self, group: str) -> None:
        data = self._highlights.get(group)
        if not data or not self._layout:
            return
        page = int(data["page"])
        if page < 1 or page > len(self._layout):
            return
        scale = self._page_scale(page)
        if scale <= 0:
            return
        y_top = self._layout[page - 1][0]
        for item in data["items"]:
            color = _HIGHLIGHT_COLORS.get(item.get("purpose"), _HIGHLIGHT_COLORS["explain"])
            for x0, y0, x1, y1 in rects_to_canvas(item["rects"], scale, _PAGE_MARGIN_X, y_top):
                self._canvas.create_rectangle(
                    x0 - 1, y0 - 1, x1 + 1, y1 + 1,
                    fill=color, outline="", stipple="gray50",
                    tags=("hl", f"hl_{group}"),
                )
        self._canvas.tag_raise("hl")

    def _redraw_highlights(self) -> None:
        for group in list(self._highlights):
            self._draw_highlight_group(group)

    def _clear_highlights(self, group: str | None = None) -> None:
        if group is None:
            groups = list(self._highlights)
            self._highlights.clear()
        else:
            groups = [group] if self._highlights.pop(group, None) is not None else []
        for name in groups:
            try:
                self._canvas.delete(f"hl_{name}")
            except Exception:
                pass

    def _page_scale(self, page: int) -> float:
        """Facteur points PDF → pixels canvas (largeur affichée / largeur en points)."""
        if not self._page_sizes_pts or page - 1 >= len(self._page_sizes_pts):
            return 0.0
        width_pts = float(self._page_sizes_pts[page - 1][0] or 0.0)
        if width_pts <= 0:
            return 0.0
        page_w = max(220, self._layout_width - 2 * _PAGE_MARGIN_X)
        return page_w / width_pts

    def _scroll_to_first_highlight(self, group: str) -> None:
        data = self._highlights.get(group)
        if not data or not self._layout:
            return
        page = int(data["page"])
        scale = self._page_scale(page)
        rects = data["items"][0]["rects"]
        if not rects or scale <= 0:
            return
        y_target = self._layout[page - 1][0] + rects[0][1] * scale
        top = self._canvas.canvasy(0)
        height = max(1, self._canvas.winfo_height())
        if top + 30 <= y_target <= top + height - 90:
            return  # déjà confortablement visible
        try:
            total = float(self._canvas.cget("scrollregion").split()[3] or 1)
        except (IndexError, ValueError):
            return
        fraction = max(0.0, min(1.0, (y_target - height * 0.3) / total))
        self._animate_scroll_to(fraction)

    def _animate_scroll_to(self, target: float, steps: int = 10) -> None:
        if self._hl_scroll_id is not None:
            try:
                self.after_cancel(self._hl_scroll_id)
            except Exception:
                pass
            self._hl_scroll_id = None
        start = self._canvas.yview()[0]
        delta = target - start
        if abs(delta) < 0.0005:
            return

        def _step(i: int) -> None:
            self._hl_scroll_id = None
            progress = i / steps
            eased = 1 - (1 - progress) ** 3
            self._canvas.yview_moveto(max(0.0, min(1.0, start + delta * eased)))
            if i < steps:
                self._hl_scroll_id = self.after(16, lambda: _step(i + 1))
            else:
                self._schedule_viewport_update()

        _step(1)

    # ------------------------------------------------------------------
    # Mise en page + rendu progressif
    # ------------------------------------------------------------------
    def _on_canvas_configure(self, _event) -> None:
        if self._relayout_id is not None:
            try:
                self.after_cancel(self._relayout_id)
            except Exception:
                pass
        self._relayout_id = self.after(120, self._relayout)
        self._clamp_bubble()

    def _relayout(self, force: bool = False) -> None:
        self._relayout_id = None
        if not self._page_count:
            return
        width = self._canvas.winfo_width()
        if width <= 1:
            width = 920
        if not force and width == self._layout_width:
            return

        fraction = self._canvas.yview()[0] if self._layout else 0.0
        self._layout_width = width
        page_w = max(220, width - 2 * _PAGE_MARGIN_X)

        self._layout = []
        y = float(_PAGE_GAP)
        for index in range(self._page_count):
            aspect = self._aspects[index] if index < len(self._aspects) else 1.414
            height = page_w * aspect
            self._layout.append((y, y + height))
            y += height + _PAGE_GAP

        self._canvas.delete("all")
        self._photos.clear()
        self._photo_width.clear()
        self._render_pending.clear()
        self._render_generation += 1
        self._canvas.configure(scrollregion=(0, 0, width, y))
        self._draw_placeholders()
        self._redraw_highlights()
        self._canvas.yview_moveto(fraction)
        self._schedule_viewport_update()

    def _draw_placeholders(self) -> None:
        page_w = max(220, self._layout_width - 2 * _PAGE_MARGIN_X)
        for index, (y0, y1) in enumerate(self._layout):
            page = index + 1
            tag = f"ph{page}"
            self._canvas.create_rectangle(
                _PAGE_MARGIN_X, y0, _PAGE_MARGIN_X + page_w, y1,
                fill="#FFFFFF", outline=theme.BORDER, tags=(tag,),
            )
            self._canvas.create_text(
                _PAGE_MARGIN_X + page_w / 2, (y0 + y1) / 2,
                text=t("reader.page_loading", page=page),
                fill=theme.MUTED_LIGHT, font=(theme.FONT_UI, 12), tags=(tag,),
            )

    def _ensure_render_worker(self) -> None:
        if self._render_worker is not None and self._render_worker.is_alive():
            return
        self._render_worker = threading.Thread(
            target=self._render_loop, daemon=True, name="scroll-reader-render",
        )
        self._render_worker.start()

    def _render_loop(self) -> None:
        from PIL import Image

        while True:
            generation, page, target_width = self._render_queue.get()
            try:
                if generation != self._render_generation:
                    continue
                png_path = render_page(self._pdf_path, page, zoom=READER_RENDER_ZOOM)
                with Image.open(png_path) as opened:
                    ratio = target_width / max(1, opened.width)
                    new_h = max(1, int(opened.height * ratio))
                    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
                    resized = opened.resize((target_width, new_h), resample)
                if generation != self._render_generation:
                    continue
                self.after(0, lambda p=page, img=resized, g=generation: self._apply_render(p, img, g))
            except Exception as exc:
                logger.debug("Rendu page %s impossible : %s", page, exc)
                self._render_pending.discard(page)
            finally:
                self._render_queue.task_done()

    def _apply_render(self, page: int, pil_image, generation: int) -> None:
        self._render_pending.discard(page)
        if generation != self._render_generation or not self._layout:
            return
        from PIL import ImageTk

        try:
            photo = ImageTk.PhotoImage(pil_image)
        except Exception:
            return
        self._photos[page] = photo
        self._photo_width[page] = pil_image.width
        y0, _y1 = self._layout[page - 1]
        self._canvas.delete(f"img{page}")
        self._canvas.create_image(
            _PAGE_MARGIN_X, y0, anchor="nw", image=photo, tags=(f"img{page}",),
        )
        self._canvas.delete(f"ph{page}")
        if self._highlights:
            # L'image vient d'être recréée au-dessus : remonter les surlignages.
            self._canvas.tag_raise("hl")
        self._evict_far_photos()

    def _request_page_render(self, page: int) -> None:
        if page < 1 or page > self._page_count:
            return
        page_w = max(220, self._layout_width - 2 * _PAGE_MARGIN_X)
        if page in self._photos and self._photo_width.get(page) == page_w:
            return
        if page in self._render_pending:
            return
        self._render_pending.add(page)
        self._render_queue.put((self._render_generation, page, page_w))

    def _evict_far_photos(self) -> None:
        if not self.state:
            return
        center = self.state.current_page
        for page in list(self._photos):
            if abs(page - center) > READER_PHOTO_CACHE_PAGES:
                self._canvas.delete(f"img{page}")
                self._photos.pop(page, None)
                self._photo_width.pop(page, None)
                if self._layout and page - 1 < len(self._layout):
                    self._redraw_placeholder(page)

    def _redraw_placeholder(self, page: int) -> None:
        y0, y1 = self._layout[page - 1]
        page_w = max(220, self._layout_width - 2 * _PAGE_MARGIN_X)
        tag = f"ph{page}"
        self._canvas.delete(tag)
        self._canvas.create_rectangle(
            _PAGE_MARGIN_X, y0, _PAGE_MARGIN_X + page_w, y1,
            fill="#FFFFFF", outline=theme.BORDER, tags=(tag,),
        )
        self._canvas.create_text(
            _PAGE_MARGIN_X + page_w / 2, (y0 + y1) / 2,
            text=t("reader.page_loading", page=page),
            fill=theme.MUTED_LIGHT, font=(theme.FONT_UI, 12), tags=(tag,),
        )

    # ------------------------------------------------------------------
    # Scroll + page dominante
    # ------------------------------------------------------------------
    def _on_scrollbar(self, *args) -> None:
        self._canvas.yview(*args)
        self._schedule_viewport_update()

    def _on_yscroll(self, first: str, last: str) -> None:
        self._scrollbar.set(first, last)
        self._schedule_viewport_update()

    def _on_mousewheel(self, event) -> None:
        if not event.delta:
            return
        self._scroll_units(-2 if event.delta > 0 else 2)

    def _scroll_units(self, units: int) -> None:
        self._canvas.yview_scroll(units, "units")
        self._schedule_viewport_update()

    def _scroll_pages(self, direction: int) -> None:
        if not self.state or not self._layout:
            return
        target = max(1, min(self._page_count, self.state.current_page + direction))
        y0, _y1 = self._layout[target - 1]
        total = float(self._canvas.cget("scrollregion").split()[3] or 1)
        self._scroll_to(max(0.0, (y0 - _PAGE_GAP) / total))

    def _scroll_to(self, fraction: float) -> None:
        self._canvas.yview_moveto(max(0.0, min(1.0, fraction)))
        self._schedule_viewport_update()

    def _schedule_viewport_update(self) -> None:
        if self._viewport_id is not None:
            return
        self._viewport_id = self.after(80, self._update_viewport)

    def _update_viewport(self) -> None:
        self._viewport_id = None
        if not self._layout or not self._session_active:
            return
        top = self._canvas.canvasy(0)
        height = max(1, self._canvas.winfo_height())
        bottom = top + height

        dominant, dominant_overlap = None, 0.0
        first_visible, last_visible = None, None
        for index, (y0, y1) in enumerate(self._layout):
            if y1 < top:
                continue
            if y0 > bottom:
                break
            page = index + 1
            if first_visible is None:
                first_visible = page
            last_visible = page
            overlap = min(y1, bottom) - max(y0, top)
            if overlap > dominant_overlap:
                dominant, dominant_overlap = page, overlap

        if first_visible is None:
            return
        for page in range(
            max(1, first_visible - READER_PRELOAD_PAGES),
            min(self._page_count, last_visible + READER_PRELOAD_PAGES) + 1,
        ):
            self._request_page_render(page)

        if dominant is not None and self.state is not None and dominant != self.state.current_page:
            previous_page = self.state.current_page
            self.state.mark_page_seen(dominant)
            self.state.chapter_title = self._estimate_chapter_title(dominant)
            self._memory.on_page_view(dominant)
            self.top_nav.set_context(
                self.state.chapter_title or self._filename, dominant, self._page_count,
            )
            self._flash_reading_state()
            self._check_chapter_completion(previous_page, dominant)

    def _flash_reading_state(self) -> None:
        if self._bubble.state not in {"idle", "reading"}:
            return
        self._bubble.set_state("reading")
        if self._bubble_state_reset_id is not None:
            try:
                self.after_cancel(self._bubble_state_reset_id)
            except Exception:
                pass
        self._bubble_state_reset_id = self.after(2600, self._bubble_back_to_idle)

    def _bubble_back_to_idle(self) -> None:
        self._bubble_state_reset_id = None
        if self._bubble.state == "reading":
            self._bubble.set_state("idle")

    def _maybe_progress_glow(self, before: dict, after: dict, threshold: float = 6.0) -> None:
        """Lueur brève sur la bulle quand une jauge progresse fortement.

        Seul feedback visuel de progrès : les jauges restent invisibles.
        """
        try:
            strong_gain = any(
                float(after.get(key, 0.0)) - float(before.get(key, 0.0)) > threshold
                for key in before
            )
        except (TypeError, ValueError):
            return
        if strong_gain and self._bubble.state in {"idle", "reading", "answering"}:
            self._bubble.set_state("glow")
            self._schedule_bubble_idle(2800)

    # ------------------------------------------------------------------
    # Bulle : position + panneau
    # ------------------------------------------------------------------
    def _place_bubble_initial(self) -> None:
        self.update_idletasks()
        host_w = max(1, self._overlay_host.winfo_width())
        host_h = max(1, self._overlay_host.winfo_height())
        rel_x = self._prefs.get("bubble_rel_x")
        rel_y = self._prefs.get("bubble_rel_y")
        if rel_x is None or rel_y is None:
            rel_x, rel_y = _DEFAULT_BUBBLE_REL
        x = int(rel_x * max(1, host_w - BUBBLE_SIZE))
        y = int(rel_y * max(1, host_h - BUBBLE_SIZE))
        self._bubble.place(x=x, y=y)
        self._bubble.raise_widget()

    def _clamp_bubble(self) -> None:
        info = self._bubble.place_info()
        if not info:
            return
        try:
            x, y = int(float(info.get("x", 0))), int(float(info.get("y", 0)))
        except (TypeError, ValueError):
            return
        max_x = max(0, self._overlay_host.winfo_width() - BUBBLE_SIZE)
        max_y = max(0, self._overlay_host.winfo_height() - BUBBLE_SIZE)
        self._bubble.place_configure(x=max(0, min(max_x, x)), y=max(0, min(max_y, y)))

    def _on_bubble_moved(self, x: int, y: int) -> None:
        host_w = max(1, self._overlay_host.winfo_width() - BUBBLE_SIZE)
        host_h = max(1, self._overlay_host.winfo_height() - BUBBLE_SIZE)
        rel_x, rel_y = x / host_w, y / host_h
        self._prefs["bubble_rel_x"] = rel_x
        self._prefs["bubble_rel_y"] = rel_y
        try:
            save_bubble_position(DEFAULT_USER_ID, rel_x, rel_y)
        except Exception as exc:
            logger.debug("Position bulle non sauvegardée : %s", exc)
        if self._panel_visible:
            self._place_panel()

    def _toggle_panel(self) -> None:
        if self._panel_visible:
            self._hide_panel()
        else:
            self._show_panel()

    def _show_panel(self) -> None:
        self._dismiss_toast()
        self._place_panel()
        self._panel_visible = True
        self._panel.set_unavailable(self.llm_available is False)
        self._panel.lift()
        self._bubble.raise_widget()
        self._panel.focus_input()
        if self._bubble.state == "intervention":
            self._bubble.set_state("idle")

    def _place_panel(self) -> None:
        info = self._bubble.place_info()
        try:
            bx, by = int(float(info.get("x", 0))), int(float(info.get("y", 0)))
        except (TypeError, ValueError):
            bx, by = 0, 0
        host_w = max(1, self._overlay_host.winfo_width())
        host_h = max(1, self._overlay_host.winfo_height())
        # Le panneau s'ouvre du côté où il y a de la place, sans gêner la bulle.
        x = bx - _PANEL_WIDTH - 12 if bx > host_w / 2 else bx + BUBBLE_SIZE + 12
        x = max(8, min(host_w - _PANEL_WIDTH - 8, x))
        y = max(8, min(host_h - _PANEL_HEIGHT - 8, by - _PANEL_HEIGHT + BUBBLE_SIZE))
        self._panel.place(x=x, y=y, width=_PANEL_WIDTH, height=_PANEL_HEIGHT)

    def _hide_panel(self) -> None:
        self._panel_visible = False
        self._clear_highlights("assistant")
        self._clear_highlights("rephrase")
        try:
            self._panel.place_forget()
        except Exception:
            pass

    def _on_mode_change(self, mode: str) -> None:
        self._prefs["mode"] = mode
        try:
            save_assistant_mode(DEFAULT_USER_ID, mode)
        except Exception as exc:
            logger.debug("Mode assistant non sauvegardé : %s", exc)

    # ------------------------------------------------------------------
    # Question libre de l'utilisateur → answer_user_question
    # ------------------------------------------------------------------
    def _on_user_question(self, question_text: str) -> None:
        # Capture du contexte au moment EXACT du submit (l'utilisateur a pu
        # scroller depuis l'ouverture du panneau).
        snapshot = self.make_snapshot()
        self._panel.add_user_message(question_text)
        self._panel.set_busy(True)
        self._bubble.set_state("thinking")
        self._memory.on_user_question(snapshot.page_number, question_text)
        if self._policy:
            self._policy.set_busy(True)

        context = {
            "page_text": snapshot.page_text,
            "user_question": question_text,
            "doc_title": snapshot.doc_title,
            "chapter_title": snapshot.chapter_title,
            "page_number": snapshot.page_number,
            "metacog_profile": self.session_mgr.profile if self.session_mgr else {},
            "session_gauges": snapshot.gauges,
            "recent_exchanges": list(self._exchanges),
            "related_flashcards": list(self._related_flashcards),
            "image_paths": [p for p in [snapshot.image_path] if p],
        }

        def _success(result: dict) -> None:
            self.after(0, lambda r=result: self._show_assistant_answer(r, question_text, snapshot))

        def _error(message: str) -> None:
            self.after(0, lambda m=message: self._assistant_answer_failed(m))

        answer_user_question_async(context, _success, _error)

    def _show_assistant_answer(self, result: dict, question_text: str, snapshot: PageContextSnapshot) -> None:
        answer = (result.get("answer") or "").strip()
        page_note = ""
        if self.state and self.state.current_page != snapshot.page_number:
            # L'utilisateur a scrollé pendant la génération : indiquer la page utilisée.
            page_note = t("assistant.page_note", page=snapshot.page_number)
        self._panel.add_assistant_message(answer, page_note)
        self._show_highlights(snapshot.page_number, result.get("highlights") or [], "assistant")
        self._panel.set_busy(False)
        self._bubble.set_state("answering")
        self._schedule_bubble_idle()
        if self._policy:
            self._policy.set_busy(False)

        question_id = None
        if self._doc_id is not None:
            try:
                question_id = save_assistant_exchange(
                    doc_id=self._doc_id,
                    page=snapshot.page_number,
                    user_question=question_text,
                    llm_answer=answer,
                    session_id=self.session_mgr.session_id if self.session_mgr else None,
                    chapter_id=self._estimate_chapter_id(snapshot.page_number),
                )
            except Exception as exc:
                logger.warning("Sauvegarde échange assistant échouée : %s", exc)

        if self.session_mgr:
            # Les signaux de follow-up nourrissent les jauges (surtout curiosité,
            # attention, compréhension) — jauges invisibles mais bien actives.
            self.session_mgr.update_from_evaluation({
                "verdict": None,
                "metacog_signals": result.get("metacog_signals") or {},
                "curiosity_signals": result.get("curiosity_signals") or {},
                "follow_up_answer": answer,
            })

        exchange = {
            "question": question_text,
            "answer": answer,
            "page": snapshot.page_number,
            "question_id": question_id,
        }
        self._exchanges.append(exchange)
        self._exchanges = self._exchanges[-6:]
        self._last_exchange = exchange

    def _assistant_answer_failed(self, message: str) -> None:
        logger.error("Réponse assistant échouée : %s", message)
        self._panel.set_busy(False)
        self._panel.add_meta_message(t("assistant.answer_failed"))
        self._bubble.set_state("unavailable" if self.llm_available is False else "idle")
        if self._policy:
            self._policy.set_busy(False)

    def _schedule_bubble_idle(self, delay_ms: int = 3200) -> None:
        if self._bubble_state_reset_id is not None:
            try:
                self.after_cancel(self._bubble_state_reset_id)
            except Exception:
                pass

        def _reset() -> None:
            self._bubble_state_reset_id = None
            if self._bubble.state in {"answering", "intervention", "glow"}:
                self._bubble.set_state("idle")

        self._bubble_state_reset_id = self.after(delay_ms, _reset)

    # ------------------------------------------------------------------
    # Flashcard manuelle depuis la dernière réponse
    # ------------------------------------------------------------------
    def _create_flashcard_from_answer(self) -> None:
        exchange = self._last_exchange
        if not exchange or not exchange.get("answer"):
            return
        try:
            save_flashcard(
                user_id=DEFAULT_USER_ID,
                question_id=exchange.get("question_id"),
                front=exchange["question"][:400],
                back=exchange["answer"],
                tags=[],
                difficulty=2,
                source="manual",
                document_id=self._doc_id,
                chapter_id=self._estimate_chapter_id(int(exchange.get("page") or 1)),
                session_id=self.session_mgr.session_id if self.session_mgr else None,
            )
        except Exception as exc:
            logger.warning("Flashcard manuelle échouée : %s", exc)
            return
        self._panel.set_status(t("assistant.flashcard_saved"))
        self.after(4000, lambda: self._panel.set_status(""))

    # ------------------------------------------------------------------
    # Révision éclair d'une flashcard due (proposée par intervention)
    # ------------------------------------------------------------------
    def _start_flashcard_review(self, card: dict) -> None:
        if not card or not card.get("front"):
            return
        self._show_panel()

        def _on_verdict(verdict: str) -> None:
            try:
                update_review(int(card["id"]), verdict)
            except Exception as exc:
                logger.debug("Révision flashcard non sauvegardée : %s", exc)
            self._due_flashcard = None
            self._panel.set_status(t("assistant.review_done"))
            self.after(4000, lambda: self._panel.set_status(""))

        self._panel.show_flashcard_review(
            front=str(card.get("front") or ""),
            back=str(card.get("back") or ""),
            on_verdict=_on_verdict,
        )

    # ------------------------------------------------------------------
    # Interventions autonomes
    # ------------------------------------------------------------------
    def _schedule_policy_tick(self) -> None:
        if not self._session_active:
            return
        if self._policy_tick_id is not None:
            try:
                self.after_cancel(self._policy_tick_id)
            except Exception:
                pass
        self._policy_tick_id = self.after(_POLICY_TICK_MS, self._policy_tick)

    def _policy_tick(self) -> None:
        self._policy_tick_id = None
        if not self._session_active:
            return
        if self._focus_until is not None:
            if time.monotonic() >= self._focus_until:
                # Fin du focus : un seul rappel doux, puis retour au régime normal.
                self._focus_until = None
                self._panel.set_focus_active(False)
                self._show_toast(t("focus.ended"))
            else:
                self._schedule_policy_tick()
                return
        if self._policy is not None and self.llm_available is not False and not self._qa_visible:
            try:
                self._policy.tick()
            except Exception as exc:
                logger.debug("Tick intervention ignoré : %s", exc)
        self._schedule_policy_tick()

    def _toggle_focus_mode(self) -> None:
        if self._focus_until is not None:
            self._focus_until = None
            self._panel.set_focus_active(False)
            self._panel.set_status(t("focus.stopped"))
            self.after(4000, lambda: self._panel.set_status(""))
            return
        self._focus_until = time.monotonic() + FOCUS_DEFAULT_MIN * 60.0
        self._panel.set_focus_active(True)
        self._hide_panel()
        self._show_toast(t("focus.started", minutes=FOCUS_DEFAULT_MIN))

    def _request_intervention_decision(self, context: dict, on_done) -> None:
        def _success(result: dict) -> None:
            self.after(0, lambda r=result: on_done(r))

        def _error(_message: str) -> None:
            self.after(0, lambda: on_done(None))

        decide_intervention_async(context, _success, _error)

    def _handle_intervention(self, decision: dict) -> None:
        kind = decision["kind"]
        message = decision["message"]
        question = decision["question"]
        page = decision["page"]
        current = self.state.current_page if self.state else page
        page_changed = current != page

        if kind == "ask_question" and page_changed:
            # La question portait sur une page quittée : ne pas déranger.
            return
        if page_changed and message:
            message = f"{t('assistant.intervention_prev_page', page=page)} {message}"

        self._bubble.set_state("intervention")
        self._schedule_bubble_idle(9000)

        if kind == "ask_question":
            if message:
                self._show_toast(
                    message,
                    action_label=t("assistant.intervention_answer"),
                    on_action=lambda: self._launch_autonomous_question(page, question),
                )
            else:
                self._launch_autonomous_question(page, question)
        elif kind == "rephrase_offer":
            self._show_toast(
                message or t("assistant.rephrase_default"),
                action_label=t("assistant.rephrase_action"),
                on_action=lambda: self._rephrase_page(page),
            )
        elif kind == "review_flashcard":
            card = decision.get("flashcard") or {}
            front_preview = " ".join(str(card.get("front") or "").split())[:80]
            self._show_toast(
                message or t("assistant.review_toast", front=front_preview),
                action_label=t("assistant.review_action"),
                on_action=lambda c=card: self._start_flashcard_review(c),
            )
        elif kind == "suggest_pause":
            self._show_toast(message or t("assistant.pause_default"))
        else:  # offer_help
            self._show_toast(
                message or t("assistant.help_default"),
                action_label=t("assistant.help_action"),
                on_action=self._show_panel,
            )

        if not page_changed:
            # Le passage visé par l'intervention est montré tant que le toast vit.
            self._show_highlights(page, decision.get("highlights") or [], "intervention")

    def _show_toast(self, message: str, action_label: str = "", on_action=None) -> None:
        self._dismiss_toast()
        toast = InterventionToast(
            self._overlay_host,
            message=message,
            action_label=action_label,
            on_action=on_action,
            on_dismiss=self._on_toast_dismissed,
        )
        self._toast = toast
        info = self._bubble.place_info()
        try:
            bx, by = int(float(info.get("x", 0))), int(float(info.get("y", 0)))
        except (TypeError, ValueError):
            bx, by = 0, 0
        host_w = max(1, self._overlay_host.winfo_width())
        toast.update_idletasks()
        tw = max(220, toast.winfo_reqwidth())
        th = max(40, toast.winfo_reqheight())
        x = bx - tw - 10 if bx > host_w / 2 else bx + BUBBLE_SIZE + 10
        x = max(8, min(host_w - tw - 8, x))
        y = max(8, by - th + BUBBLE_SIZE)
        toast.place(x=x, y=y)
        toast.lift()
        self._bubble.raise_widget()

    def _on_toast_dismissed(self) -> None:
        self._toast = None
        self._clear_highlights("intervention")

    def _dismiss_toast(self) -> None:
        if self._toast is not None:
            toast, self._toast = self._toast, None
            try:
                toast.dismiss()
            except Exception:
                pass
        self._clear_highlights("intervention")

    # ------------------------------------------------------------------
    # Questions pédagogiques autonomes (pipeline companion complet)
    # ------------------------------------------------------------------
    def _launch_autonomous_question(self, page: int, question_text: str = "") -> None:
        if self.companion is None or self.state is None:
            return
        page_text = self._page_text(page)
        if len(page_text.split()) < _MIN_WORDS_FOR_QA and not question_text:
            return
        if self._policy:
            self._policy.set_busy(True)

        context = {
            "paragraph": page_text,
            "source_block_id": f"page:{page}",
            "page_start": page,
            "page_end": page,
            "doc_id": self._doc_id,
            "doc_title": self._filename,
            "chapter_title": self._estimate_chapter_title(page),
            "chapter_id": self._estimate_chapter_id(page),
            "image_paths": [p for p in [self._snapshot_image(page)] if p],
            "session_gauges": self._current_gauges(),
            "scope_type": "page",
        }
        prefetched = None
        if question_text:
            prefetched = {
                "question_type": "open",
                "question": question_text,
                "expected_answer": "",
                "source_block_id": f"page:{page}",
            }
        session_id = self.session_mgr.session_id if self.session_mgr else None
        # Différence majeure avec l'ancien lecteur : on_complete ne fait plus
        # avancer la page — la lecture reste libre.
        self.companion.start_paragraph_qa(
            context,
            session_id=session_id,
            on_complete=lambda: self.after(0, self._on_qa_complete),
            prefetched_question=prefetched,
        )

    def _on_qa_complete(self) -> None:
        if self._policy:
            self._policy.set_busy(False)
        if self._qa_close_id is not None:
            try:
                self.after_cancel(self._qa_close_id)
            except Exception:
                pass
        self._qa_close_id = self.after(15000, self._hide_qa_panel)

    def _show_qa_panel(self) -> None:
        self._qa_panel.place(relx=0.5, rely=1.0, anchor="s", y=-14, relwidth=0.56)
        self._qa_panel.lift()
        self._bubble.raise_widget()
        self._qa_visible = True

    def _hide_qa_panel(self) -> None:
        if self._qa_close_id is not None:
            try:
                self.after_cancel(self._qa_close_id)
            except Exception:
                pass
            self._qa_close_id = None
        self._qa_visible = False
        self._clear_highlights("qa")
        try:
            self._qa_panel.place_forget()
        except Exception:
            pass
        self._clear_qa_block()
        if self._policy:
            self._policy.set_busy(False)

    def _clear_qa_block(self) -> None:
        if self._active_qa is not None:
            try:
                self._active_qa.destroy()
            except Exception:
                pass
            self._active_qa = None
        self._follow_up_qa = None

    # --- callbacks companion (threads worker → marshaler vers Tk) -----------
    def on_question_ready(self, question: dict) -> None:
        self.after(0, lambda q=question: (
            self.top_nav.set_llm_status("available"),
            self._show_question(q),
        ))

    def on_answer_evaluated(self, result: dict) -> None:
        self.after(0, lambda r=result: (
            self.top_nav.set_llm_status("available"),
            self._show_evaluation(r),
        ))

    def on_rephrasing_ready(self, rephrasing: dict) -> None:
        self.after(0, lambda r=rephrasing: self._show_rephrasing(r))

    def on_paragraph_mask(self, start_char: int, end_char: int, placeholder: str) -> None:
        # Lecture sur image : pas de texte inline à masquer.
        return

    def on_llm_loading(self, label: str) -> None:
        self.after(0, lambda: self.top_nav.set_llm_status("generating"))
        if label == "question":
            self.after(0, lambda: self._bubble.set_state("thinking"))
        target = self._active_qa
        if label == "evaluation" and self._qa_is_alive(target):
            self.after(0, lambda b=target: b.show_loading() if self._qa_is_alive(b) else None)

    def on_llm_error(self, message: str) -> None:
        logger.error("Erreur LLM lecteur : %s", message)
        self.after(0, lambda: (
            self.top_nav.set_llm_status("unavailable"),
            self._hide_qa_panel(),
            self._bubble.set_state("idle"),
        ))

    def _show_question(self, question: dict) -> None:
        self._bubble.set_state("intervention")
        self._schedule_bubble_idle(6000)
        if self._active_qa is not None and self._qa_is_alive(self._active_qa):
            self._active_qa.remove_follow_up_form()
            self._active_qa.show_new_question(question)
            self._show_qa_panel()
            return
        self._clear_qa_block()

        def _submit(answer: str, response_time_ms: int) -> None:
            if self.companion:
                self.companion.handle_answer(answer, response_time_ms)

        def _rephrase() -> None:
            if self.companion:
                self.companion.request_new_question()

        qa = QABlock(self._qa_host, question, _submit, _rephrase, on_reveal_mask=None)
        qa.pack(fill="x")
        self._active_qa = qa
        self._show_qa_panel()

    def _show_evaluation(self, result: dict) -> None:
        follow_up_answer = result.get("follow_up_answer")
        self._show_highlights(self._companion_page(), result.get("highlights") or [], "qa")
        if follow_up_answer:
            target = self._follow_up_qa or self._active_qa
            if self._qa_is_alive(target):
                target.show_follow_up_answer(follow_up_answer)
            self._follow_up_qa = None
            # Persiste l'échange comme les questions libres de la bulle : sans
            # cela, les follow-ups Q&R n'existent que dans les jauges.
            follow_up_question = str(result.get("follow_up_question") or "").strip()
            if follow_up_question and self._doc_id is not None:
                page = self._companion_page()
                try:
                    save_assistant_exchange(
                        doc_id=self._doc_id,
                        page=page,
                        user_question=follow_up_question,
                        llm_answer=str(follow_up_answer),
                        session_id=self.session_mgr.session_id if self.session_mgr else None,
                        chapter_id=self._estimate_chapter_id(page),
                        scope_type="qa_follow_up",
                    )
                except Exception as exc:
                    logger.debug("Échange follow-up non persisté : %s", exc)
        elif self._qa_is_alive(self._active_qa):
            qa_block = self._active_qa
            para_snapshot = self.companion._paragraph_for_llm() if self.companion else ""
            qa_block.show_feedback(
                result.get("verdict", ""),
                result.get("feedback", ""),
                result.get("completion", ""),
                result.get("hint", ""),
                on_follow_up=lambda text, block=qa_block, para=para_snapshot: self._on_follow_up(text, block, para),
            )

        if self.session_mgr:
            # Pipeline intact : jauges mises à jour et enregistrées (non affichées).
            before = self.session_mgr.current_gauges()
            after = self.session_mgr.update_from_evaluation(
                result,
                response_time_ms=result.get("response_time_ms"),
                consecutive_incorrect=int(result.get("consecutive_incorrect") or 0),
            )
            self._maybe_progress_glow(before, after)
        if not follow_up_answer:
            self._memory.on_answer(self._companion_page(), result.get("verdict"))

    def _on_follow_up(self, question_text: str, qa_block=None, paragraph_text: str | None = None) -> None:
        self._follow_up_qa = qa_block or self._active_qa
        if self.companion:
            self.companion.handle_follow_up_question(question_text, paragraph_text)

    def _show_rephrasing(self, rephrasing: dict, page: int | None = None) -> None:
        text = (rephrasing or {}).get("rephrased_paragraph", "").strip()
        if not text:
            return
        self._show_panel()
        self._panel.add_assistant_message(f"💡 {text}")
        target_page = page if page is not None else self._companion_page()
        self._show_highlights(target_page, (rephrasing or {}).get("highlights") or [], "rephrase")

    # ------------------------------------------------------------------
    # Fin de chapitre : récap LLM + anticipation du chapitre suivant
    # ------------------------------------------------------------------
    def _chapter_index_for_page(self, page: int) -> int | None:
        index = None
        for i, chapter in enumerate(self._chapters):
            if int(chapter.get("page_start") or 1) <= page:
                index = i
            else:
                break
        return index

    def _check_chapter_completion(self, previous_page: int, dominant: int) -> None:
        if dominant <= previous_page or not self._chapters:
            return  # célébration seulement en avançant dans le document
        finished = self._chapter_index_for_page(previous_page)
        current = self._chapter_index_for_page(dominant)
        if finished is None or current is None or current <= finished:
            return
        if finished in self._celebrated_chapters:
            return
        self._celebrated_chapters.add(finished)
        title = str(self._chapters[finished].get("title") or "")
        self._show_toast(
            t("reader.chapter_done", title=title[:60]),
            action_label=t("reader.chapter_recap_action"),
            on_action=lambda i=finished: self._show_chapter_recap(i),
        )

    def _chapter_pages(self, index: int) -> tuple[int, int]:
        chapter = self._chapters[index]
        start = int(chapter.get("page_start") or 1)
        if chapter.get("page_end"):
            end = int(chapter["page_end"])
        elif index + 1 < len(self._chapters):
            end = max(start, int(self._chapters[index + 1].get("page_start") or start + 1) - 1)
        else:
            end = self._page_count or start
        return start, min(end, self._page_count or end)

    def _show_chapter_recap(self, index: int) -> None:
        if self.llm_available is False or index >= len(self._chapters):
            return
        chapter = self._chapters[index]
        title = str(chapter.get("title") or "")
        start, end = self._chapter_pages(index)
        # Éléments lus : extraits du début et de la fin du chapitre (budget serré).
        excerpts = []
        for page in dict.fromkeys([start, min(start + 1, end), end]):
            text = " ".join(self._page_text(page).split())[:600]
            if text:
                excerpts.append({"page": page, "excerpt": text})
        self._show_panel()
        self._panel.add_meta_message(t("reader.chapter_recap_loading", title=title[:60]))
        self._bubble.set_state("thinking")

        context = {
            "chapter_title": title,
            "paragraphs_summary": excerpts,
            "metacog_profile": self.session_mgr.profile if self.session_mgr else {},
        }

        def _success(result: dict) -> None:
            self.after(0, lambda r=result: self._show_chapter_recap_result(r, index))

        def _error(message: str) -> None:
            logger.debug("Récap chapitre échoué : %s", message)
            self.after(0, lambda: (
                self._panel.add_meta_message(t("assistant.answer_failed")),
                self._bubble.set_state("idle"),
            ))

        generate_chapter_summary_async(context, _success, _error)

    def _show_chapter_recap_result(self, result: dict, index: int) -> None:
        summary = (result or {}).get("chapter_summary") or {}
        overview = str(summary.get("overview") or "").strip()
        lines = [overview] if overview else []
        for item in summary.get("recap_qa") or []:
            question = str((item or {}).get("question") or "").strip()
            answer = str((item or {}).get("answer") or "").strip()
            if question and answer:
                lines.append(f"• {question}\n→ {answer}")
        if lines:
            self._panel.add_assistant_message("\n\n".join(lines))
        self._bubble.set_state("answering")
        self._schedule_bubble_idle()
        self._tease_next_chapter(index + 1)

    def _tease_next_chapter(self, next_index: int) -> None:
        """Accroche de curiosité sur le chapitre suivant — creux d'attention naturel."""
        if next_index >= len(self._chapters) or self.llm_available is False:
            return
        chapter = self._chapters[next_index]
        title = str(chapter.get("title") or "")
        excerpt = " ".join(self._page_text(int(chapter.get("page_start") or 1)).split())[:1200]

        def _success(result: dict) -> None:
            hook = str((result or {}).get("curiosity_hook") or "").strip()
            if hook:
                self.after(0, lambda h=hook: self._panel.add_assistant_message(
                    t("reader.next_chapter_tease", title=title[:60], hook=h)
                ))

        def _error(_message: str) -> None:
            pass

        generate_curiosity_hook_async(
            doc_title=self._filename,
            chapter_title=title,
            subchapter_title="",
            chapter_excerpt=excerpt,
            profile=self.session_mgr.profile if self.session_mgr else {},
            on_success=_success,
            on_error=_error,
        )

    # ------------------------------------------------------------------
    # Reformulation de page (proposition d'intervention)
    # ------------------------------------------------------------------
    def _rephrase_page(self, page: int) -> None:
        page_text = self._page_text(page)
        if not page_text.strip():
            return
        self._bubble.set_state("thinking")
        self._show_panel()
        self._panel.set_status(t("assistant.thinking"))

        context = {
            "paragraph": page_text,
            "image_paths": [p for p in [self._snapshot_image(page)] if p],
            "attempt_count": 0,
        }

        def _success(rephrasing: dict) -> None:
            def _apply() -> None:
                try:
                    save_rephrasing(
                        question_id=None,
                        session_id=self.session_mgr.session_id if self.session_mgr else None,
                        angle=rephrasing.get("rephrasing_angle"),
                        rephrased_text=rephrasing.get("rephrased_paragraph", ""),
                        note=rephrasing.get("note"),
                    )
                except Exception as exc:
                    logger.debug("Reformulation non sauvegardée : %s", exc)
                self._panel.set_status("")
                self._show_rephrasing(rephrasing, page=page)
                self._bubble.set_state("answering")
                self._schedule_bubble_idle()
            self.after(0, _apply)

        def _error(message: str) -> None:
            self.after(0, lambda: (
                self._panel.set_status(""),
                self._panel.add_meta_message(t("assistant.answer_failed")),
                self._bubble.set_state("idle"),
            ))

        generate_rephrasing_async(context, _success, _error)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _companion_page(self) -> int:
        paragraph = getattr(self.companion, "paragraph", None)
        page = getattr(paragraph, "page_start", None)
        if page:
            return int(page)
        return self.state.current_page if self.state else 1

    @staticmethod
    def _qa_is_alive(block) -> bool:
        if block is None:
            return False
        try:
            is_alive = getattr(block, "is_alive", None)
            return bool(is_alive()) if callable(is_alive) else bool(block.winfo_exists())
        except tk.TclError:
            return False

    def _start_timer(self) -> None:
        self._stop_timer()
        self._tick_timer()

    def _tick_timer(self) -> None:
        if self.session_mgr is not None:
            elapsed = int(time.monotonic() - self.session_mgr.started_monotonic)
            self.top_nav.set_elapsed(elapsed)
        self._timer_id = self.after(1000, self._tick_timer)

    def _stop_timer(self) -> None:
        if self._timer_id is not None:
            try:
                self.after_cancel(self._timer_id)
            except Exception:
                pass
            self._timer_id = None

    def _close_doc(self) -> None:
        if self._doc is not None:
            try:
                self._doc.close()
            finally:
                self._doc = None
