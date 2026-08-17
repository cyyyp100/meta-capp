# services/assistant.py — Réponses de l'assistant (Gemma) à une question de lecture.
#
# Construit le contexte (texte de page, titre doc/chapitre) puis délègue au LLM.
# `answerer` est injectable -> testable sans Ollama. Le pont vers le transport
# (WebSocket) reste côté serveur : ce module ne connaît ni asyncio ni FastAPI.
from __future__ import annotations

from typing import Callable

from db.answers import get_recurring_struggles
from db.chapters import get_chapters
from db.documents import get_document as _get_document
from db.flashcards import get_due_flashcards, get_related_flashcards
from db.metacog import ensure_profile
from db.reader_highlights import get_highlight_quotes
from llm.ollama_client import (
    answer_user_question_async,
    evaluate_answer_async,
    generate_chapter_summary_async,
    generate_curiosity_hook_async,
    generate_question_async,
    generate_rephrasing_async,
    make_standalone_flashcard_async,
)
from services import library, pdf_rag

__all__ = [
    "build_answer_context",
    "answer_question",
    "chapter_title_for_page",
    "rephrase_page",
    "chapter_recap",
    "curiosity_hook",
    "generate_page_question",
    "evaluate_page_answer",
    "build_intervention_context",
    "make_flashcard",
]


# Zoom de l'image envoyée au LLM : net pour les formules/figures, tout en gardant
# de la marge sous le plafond d'image du client (page chargée en images sinon
# ignorée puis repli texte). Mesuré ~150 Ko sur un article, cap 500 Ko.
_ASSISTANT_IMAGE_ZOOM = 1.5


def _safe(fn, default):
    """Lecture best-effort : un incident de persistance ne doit jamais casser
    une réponse de l'assistant (le LLM dégrade gracieusement sur un profil vide)."""
    try:
        return fn()
    except Exception:
        return default


def _page_image_paths(doc_id: int, page: int) -> list[str]:
    """Image rendue de la page (zoom modéré) pour la vision LLM, best-effort.

    Le client LLM ignore silencieusement une image trop lourde et se replie sur
    le texte seul si Ollama refuse l'image : aucun risque pour la réponse.

    Document reconstruit (édition cloud) : le texte OCR complet est déjà dans
    le contexte — l'image (facturée au fournisseur) n'est jointe QUE si la
    page contient des visuels (figure/table) que le compagnon doit voir."""
    if _ocr_page_without_visuals(doc_id, page):
        return []
    path = _safe(lambda: library.render_page(doc_id, page, _ASSISTANT_IMAGE_ZOOM), None)
    return [path] if path else []


def _ocr_page_without_visuals(doc_id: int, page: int) -> bool:
    blocks = _safe(lambda: library.page_blocks(doc_id, page), None)
    if blocks is None:  # document raster ou page pas encore reconstruite
        return False
    return not any(b.get("type") in ("figure", "table") for b in blocks)


def chapter_title_for_page(doc_id: int, page: int) -> str:
    """Titre du chapitre couvrant `page` (dernier chapitre commençant avant)."""
    best = ""
    for chapter in get_chapters(doc_id):
        try:
            start = int(chapter.get("page_start") or 0)
        except (TypeError, ValueError):
            continue
        if start <= page:
            best = chapter.get("title") or best
    return best


