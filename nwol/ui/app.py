# ui/app.py — Fenêtre principale MetaC-App (lecteur scroll libre + assistant)
#
# Flux de lecture : import PDF → sas de concentration → révision éclair de
# 5 flashcards → PDF complet en scroll libre avec bulle assistante. Plus de
# choix de chapitre : l'index de chapitres reste calculé et stocké comme
# métadonnée (estimation du chapitre courant pour le LLM).
from __future__ import annotations
import tkinter as tk
from tkinter import filedialog, messagebox
import logging
import threading
from pathlib import Path

from core.companion import AdaptiveCompanion
from db.schema import initialize_schema
from db.documents import (
    upsert_document,
    get_document_subject,
    update_document_subject,
)
from db.flashcards import get_session_start_cards
from db.metacog import ensure_profile
from db.chapters import get_chapters, save_chapters
from db.session_reflections import get_recent_reflection_questions, save_session_reflection
from db.user import (
    DEFAULT_USER_ID,
    ensure_default_user,
    record_login_and_get_streak,
    get_user_lang,
)
from db.quiz_questions import get_quiz_questions
import i18n as _i18n
from i18n import t
from llm.ollama_client import (
    analyze_meta_cognition_answers_async,
    cancel_pending_generations,
    detect_document_subject_async,
    generate_meta_cognition_questions_async,
    generate_session_summary_async,
    is_ollama_available,
)
from llm.pdf_assistant_queue import get_pdf_llm_queue
from metacog.reflection import fallback_meta_cognition_analysis, normalize_meta_cognition_questions
from metacog.session import SessionManager
from reader.state import ReaderState
from pdf_viewer.pdf_document import PdfDocument
from pdf_viewer.page_renderer import clear_page_cache
from pdf_viewer.chapter_index import build_chapter_index
from ui.home import HomeScreen
from ui.lang_selector import LangSelectorPage
from ui.lang_entry_sas import LangEntrySas
from ui.lang_session_page import LangSessionPage
from ui.lang_progress_page import LangProgressPage
from ui.quiz_page import QuizPage
from ui.flashcards_page import FlashcardReviewWidget, FlashcardsPage
from ui.metacog_page import MetacogPage
from ui.scroll_reader import ScrollReaderPage
from ui.session_entry_sas import SessionEntrySas
from ui.session_exit_sas import SessionExitSas
from ui import theme

logger = logging.getLogger("App")


class NWoLApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MetaC-App")
        self.geometry("1360x860")
        self.minsize(1060, 680)
        theme.configure_root(self)

        initialize_schema()
        ensure_default_user()
        self._streak = record_login_and_get_streak()
        _i18n.set_lang(get_user_lang(DEFAULT_USER_ID))

        self._doc: PdfDocument | None = None
        self._state = ReaderState()
        self._session_mgr: SessionManager | None = None
        self._companion: AdaptiveCompanion | None = None
        self._current_view: str | None = None
        self._generation: int = 0
        self._pending_lang_profile: dict | None = None
        self._pending_lang_curriculum: list | None = None

        self._build_ui()
        self.reader.state = self._state
        _i18n.on_lang_change(self._rebuild_secondary_screens)
        self._check_llm_status()
        self._show_home()

        logger.info("Application MetaC-App démarrée (lecteur scroll libre + assistant)")

    # ------------------------------------------------------------------
    # Construction de l'UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._build_menu()

        self._container = tk.Frame(self, bg=theme.BG)
        self._container.pack(fill="both", expand=True)

        self._home_screen = HomeScreen(
            self._container,
            on_import_pdf=self._on_pdf_imported,
            on_flashcards=self._show_flashcards,
            on_profile=self._show_metacog,
            on_quiz=self._show_quiz,
            on_lang_learn=self._show_lang_selector,
            streak=self._streak,
        )
        self._home_screen.place(relwidth=1, relheight=1)

        self._entry_sas = SessionEntrySas(
            self._container,
            on_ready=self._show_start_review,
            on_back=self._back_from_entry_sas,
        )
        self._entry_sas.place(relwidth=1, relheight=1)

        self._start_review_screen = tk.Frame(self._container, bg=theme.BG)
        self._start_review_screen.place(relwidth=1, relheight=1)
        self._start_review_widget = FlashcardReviewWidget(
            self._start_review_screen,
            on_done=self._on_start_review_done,
            title="Révision éclair",
            mode="browse",
        )
        self._start_review_widget.pack(fill="both", expand=True, padx=54, pady=44)

        self.reader = ScrollReaderPage(
            self._container,
            on_back=self._back_from_reader,
            on_end_session=self._on_session_end,
        )
        self.reader.place(relwidth=1, relheight=1)

        self._flashcards_page = FlashcardsPage(self._container, on_back=self._show_home)
        self._flashcards_page.place(relwidth=1, relheight=1)

        self._metacog_page = MetacogPage(self._container, on_back=self._show_home)
        self._metacog_page.place(relwidth=1, relheight=1)

        self._exit_sas = SessionExitSas(self._container, on_done=self._on_exit_sas_done)
        self._exit_sas.place(relwidth=1, relheight=1)

        self._quiz_page = QuizPage(
            self._container,
            on_back=self._show_home,
            get_questions=lambda uid, subj=None: get_quiz_questions(uid, subject=subj),
            on_answer=self._on_quiz_answer,
            on_flashcards=self._show_flashcards,
            on_profile=self._show_metacog,
        )
        self._quiz_page.place(relwidth=1, relheight=1)

        self._lang_selector = LangSelectorPage(
            self._container, on_start=self._on_lang_selected, on_back=self._show_home,
        )
        self._lang_selector.place(relwidth=1, relheight=1)

        self._lang_entry_sas = LangEntrySas(
            self._container, on_ready=self._on_lang_sas_ready, on_back=self._show_lang_selector,
        )
        self._lang_entry_sas.place(relwidth=1, relheight=1)

        self._lang_session_page = LangSessionPage(
            self._container, on_end=self._on_lang_session_end, on_back=self._show_lang_entry_sas,
        )
        self._lang_session_page.place(relwidth=1, relheight=1)

        self._lang_progress_page = LangProgressPage(
            self._container, on_back=self._show_home, on_start_session=self._start_lang_from_progress,
        )
        self._lang_progress_page.place(relwidth=1, relheight=1)

    def _build_menu(self) -> None:
        self._menubar = tk.Menu(self)
        self._filemenu = tk.Menu(self._menubar, tearoff=0)
        self._filemenu.add_command(label=t("menu.home"), command=self._show_home)
        self._filemenu.add_command(label=t("menu.open_pdf"), command=self._open_pdf_dialog, accelerator="Ctrl+O")
        self._filemenu.add_separator()
        self._filemenu.add_command(label=t("menu.quit"), command=self.on_close)
        self._menubar.add_cascade(label=t("menu.file"), menu=self._filemenu)
        self.bind("<Control-o>", lambda _e: self._open_pdf_dialog())
        self.configure(menu=self._menubar)

    def _rebuild_menu(self) -> None:
        self._filemenu.entryconfigure(0, label=t("menu.home"))
        self._filemenu.entryconfigure(1, label=t("menu.open_pdf"))
        self._filemenu.entryconfigure(3, label=t("menu.quit"))
        self._menubar.entryconfigure(0, label=t("menu.file"))

    def _rebuild_secondary_screens(self) -> None:
        self._rebuild_menu()
        for screen in (
            self._entry_sas,
            self.reader,
            self._flashcards_page,
            self._exit_sas,
            self._quiz_page,
            self._metacog_page,
            self._lang_selector,
            self._lang_entry_sas,
            self._lang_session_page,
            self._lang_progress_page,
        ):
            if hasattr(screen, "refresh_lang"):
                try:
                    screen.refresh_lang()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Navigation entre écrans
    # ------------------------------------------------------------------

    def _show_home(self) -> None:
        self._raise_view("home", self._home_screen)

    def _show_entry_sas(self) -> None:
        self._raise_view("entry_sas", self._entry_sas)

    def _show_start_review(self) -> None:
        cards = get_session_start_cards(n=5, doc_id=self._state.doc_id if self._state else None)
        if not cards:
            self._on_start_review_done()
            return
        self._start_review_widget.load(cards, title=t("app.flash_review"))
        self._raise_view("start_review", self._start_review_screen)

    def _show_reader(self) -> None:
        self._raise_view("reader", self.reader)

    def _show_flashcards(self) -> None:
        self._flashcards_page.load()
        self._raise_view("flashcards", self._flashcards_page)

    def _show_metacog(self) -> None:
        self._metacog_page.load()
        self._raise_view("metacog", self._metacog_page)

    def _show_quiz(self) -> None:
        self._quiz_page.load(user_id=1)
        self._raise_view("quiz", self._quiz_page)

    def _show_lang_selector(self) -> None:
        self._raise_view("lang_selector", self._lang_selector)

    def _show_lang_entry_sas(self) -> None:
        self._raise_view("lang_entry_sas", self._lang_entry_sas)

    def _show_exit_sas(self) -> None:
        self._raise_view("exit_sas", self._exit_sas)

    def _on_lang_selected(self, profile: dict, curriculum: list) -> None:
        self._pending_lang_profile = profile
        self._pending_lang_curriculum = curriculum
        self._lang_entry_sas.load(profile, curriculum)
        self._show_lang_entry_sas()

    def _on_lang_sas_ready(self, profile: dict, curriculum: list) -> None:
        self._pending_lang_profile = profile
        self._pending_lang_curriculum = curriculum
        self._lang_session_page.load(profile, curriculum)
        self._raise_view("lang_session", self._lang_session_page)

    def _on_lang_session_end(self, summary: dict) -> None:
        from db.lang_db import (save_lang_session, update_lang_profile,
                                get_lang_progress)
        profile_id = summary.get("profile_id")
        lesson_n = summary.get("lesson_n", 1)
        duration_s = summary.get("duration_s", 0)
        score = summary.get("score", 0.0)
        if profile_id:
            try:
                save_lang_session(profile_id, lesson_n, duration_s, score)
                if duration_s >= 900:
                    next_lesson = lesson_n + 1
                    phase = "active" if next_lesson >= 50 else "passive"
                    update_lang_profile(profile_id, current_lesson=next_lesson, phase=phase)
                    if self._pending_lang_profile:
                        self._pending_lang_profile = dict(
                            self._pending_lang_profile, current_lesson=next_lesson, phase=phase,
                        )
            except Exception:
                pass

        profile = self._pending_lang_profile
        curriculum = self._pending_lang_curriculum or []
        if profile and profile_id:
            try:
                progress = get_lang_progress(profile_id)
                self._lang_progress_page.load(profile, curriculum, progress)
                self._raise_view("lang_progress", self._lang_progress_page)
                return
            except Exception:
                pass
        self._show_home()

    def _start_lang_from_progress(self, profile: dict, curriculum: list) -> None:
        self._pending_lang_profile = profile
        self._pending_lang_curriculum = curriculum
        self._lang_entry_sas.load(profile, curriculum)
        self._show_lang_entry_sas()

    def _raise_view(self, view_name: str, widget: tk.Widget) -> None:
        previous = self._current_view
        self._current_view = view_name
        widget.tkraise()
        if previous == view_name or theme.PREFERS_REDUCED_MOTION:
            widget.place_configure(relx=0)
            return
        widget.place_configure(relx=0.018)

        def _update(progress: float) -> None:
            widget.place_configure(relx=0.018 * (1 - theme.ease_out_cubic(progress)))

        def _done() -> None:
            widget.place_configure(relx=0)

        theme.animate(self._container, theme.ANIM_FAST, _update, _done)

    def _back_from_reader(self) -> None:
        self._exit_reading_session("back")
        self._show_home()

    def _back_from_entry_sas(self) -> None:
        self._show_home()

    # ------------------------------------------------------------------
    # Import PDF → sas → révision → lecture libre
    # ------------------------------------------------------------------

    def _open_pdf_dialog(self) -> None:
        path = filedialog.askopenfilename(
            title=t("app.open_pdf_dialog"),
            filetypes=[(t("home.pdf_files"), "*.pdf"), (t("home.all_files"), "*.*")],
        )
        if path:
            self._on_pdf_imported(path)

    def open_pdf_path(self, path: str) -> None:
        self._on_pdf_imported(path)

    def _on_pdf_imported(self, path: str) -> None:
        """Ouvre le PDF puis enchaîne directement sur le sas de concentration."""
        try:
            self._generation += 1
            self._exit_reading_session("import")
            try:
                get_pdf_llm_queue().cancel_obsolete()
            except Exception as exc:
                logger.debug("Annulation queue PDF LLM ignorée à l'import: %s", exc)
            if self._doc is not None:
                try:
                    clear_page_cache(self._doc.path)
                finally:
                    self._doc.close()

            self._doc = PdfDocument(path).open()
            doc_path = self._doc.path
            filename = self._doc.filename
            page_count = self._doc.page_count()
            has_toc = bool(self._doc.toc())

            doc_id = upsert_document(doc_path, filename, page_count, "pymupdf_scroll", has_toc)
            self._state = ReaderState(doc_id=doc_id, total_pages=page_count, doc_title=filename)
            self.reader.state = self._state

            # L'index de chapitres n'est plus un écran : il reste calculé et
            # stocké comme métadonnée (estimation du chapitre courant).
            chapters = build_chapter_index(doc_path)
            save_chapters(doc_id, chapters)

            self.reader.set_document(
                filename, doc_path, page_count, doc_id, chapters=get_chapters(doc_id),
            )
            self._proceed_to_entry_sas()
            self._launch_llm_subject_detection(doc_id, doc_path, filename)

        except Exception as e:
            logger.error("Erreur ouverture PDF : %s", e)
            messagebox.showerror(t("app.error.open_pdf_title"), t("app.error.open_pdf_msg", error=e))

    def _excerpt_first_pages(self, n: int = 2) -> str:
        if not self._doc:
            return ""
        last = min(n, self._doc.page_count())
        parts = [self._doc.raw_text(p) for p in range(1, last + 1)]
        return "\n".join(parts)[:4000]

    def _proceed_to_entry_sas(self) -> None:
        self._entry_sas.load(
            self._doc.filename,
            doc_title=self._doc.filename,
            chapter_title="",
            profile=ensure_profile(),
            chapter_excerpt=self._excerpt_first_pages(2),
        )
        self._show_entry_sas()

    # ------------------------------------------------------------------
    # Détection de matière via LLM (import PDF)
    # ------------------------------------------------------------------

    def _launch_llm_subject_detection(self, doc_id: int, pdf_path: str, title: str) -> None:
        excerpt = self._excerpt_first_pages(2)

        def _on_success(result: dict) -> None:
            subject = result.get("subject")
            if subject:
                self.after(0, lambda s=subject: self._apply_llm_subject(doc_id, s))

        detect_document_subject_async(
            doc_title=Path(title).stem,
            excerpt=excerpt,
            on_success=_on_success,
            on_error=lambda _e: None,
        )

    def _apply_llm_subject(self, doc_id: int, subject: str) -> None:
        from db.subjects import ensure_subject
        update_document_subject(doc_id, subject)
        ensure_subject(DEFAULT_USER_ID, subject)
        logger.info("Matière LLM appliquée : doc=%s subject=%s", doc_id, subject)

        if self._session_mgr and self._state.doc_id == doc_id and self._session_mgr.subject != subject:
            self._session_mgr.set_subject(subject)

    # ------------------------------------------------------------------
    # Révision éclair → session de lecture libre
    # ------------------------------------------------------------------

    def _on_start_review_done(self) -> None:
        if not self._doc:
            self._show_home()
            return
        self._show_reader()
        self._study_document()

    def _study_document(self) -> None:
        """Session sur le document entier (scope virtuel ``whole_document``)."""
        if not self._doc or self._state is None or self._state.doc_id is None:
            return
        self._cancel_session()

        subject = get_document_subject(self._state.doc_id)
        self._session_mgr = SessionManager(self._state.doc_id, subject=subject)
        self._companion = AdaptiveCompanion(
            state=self._state,
            on_question=self.reader.on_question_ready,
            on_feedback=self.reader.on_answer_evaluated,
            on_rephrasing=self.reader.on_rephrasing_ready,
            on_mask=self.reader.on_paragraph_mask,
            on_loading=self.reader.on_llm_loading,
            on_error=self.reader.on_llm_error,
        )
        self._state.chapter_mode = True
        self.reader.state = self._state
        self.reader.set_learning_context(self._companion, self._session_mgr, self._doc.filename)
        self.reader.start_session()

    def _cancel_session(self) -> None:
        if self._state:
            self._state.chapter_mode = False
        try:
            get_pdf_llm_queue().cancel_obsolete()
        except Exception as exc:
            logger.debug("Annulation queue PDF LLM ignorée: %s", exc)

    # ------------------------------------------------------------------
    # LLM status
    # ------------------------------------------------------------------

    def _check_llm_status(self) -> None:
        def _check():
            available = is_ollama_available()
            self.after(0, lambda: self.reader.set_llm_available(available))
        threading.Thread(target=_check, daemon=True).start()

    # ------------------------------------------------------------------
    # Fin de session → sas de sortie (synthèse + questions de réflexion)
    # ------------------------------------------------------------------

    def _on_session_end(self) -> None:
        cancel_pending_generations()
        if self._session_mgr is None:
            self._show_home()
            return
        if self._session_mgr._ended_summary is None:
            summary = self._session_mgr.end_session(
                pages_read=self._state.pages_read_count() if self._state else 0,
                chapters_completed=[],
            )
        else:
            summary = self._session_mgr._ended_summary
        if self._state:
            self._state.chapter_mode = False
        self.reader.flush_session_memory()
        self.reader.clear()

        llm_expected = bool(summary and self.reader.llm_available is not False)
        self._exit_sas.start_loading(summary, llm_expected=llm_expected)
        self._show_exit_sas()

        if not llm_expected:
            self._exit_sas.set_analysis({})
            self._exit_sas.set_questions([], source="fallback")
            return

        context = {
            "session_data": summary,
            "metacog_profile": summary.get("profile") or {},
        }
        from db.answers import get_recent_session_answers
        try:
            recent_user_answers = [
                {
                    "answer": (answer.get("answer_text") or "")[:200],
                    "verdict": answer.get("verdict"),
                }
                for answer in get_recent_session_answers(summary.get("session_id"), limit=5)
            ]
        except Exception as exc:
            logger.debug("Réponses récentes non chargées pour le sas : %s", exc)
            recent_user_answers = []
        question_context = {
            "session_summary": summary,
            "recent_user_answers": recent_user_answers,
            "previous_end_questions": get_recent_reflection_questions(summary.get("user_id") or 1),
            "user_profile": summary.get("profile") or {},
        }

        def _success(result: dict) -> None:
            self.after(0, lambda r=result: self._exit_sas.set_analysis(r))

        def _error(message: str) -> None:
            logger.error("Synthèse de session échouée : %s", message)
            self.after(0, lambda: self._exit_sas.set_analysis({}))

        def _questions_success(result: dict) -> None:
            questions = normalize_meta_cognition_questions(
                result.get("questions") or [],
                previous_questions=question_context["previous_end_questions"],
                seed_context=summary.get("session_id"),
            )
            self.after(0, lambda q=questions: self._exit_sas.set_questions(q, source="llm"))

        def _questions_error(message: str) -> None:
            logger.error("Questions métacognitives échouées : %s", message)
            self.after(0, lambda: self._exit_sas.set_questions([], source="fallback"))

        generate_session_summary_async(context, _success, _error)
        generate_meta_cognition_questions_async(question_context, _questions_success, _questions_error)

    def _exit_reading_session(self, reason: str) -> None:
        if not (self._state and self._state.chapter_mode):
            logger.debug("_exit_reading_session(%s) ignoré: session inactive.", reason)
            return
        logger.info("Sortie de session de lecture: %s", reason)
        self._state.chapter_mode = False
        cancel_pending_generations()
        self.reader.flush_session_memory()
        self.reader.clear()
        if self._session_mgr is not None:
            if self._session_mgr._ended_summary is None:
                try:
                    self._session_mgr.end_session(
                        pages_read=self._state.pages_read_count(), chapters_completed=[],
                    )
                except Exception as exc:
                    logger.warning("Fin SessionManager échouée: %s", exc)
            # Session interrompue sans sas de sortie : consolider quand même le
            # profil permanent (idempotent si déjà finalisé).
            try:
                self._session_mgr.finalize_profile()
            except Exception as exc:
                logger.warning("Consolidation profil (session interrompue) échouée: %s", exc)
        self._session_mgr = None
        self._companion = None
        self.reader.session_mgr = None
        self.reader.companion = None

    def _on_exit_sas_done(self, payload: dict) -> None:
        summary = payload.get("summary") or {}
        session_id = summary.get("session_id")
        user_id = summary.get("user_id")
        responses = payload.get("responses") or []
        for response in responses:
            save_session_reflection(
                session_id=session_id,
                user_id=user_id,
                question_text=response.get("question", ""),
                answer_text=response.get("answer", ""),
                question_order=response.get("order", 0),
            )

        if self._session_mgr:
            questions = [response.get("question", "") for response in responses]
            answers = [response.get("answer", "") for response in responses]
            if self.reader.llm_available is not False:
                context = {
                    "questions": questions,
                    "answers": answers,
                    "session_context": summary,
                    "user_profile": summary.get("profile") or {},
                }

                def _success(analysis: dict) -> None:
                    self.after(0, lambda a=analysis: self._finalize_exit_sas(a, questions, answers, summary))

                def _error(message: str) -> None:
                    logger.error("Analyse méta-cognitive échouée : %s", message)
                    analysis = fallback_meta_cognition_analysis(questions, answers, summary, summary.get("profile") or {})
                    self.after(0, lambda a=analysis: self._finalize_exit_sas(a, questions, answers, summary))

                analyze_meta_cognition_answers_async(context, _success, _error)
                return

            analysis = fallback_meta_cognition_analysis(questions, answers, summary, summary.get("profile") or {})
            self._finalize_exit_sas(analysis, questions, answers, summary)
            return

        self._finalize_exit_sas(None, [], [], summary)

    def _finalize_exit_sas(self, meta_analysis, questions, answers, summary) -> None:
        if self._session_mgr:
            if meta_analysis:
                self._session_mgr.apply_meta_cognition_analysis(meta_analysis)
            self._session_mgr.finalize_profile()
        self._session_mgr = None
        self._companion = None
        self.reader.session_mgr = None
        self.reader.companion = None
        self._show_home()

    # ------------------------------------------------------------------
    # Quiz — mise à jour des jauges par matière (jauges invisibles mais actives)
    # ------------------------------------------------------------------

    def _on_quiz_answer(self, category: str, correct: bool, details: dict | None = None) -> None:
        from db.subjects import SUBJECT_LABELS, update_subject_from_answer
        from metacog.profile import update_retention_from_quiz

        details = details or {}
        verdict = details.get("verdict") or ("correct" if correct else "incorrect")
        session_id = self._session_mgr.session_id if self._session_mgr else None
        update_retention_from_quiz(DEFAULT_USER_ID, verdict, session_id=session_id)

        if self._session_mgr:
            # Tous les signaux LLM de l'évaluation quiz nourrissent les jauges de
            # session, pas seulement la rétention. La matière est mise à jour par
            # le flux quiz dédié ci-dessous (update_subject=False évite le doublon).
            self._session_mgr.update_from_evaluation(
                {
                    "verdict": verdict,
                    "metacog_signals": details.get("metacog_signals") or {},
                    "curiosity_signals": details.get("curiosity_signals") or {},
                    "creativity_signals": details.get("creativity_signals") or {},
                },
                update_subject=False,
            )

        if category in SUBJECT_LABELS:
            new_level = update_subject_from_answer(DEFAULT_USER_ID, category, correct, session_id=session_id)
            if self._session_mgr and self._session_mgr.subject == category:
                self._session_mgr.update_subject_level(new_level)

    # ------------------------------------------------------------------
    # Fermeture
    # ------------------------------------------------------------------

    def on_close(self) -> None:
        cancel_pending_generations()
        self.reader.clear()
        if self._doc:
            try:
                clear_page_cache(self._doc.path)
            finally:
                self._doc.close()
        from db import close_connection
        close_connection()
        logger.info("Application fermée.")
        self.destroy()
