# services/assistant.py — Réponses de l'assistant (Gemma) à une question de lecture.
#
# Construit le contexte (texte de page, titre doc/chapitre) puis délègue au LLM.
# `answerer` est injectable -> testable sans Ollama. Le pont vers le transport
# (WebSocket) reste côté serveur : ce module ne connaît ni asyncio ni FastAPI.
from __future__ import annotations

import re
from typing import Callable

from config.settings import FORCE_QUESTION_TYPE
from db.answers import get_recurring_struggles
from db.chapters import get_chapters
from db.documents import get_document as _get_document
from db.flashcards import get_due_flashcards, get_related_flashcards
from db.metacog import ensure_profile
from db.questions import get_question
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
    "resolve_paragraph_mask",
    "evaluate_page_answer",
    "objective_verdict",
    "build_intervention_context",
    "make_flashcard",
]


# Zoom de l'image envoyée au LLM : net pour les formules/figures, tout en gardant
# de la marge sous le plafond d'image du client (page chargée en images sinon
# ignorée puis repli texte). Mesuré ~150 Ko sur un article, cap 500 Ko.
_ASSISTANT_IMAGE_ZOOM = 1.5

# En dessous, le passage masqué est trop court pour être retrouvé de façon fiable
# sur la page (et masquer trois mots n'exige aucun effort de rappel).
_MIN_MASK_CHARS = 40


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

    Un document servi en blocs (fichier de code) n'a rien à montrer au modèle
    que le texte ne dise déjà : on n'y joint pas d'image. Un rendu PyMuPDF de
    code coûte du temps et des tokens de vision pour zéro information."""
    if _served_as_text_blocks(doc_id, page):
        return []
    path = _safe(lambda: library.render_page(doc_id, page, _ASSISTANT_IMAGE_ZOOM), None)
    return [path] if path else []


def _served_as_text_blocks(doc_id: int, page: int) -> bool:
    """La page est-elle servie en blocs de texte plutôt qu'en image ?

    `library.page_blocks` renvoie None pour un document raster (PDF) et une
    liste de blocs `code` pour un fichier source."""
    blocks = _safe(lambda: library.page_blocks(doc_id, page), None)
    return bool(blocks)


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
        # Levier de mise au point : force un type pour vérifier son rendu de bout
        # en bout (vide en usage normal, cf. config/settings.FORCE_QUESTION_TYPE).
        "preferred_question_type": FORCE_QUESTION_TYPE,
        "past_struggles": _safe(lambda: get_recurring_struggles(doc_id=doc_id), []),
        "user_highlights": _safe(lambda: get_highlight_quotes(doc_id, page=page), []),
        "image_paths": _page_image_paths(doc_id, page),
    }
    generator(context, on_success, on_error)


def resolve_paragraph_mask(doc_id: int, page: int, mask: dict | None) -> dict | None:
    """Transforme le masque du LLM (indices de caractères) en citation affichable.

    Le LLM renvoie `paragraph_mask` en indices dans le texte de la page ; l'UI, elle,
    localise un passage par sa **citation** (même chemin que les surlignages :
    `library.search_page`). C'est ici qu'on convertit, pour que le routeur WS n'ait
    plus qu'à transporter. Renvoie None si le masque est absent ou intraduisible."""
    if not isinstance(mask, dict) or not mask.get("enabled"):
        return None
    text = library.page_text(doc_id, page) or ""
    try:
        start = int(mask.get("start_char", 0))
        end = int(mask.get("end_char", 0))
    except (TypeError, ValueError):
        return None
    quote = " ".join(text[max(0, start):end].split())
    if len(quote) < _MIN_MASK_CHARS:
        return None
    return {"quote": quote, "placeholder": (mask.get("placeholder") or "").strip()}