def build_answer_context(
    doc_id: int,
    page: int,
    question: str,
    recent_exchanges: list[dict] | None = None,
    session_gauges: dict | None = None,
    selected_snippets: list[str] | None = None,
) -> dict:
    doc = _get_document(doc_id) or {}
    return {
        "user_question": question,
        "page_text": _safe(lambda: library.page_text(doc_id, page), ""),
        "doc_title": doc.get("filename") or "",
        "chapter_title": chapter_title_for_page(doc_id, page),
        "page_number": page,
        "metacog_profile": _safe(ensure_profile, {}),
        "session_gauges": session_gauges or {},
        "related_flashcards": _safe(lambda: get_related_flashcards(doc_id=doc_id), []),
        "recent_exchanges": list(recent_exchanges or []),
        "selected_snippets": list(selected_snippets or []),
        "user_highlights": _safe(lambda: get_highlight_quotes(doc_id, page=page), []),
        # RAG plein-document : passages pertinents trouvés AILLEURS que sur la page
        # visible (uniquement sur une question de l'étudiant, cf. answer_question).
        "retrieved_passages": _safe(
            lambda: pdf_rag.retrieve(doc_id, question, current_page=page), []
        ),
        "image_paths": _page_image_paths(doc_id, page),
    }


def answer_question(
    doc_id: int,
    page: int,
    question: str,
    on_success: Callable[[dict], None],
    on_error: Callable[[str], None],
    *,
    recent_exchanges: list[dict] | None = None,
    session_gauges: dict | None = None,
    selected_snippets: list[str] | None = None,
    answerer: Callable = answer_user_question_async,
) -> None:
    """Lance la réponse LLM (asynchrone, via callbacks). Non bloquant."""
    answerer(
        build_answer_context(
            doc_id, page, question, recent_exchanges, session_gauges, selected_snippets,
        ),
        on_success,
        on_error,
    )


# Toutes les actions ci-dessous normalisent la sortie en {answer, highlights}
# pour que le transport (WebSocket) reste uniforme.

def rephrase_page(
    doc_id: int,
    page: int,
    on_success: Callable[[dict], None],
    on_error: Callable[[str], None],
    *,
    generator: Callable = generate_rephrasing_async,
) -> None:
    page_text = library.page_text(doc_id, page)

    def _wrap(result: dict) -> None:
        text = (result.get("rephrased_paragraph") or "").strip()
        note = (result.get("note") or "").strip()
        full = text + (f"\n\n_{note}_" if note else "")
        on_success({"answer": full or "(pas de reformulation)", "highlights": result.get("highlights", [])})

    generator(
        {"paragraph": page_text, "attempt_count": 0, "image_paths": _page_image_paths(doc_id, page)},
        _wrap,
        on_error,
    )


def chapter_recap(
    doc_id: int,
    page: int,
    on_success: Callable[[dict], None],
    on_error: Callable[[str], None],
    *,
    generator: Callable = generate_chapter_summary_async,
) -> None:
    page_text = library.page_text(doc_id, page)
    context = {
        "chapter_title": chapter_title_for_page(doc_id, page),
        "paragraphs_summary": [page_text[:1500]] if page_text else [],
        "metacog_profile": _safe(ensure_profile, {}),
    }

    def _wrap(result: dict) -> None:
        summary = result.get("chapter_summary") or {}
        text = "\n\n".join(p for p in (summary.get("title", ""), summary.get("overview", "")) if p).strip()
        on_success({"answer": text or "(pas de résumé)", "highlights": []})

    generator(context, _wrap, on_error)


def curiosity_hook(
    doc_id: int,
    page: int,
    on_success: Callable[[dict], None],
    on_error: Callable[[str], None],
    *,
    generator: Callable = generate_curiosity_hook_async,
) -> None:
    doc = _get_document(doc_id) or {}
    page_text = library.page_text(doc_id, page)

    def _wrap(result: dict) -> None:
        on_success({"answer": (result.get("curiosity_hook") or "").strip() or "(pas de hook)", "highlights": []})

    generator(
        doc.get("filename") or "",
        chapter_title_for_page(doc_id, page),
        "",
        page_text[:1500],
        _safe(ensure_profile, {}),
        _wrap,
        on_error,
    )


# Boucle Q&R guidée : génère une question sur la page, puis évalue la réponse.
# Version autoportante (LLM direct), sans la persistance/session du companion.

def generate_page_question(
    doc_id: int,
    page: int,
    on_success: Callable[[dict], None],
    on_error: Callable[[str], None],
    *,
    session_gauges: dict | None = None,
    recent_question_types: list[str] | None = None,
    generator: Callable = generate_question_async,
) -> None:
    doc = _get_document(doc_id) or {}
    context = {
        "paragraph": library.page_text(doc_id, page),
        "doc_title": doc.get("filename") or "",
        "chapter_title": chapter_title_for_page(doc_id, page),
        "standalone": True,
        "metacog_profile": _safe(ensure_profile, {}),
        "session_gauges": session_gauges or {},
        # Anti-répétition + pilotage par jauges faibles (cf. _question_adaptation) :
        # avec recent_question_types fourni et preferred_question_type laissé vide,
        # le prompt choisit le type le plus utile et évite de répéter les récents.
        "recent_question_types": list(recent_question_types or []),
        "past_struggles": _safe(lambda: get_recurring_struggles(doc_id=doc_id), []),
        "user_highlights": _safe(lambda: get_highlight_quotes(doc_id, page=page), []),
        "image_paths": _page_image_paths(doc_id, page),
    }
    generator(context, on_success, on_error)


def evaluate_page_answer(
    doc_id: int,
    page: int,
    question: str,
    answer: str,
    on_success: Callable[[dict], None],
    on_error: Callable[[str], None],
    *,
    evaluator: Callable = evaluate_answer_async,
) -> None:
    context = {
        "question": {"question": question},
        "user_answer": answer,
        "paragraph": library.page_text(doc_id, page),
        "metacog_profile": _safe(ensure_profile, {}),
        "past_struggles": _safe(lambda: get_recurring_struggles(doc_id=doc_id), []),
        "image_paths": _page_image_paths(doc_id, page),
    }
    evaluator(context, on_success, on_error)


def build_intervention_context(
    doc_id: int,
    page: int,
    *,
    trigger: str,
    dwell_s: float,
    visits: int,
    questions_on_page: int,
    mode: str,
    gauges: dict | None = None,
    due_flashcard_front: str = "",
) -> dict:
    """Contexte d'une décision d'intervention autonome.

    `trigger` est **décidé par `services/intervention.py`** (seuils de
    `config/settings.py`) : cette fonction ne fait qu'habiller le signal reçu avec
    le texte de page et les surlignages. Ne pas y remettre de cascade de seuils —
    ce fut la cause d'une politique dupliquée entre les deux UI.
    Synchrone (lectures DB + texte de page) : à appeler hors de la boucle asyncio
    (executor)."""
    gauges = gauges or {}
    page_text = library.page_text(doc_id, page) or ""
    due_front = due_flashcard_front or ""
    if not due_front:
        due = _safe(lambda: get_due_flashcards(doc_id=doc_id, limit=1), [])
        due_front = (due[0].get("front") if due else "") or ""

    return {
        "trigger": trigger,
        "page": page,
        "page_text": page_text[:2500],
        "dwell_s": round(float(dwell_s), 1),
        "visits": int(visits),
        "user_questions_on_page": int(questions_on_page),
        "gauges": gauges,
        "mode": mode,
        "due_flashcard_front": due_front,
        "user_highlights": _safe(lambda: get_highlight_quotes(doc_id, page=page), []),
    }


def make_flashcard(
    doc_id: int,
    page: int,
    front: str,
    back: str,
    on_success: Callable[[dict], None],
    on_error: Callable[[str], None],
    *,
    generator: Callable = make_standalone_flashcard_async,
) -> None:
    """Réécrit un échange (recto/verso bruts) en flashcard autoportante via le LLM.

    Le paragraphe de la page sert de contexte pour remplacer toute référence au
    document (« selon ce texte ») par le concept précis. Non bloquant (callbacks).
    """
    context = {
        "front": front or "",
        "back": back or "",
        "paragraph": _safe(lambda: library.page_text(doc_id, page), "") or "",
    }
    generator(context, on_success, on_error)