def evaluate_page_answer(
    doc_id: int,
    page: int,
    question: str,
    answer: str,
    on_success: Callable[[dict], None],
    on_error: Callable[[str], None],
    *,
    question_type: str = "",
    question_id: int | None = None,
    evaluator: Callable = evaluate_answer_async,
) -> None:
    """Corrige une réponse : verdict objectif quand il existe, LLM sinon.

    La question générée porte sa réponse canonique et ses propositions ; elles
    sont relues ici (`question_id`) pour deux raisons. D'abord le LLM corrige en
    les voyant, au lieu de redéduire la vérité du paragraphe. Ensuite, quand la
    correction ne demande aucun jugement — un QCM, une remise en ordre — le
    verdict est calculé ici et s'impose : le LLM ne garde que le commentaire,
    les signaux et les surlignages."""
    stored = _stored_question(question_id)
    expected_answer = str(stored.get("answer") or "").strip()
    choices = stored.get("choices") or []
    qtype = question_type or str(stored.get("question_type") or "")

    question_block: dict = {"question": question, "question_type": qtype}
    if expected_answer:
        question_block["expected_answer"] = expected_answer
    if choices:
        question_block["choices"] = choices

    verdict = objective_verdict(qtype, answer, expected_answer, choices)
    context = {
        # Le type conditionne la correction (ordre exact d'un « ordering »,
        # contrainte d'un « teach_back »…) ET la dimension de jauge appuyée dans
        # metacog_signals : sans lui, le prompt d'évaluation corrigeait à l'aveugle.
        "question": question_block,
        "user_answer": answer,
        "paragraph": library.page_text(doc_id, page),
        "metacog_profile": _safe(ensure_profile, {}),
        "past_struggles": _safe(lambda: get_recurring_struggles(doc_id=doc_id), []),
        "image_paths": _page_image_paths(doc_id, page),
        "objective_verdict": verdict,
    }

    def _settled(evaluation: dict) -> None:
        # Le verdict objectif est déjà annoncé au LLM (feedback cohérent) ; on le
        # réimpose ici car une hallucination ne doit pas pouvoir valider un
        # mauvais choix — ni invalider le bon.
        if verdict:
            evaluation["verdict"] = verdict
            if verdict != "incorrect":
                evaluation["hint"] = ""
            if verdict != "partial":
                evaluation["completion"] = ""
        on_success(evaluation)

    evaluator(context, _settled, on_error)


def _stored_question(question_id: int | None) -> dict:
    if question_id is None:
        return {}
    return _safe(lambda: get_question(int(question_id)), None) or {}


def objective_verdict(
    question_type: str, answer: str, expected_answer: str, choices: list[str]
) -> str:
    """Verdict certain, ou "" si le type ou les données ne le permettent pas.

    Renvoyer "" est le cas normal : la plupart des types demandent un jugement.
    On ne tranche que là où il n'y a rien à juger — et seulement si la réponse
    attendue est bien reliable aux propositions stockées."""
    if question_type == "qcm":
        expected = _resolve_expected_choice(expected_answer, choices)
        if not expected:
            return ""
        return "correct" if _same_text(answer, expected) else "incorrect"
    if question_type == "ordering":
        steps = [str(c).strip() for c in choices if str(c).strip()]
        if len(steps) < 2:
            return ""
        given = _parse_ordered_steps(answer, steps)
        if given is None:
            return ""
        if given == steps:
            return "correct"
        # Deux étapes voisines permuées : la séquence est comprise, l'ordre non.
        return "partial" if _is_adjacent_swap(given, steps) else "incorrect"
    return ""


def _resolve_expected_choice(expected_answer: str, choices: list[str]) -> str:
    """La bonne proposition, telle qu'elle figure dans `choices`.

    Le LLM désigne parfois la réponse par sa lettre ("B"), parfois en la recopiant
    avec sa puce ("B) 12 m/s"). Si rien ne se rattache aux propositions, on
    renonce au verdict objectif plutôt que de sanctionner à tort."""
    expected = (expected_answer or "").strip()
    if not expected or not choices:
        return ""
    for choice in choices:
        if _same_text(choice, expected):
            return str(choice)
    letter = expected.rstrip(").").strip()
    if len(letter) == 1 and letter.isalpha():
        index = ord(letter.upper()) - ord("A")
        if 0 <= index < len(choices):
            return str(choices[index])
    normalized = _normalize_text(expected)
    matches = [c for c in choices if _normalize_text(str(c)) and _normalize_text(str(c)) in normalized]
    return str(matches[0]) if len(matches) == 1 else ""


def _parse_ordered_steps(answer: str, steps: list[str]) -> list[str] | None:
    """Séquence répondue, ramenée aux étapes connues ("1. Poser…" -> "Poser…")."""
    lines = [re.sub(r"^\s*\d+\s*[.)\-]\s*", "", line).strip() for line in (answer or "").splitlines()]
    lines = [line for line in lines if line]
    if len(lines) != len(steps):
        return None
    resolved: list[str] = []
    for line in lines:
        match = next((s for s in steps if _same_text(s, line)), "")
        if not match:
            return None
        resolved.append(match)
    return resolved if len(set(resolved)) == len(steps) else None


def _is_adjacent_swap(given: list[str], expected: list[str]) -> bool:
    wrong = [i for i, value in enumerate(given) if value != expected[i]]
    if len(wrong) != 2 or wrong[1] - wrong[0] != 1:
        return False
    first, second = wrong
    return given[first] == expected[second] and given[second] == expected[first]


def _normalize_text(value: str) -> str:
    return " ".join((value or "").split()).strip(" .;:!?").casefold()


def _same_text(left: str, right: str) -> bool:
    return bool(_normalize_text(left)) and _normalize_text(left) == _normalize_text(right)


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
