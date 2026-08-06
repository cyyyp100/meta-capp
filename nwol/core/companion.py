# core/companion.py — Orchestrateur de la boucle Q&R adaptative
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Callable

from config.settings import OLLAMA_MODEL
from core.math_text import normalize_unicode_math, safe_formula_context_text
from db.answers import save_answer
from db.flashcards import save_flashcard
from db.metacog import ensure_profile
from db.questions import save_question
from db.rephrasing import save_rephrasing
from db.user import DEFAULT_USER_ID
from i18n import current_lang, t
from llm.ollama_client import (
    answer_follow_up_async,
    evaluate_answer_async,
    generate_question_async,
    generate_rephrasing_async,
)
from metacog.reflection import augment_evaluation_with_response_signals
from reader.state import ReaderState

logger = logging.getLogger("Companion")


@dataclass
class ParagraphContext:
    text: str
    label: str = "Paragraphe"
    page_start: int | None = None
    page_end: int | None = None
    doc_id: int | None = None
    doc_title: str = ""
    chapter_title: str = ""
    chapter_id: int | None = None
    block: dict = field(default_factory=dict)
    blocks: list = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    session_gauges: dict = field(default_factory=dict)
    recent_question_types: list[str] = field(default_factory=list)
    source_block_id: str = ""
    scope_type: str = "paragraph"


class AdaptiveCompanion:
    """
    Pilote la boucle obligatoire :
    question -> réponse -> évaluation -> feedback -> passage ou remédiation.

    Les callbacks UI sont volontairement injectés : ce cœur reste testable et
    peut être branché au panneau Tkinter v1.3 sans dépendre de Tkinter.
    """

    def __init__(
        self,
        state: ReaderState | None = None,
        user_id: int = DEFAULT_USER_ID,
        llm_model: str = OLLAMA_MODEL,
        on_question: Callable[[dict], None] | None = None,
        on_feedback: Callable[[dict], None] | None = None,
        on_rephrasing: Callable[[dict], None] | None = None,
        on_mask: Callable[[int, int, str], None] | None = None,
        on_loading: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        question_generator=generate_question_async,
        answer_evaluator=evaluate_answer_async,
        rephrasing_generator=generate_rephrasing_async,
        follow_up_answerer=answer_follow_up_async,
    ):
        self.state = state
        self.user_id = user_id
        self.llm_model = llm_model
        self.on_question = on_question or (lambda _question: None)
        self.on_feedback = on_feedback or (lambda _feedback: None)
        self.on_rephrasing = on_rephrasing or (lambda _rephrasing: None)
        self.on_mask = on_mask or (lambda _start, _end, _placeholder: None)
        self.on_loading = on_loading or (lambda _label: None)
        self.on_error = on_error or (lambda message: logger.error(message))
        self.question_generator = question_generator
        self.answer_evaluator = answer_evaluator
        self.rephrasing_generator = rephrasing_generator
        self.follow_up_answerer = follow_up_answerer

        self.session_id: int | None = None
        self.paragraph: ParagraphContext | None = None
        self.current_question: dict | None = None
        self.current_question_id: int | None = None
        self._on_complete: Callable[[], None] | None = None
        # Difficultés récurrentes cross-session, injectées au démarrage de session
        # (aucune requête DB pendant la boucle Q&R).
        self.past_struggles: list[dict] = []

    def start_paragraph_qa(
        self,
        paragraph_scope,
        session_id: int | None,
        on_complete: Callable[[], None] | None = None,
        prefetched_question: dict | None = None,
    ) -> None:
        self.paragraph = _normalize_paragraph_context(paragraph_scope, self.state)
        self.session_id = session_id
        self._on_complete = on_complete
        self.current_question = None
        self.current_question_id = None

        if self.state:
            self.state.qa_active = True
            self.state.current_question = None
            self.state.attempt_count = 0
            self.state.consecutive_incorrect = 0

        logger.info(
            "Q&R paragraphe active source=%s label=%s extrait=%s",
            self.paragraph.source_block_id,
            self.paragraph.label,
            _source_context_excerpt(self.paragraph.text, max_chars=120),
        )

        if prefetched_question is not None:
            self._set_current_question(prefetched_question, expected_source_block_id=self.paragraph.source_block_id)
            return

        self._generate_question()

    def start_section_qa(
        self,
        section_context: dict,
        session_id: int | None,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Démarre la Q&R pour une section entière (titre/sous-titre)."""
        self.start_paragraph_qa(section_context, session_id, on_complete)

    def handle_answer(self, answer_text: str, response_time_ms: int | None = None) -> None:
        if not self.paragraph or not self.current_question:
            self.on_error("Aucune question active pour cette réponse.")
            return

        if self.state:
            self.state.attempt_count += 1

        attempt_number = self.state.attempt_count if self.state else 1
        profile = ensure_profile(self.user_id)
        history = self.state.session_history[-5:] if self.state else []
        context = {
            "question": self.current_question,
            "user_answer": answer_text,
            "paragraph": self._paragraph_for_llm(),
            "image_paths": self._image_paths_for_llm(),
            "metacog_profile": profile,
            "history": history,
            "past_struggles": self.past_struggles,
        }
        self.on_loading("evaluation")

        def _success(evaluation: dict) -> None:
            self._handle_evaluation(evaluation, answer_text, response_time_ms, attempt_number)

        self.answer_evaluator(context, _success, self.on_error)

    def request_new_question(self) -> None:
        """Régénère une nouvelle question pour le paragraphe actif."""
        if not self.paragraph:
            self.on_error("Aucun paragraphe actif pour générer une question.")
            return
        self._generate_question()

    def request_rephrasing(self) -> None:
        """Déclenche une reformulation manuelle sans invalider la question active."""
        if not self.paragraph:
            self.on_error("Aucun paragraphe actif à reformuler.")
            return

        attempt_count = self.state.attempt_count if self.state else 0
        context = {
            "paragraph": self._paragraph_for_llm(),
            "image_paths": self._image_paths_for_llm(),
            "attempt_count": attempt_count,
        }
        self.on_loading("rephrasing")

        def _success(rephrasing: dict) -> None:
            rephrasing_id = save_rephrasing(
                question_id=self.current_question_id,
                session_id=self.session_id,
                angle=rephrasing.get("rephrasing_angle"),
                rephrased_text=rephrasing.get("rephrased_paragraph", ""),
                note=rephrasing.get("note"),
            )
            self.on_rephrasing({**rephrasing, "id": rephrasing_id})

        self.rephrasing_generator(context, _success, self.on_error)

    def handle_follow_up_question(self, question_text: str, paragraph_text: str | None = None) -> None:
        if not self.paragraph:
            return

        question_text = (question_text or "").strip()
        if not question_text:
            return

        profile = ensure_profile(self.user_id)
        context = {
            "paragraph": paragraph_text if paragraph_text is not None else self._paragraph_for_llm(),
            "image_paths": self._image_paths_for_llm(),
            "user_question": question_text,
            "metacog_profile": profile,
        }
        self.on_loading("follow_up")

        def _success(result: dict) -> None:
            result = augment_evaluation_with_response_signals(result, question_text)
            self.on_feedback({
                **result,
                "follow_up_answer": result.get("answer"),
                "follow_up_question": question_text,
                "verdict": "correct",
            })

        self.follow_up_answerer(context, _success, self.on_error)

    def _generate_question(self) -> None:
        if not self.paragraph:
            return

        profile = ensure_profile(self.user_id)
        history = self.state.session_history[-5:] if self.state else []
        paragraph_text = self._paragraph_for_llm()
        source_block_id = self.paragraph.source_block_id
        context = {
            "paragraph": paragraph_text,
            "image_paths": self._image_paths_for_llm(),
            "chapter_title": self.paragraph.chapter_title,
            "doc_title": self.paragraph.doc_title,
            "metacog_profile": profile,
            "session_gauges": self.paragraph.session_gauges,
            "recent_question_types": (
                self.paragraph.recent_question_types
                or _recent_question_types_from_history(history)
            ),
            "history": history,
            "source_block_id": source_block_id,
            "has_existing_question": "?" in paragraph_text,
            "past_struggles": self.past_struggles,
        }
        self.on_loading("question")

        def _success(question: dict) -> None:
            self._set_current_question(question, expected_source_block_id=source_block_id)

        self.question_generator(context, _success, self.on_error)

    def _set_current_question(self, question: dict, expected_source_block_id: str | None = None) -> None:
        if not self.paragraph:
            return
        expected_source_block_id = expected_source_block_id or self.paragraph.source_block_id
        if self.paragraph.source_block_id != expected_source_block_id:
            logger.info(
                "Question LLM ignorée: source obsolète=%s source active=%s",
                expected_source_block_id,
                self.paragraph.source_block_id,
            )
            return

        question = dict(question)
        question["llm_model"] = self.llm_model
        returned_source_block_id = str(question.get("source_block_id") or "").strip()
        if returned_source_block_id and returned_source_block_id != expected_source_block_id:
            logger.warning(
                "Source de question LLM corrigée: source réponse=%s source attendue=%s",
                returned_source_block_id,
                expected_source_block_id,
            )
        question["source_block_id"] = expected_source_block_id
        question.setdefault("source_context", _source_context_excerpt(self.paragraph.text))
        if not question.get("session_hint"):
            hint = _adaptive_session_hint(self.paragraph.session_gauges)
            if hint:
                question["session_hint"] = hint
        self.current_question = question
        self.current_question_id = self._persist_question(question)
        self._apply_paragraph_mask(question.get("paragraph_mask"))

        if self.state:
            self.state.current_question = {
                **question,
                "id": self.current_question_id,
            }

        self.on_question({
            **question,
            "id": self.current_question_id,
        })
        logger.info(
            "Question prête id=%s source=%s label=%s",
            self.current_question_id,
            expected_source_block_id,
            self.paragraph.label,
        )

    def _apply_paragraph_mask(self, paragraph_mask: dict | None) -> None:
        if not isinstance(paragraph_mask, dict) or paragraph_mask.get("enabled") is not True:
            return
        try:
            start_char = int(paragraph_mask.get("start_char"))
            end_char = int(paragraph_mask.get("end_char"))
        except (TypeError, ValueError):
            return
        if end_char <= start_char:
            return
        placeholder = paragraph_mask.get("placeholder") or t("qa.mask_placeholder")
        self.on_mask(start_char, end_char, str(placeholder))

    def _handle_evaluation(
        self,
        evaluation: dict,
        answer_text: str,
        response_time_ms: int | None,
        attempt_number: int,
    ) -> None:
        if not self.paragraph:
            return

        evaluation = augment_evaluation_with_response_signals(evaluation, answer_text)

        answer_id = save_answer(
            question_id=self.current_question_id,
            user_id=self.user_id,
            answer_text=answer_text,
            verdict=evaluation.get("verdict"),
            feedback=evaluation.get("feedback"),
            completion=evaluation.get("completion"),
            hint=evaluation.get("hint"),
            response_time_ms=response_time_ms,
            metacog_signals=evaluation.get("metacog_signals") or {},
            attempt_number=attempt_number,
            session_id=self.session_id,
        )

        verdict = evaluation.get("verdict")
        current_consecutive = self.state.consecutive_incorrect if self.state else 0
        next_consecutive = current_consecutive + 1 if verdict == "incorrect" else 0
        feedback = {
            **evaluation,
            "answer_id": answer_id,
            "response_time_ms": response_time_ms,
            "consecutive_incorrect": next_consecutive,
        }
        self.on_feedback(feedback)
        self._push_history(answer_text, evaluation)

        if verdict in {"correct", "partial"}:
            if self.state:
                self.state.consecutive_incorrect = 0
            self._save_flashcard_if_any(evaluation.get("flashcard"))
            self._complete_paragraph()
            return

        if self.state:
            self.state.consecutive_incorrect += 1
            consecutive = self.state.consecutive_incorrect
        else:
            consecutive = 1

        if consecutive >= 2:
            self._generate_rephrasing_then_question()
        else:
            self._generate_question()

    def _generate_rephrasing_then_question(self) -> None:
        if not self.paragraph:
            return

        attempt_count = self.state.attempt_count if self.state else 2
        context = {
            "paragraph": self._paragraph_for_llm(),
            "image_paths": self._image_paths_for_llm(),
            "attempt_count": attempt_count,
        }
        self.on_loading("rephrasing")

        def _success(rephrasing: dict) -> None:
            rephrasing_id = save_rephrasing(
                question_id=self.current_question_id,
                session_id=self.session_id,
                angle=rephrasing.get("rephrasing_angle"),
                rephrased_text=rephrasing.get("rephrased_paragraph", ""),
                note=rephrasing.get("note"),
            )
            self.on_rephrasing({**rephrasing, "id": rephrasing_id})
            self._generate_question()

        def _error(message: str) -> None:
            self.on_error(message)
            self._generate_question()

        self.rephrasing_generator(context, _success, _error)

    def _persist_question(self, question: dict) -> int | None:
        if not self.paragraph or self.paragraph.doc_id is None:
            return None
        return save_question(
            doc_id=self.paragraph.doc_id,
            scope_type=self.paragraph.scope_type,
            scope_label=self.paragraph.label,
            page_start=self.paragraph.page_start,
            page_end=self.paragraph.page_end,
            question=question,
            llm_model=self.llm_model,
            session_id=self.session_id,
            chapter_id=self.paragraph.chapter_id,
        )

    def _save_flashcard_if_any(self, llm_flashcard: dict | None) -> None:
        if not self.current_question or not self.paragraph:
            return
        question_type = self.current_question.get("question_type", "")
        if question_type in {"metacognition", "anticipation"}:
            return

        llm_front = (llm_flashcard or {}).get("front", "").strip()
        llm_back = (llm_flashcard or {}).get("back", "").strip()
        front = llm_front if llm_front else self.current_question.get("question", "").strip()
        back = llm_back if llm_back else self.current_question.get("expected_answer", "").strip()
        if not front:
            return

        tags = (llm_flashcard or {}).get("tags") or []
        difficulty = (llm_flashcard or {}).get("difficulty", 2)
        save_flashcard(
            user_id=self.user_id,
            question_id=self.current_question_id,
            front=front,
            back=back,
            tags=tags,
            difficulty=difficulty,
            source="auto",
            document_id=self.paragraph.doc_id,
            chapter_id=self.paragraph.chapter_id,
            session_id=self.session_id,
            asset_paths=self.paragraph.image_paths,
        )

    def _push_history(self, answer_text: str, evaluation: dict) -> None:
        if not self.state or not self.current_question:
            return
        self.state.push_session_history({
            "question": self.current_question.get("question", ""),
            "question_type": self.current_question.get("question_type", ""),
            "answer": answer_text,
            "verdict": evaluation.get("verdict"),
            "feedback": evaluation.get("feedback", ""),
        })

    def _complete_paragraph(self) -> None:
        if self.state:
            self.state.qa_active = False
            self.state.current_question = None
            self.state.attempt_count = 0
            self.state.consecutive_incorrect = 0

        callback = self._on_complete
        self._on_complete = None
        if callback:
            callback()

    def _paragraph_for_llm(self) -> str:
        if not self.paragraph:
            return ""
        return _preprocess_paragraph_for_llm(self.paragraph.text, self.paragraph.blocks)

    def _image_paths_for_llm(self) -> list[str]:
        if not self.paragraph:
            return []
        return list(self.paragraph.image_paths)


def _normalize_paragraph_context(paragraph_scope, state: ReaderState | None) -> ParagraphContext:
    if isinstance(paragraph_scope, dict):
        block = paragraph_scope.get("block") or paragraph_scope
        text = paragraph_scope.get("paragraph") or block.get("text") or ""
        page = (
            block.get("page_number")
            or block.get("page_start")
            or block.get("page")
            or paragraph_scope.get("page_number")
            or paragraph_scope.get("page_start")
            or paragraph_scope.get("page")
        )
        all_blocks = paragraph_scope.get("blocks") or []
        context_blocks = _adjacent_context_blocks(block, all_blocks, page, page)
        if _is_context_block(block) and not _contains_block(context_blocks, block):
            context_blocks.insert(0, block)
        image_paths = _context_image_paths(context_blocks)
        source_block_id = str(paragraph_scope.get("source_block_id") or "").strip()
        if not source_block_id:
            source_block_id = _paragraph_source_block_id(block, page=page, text=text)
        return ParagraphContext(
            text=text,
            label=_paragraph_label(paragraph_scope.get("label"), block, page),
            page_start=paragraph_scope.get("page_start") or page,
            page_end=paragraph_scope.get("page_end") or page,
            doc_id=paragraph_scope.get("doc_id") or (state.doc_id if state else None),
            doc_title=paragraph_scope.get("doc_title", ""),
            chapter_title=paragraph_scope.get("chapter_title", ""),
            chapter_id=paragraph_scope.get("chapter_id"),
            block=block,
            blocks=context_blocks,
            image_paths=list(paragraph_scope.get("image_paths") or []) or image_paths,
            session_gauges=dict(paragraph_scope.get("session_gauges") or {}),
            recent_question_types=list(paragraph_scope.get("recent_question_types") or []),
            source_block_id=source_block_id,
            scope_type=str(paragraph_scope.get("scope_type") or "paragraph"),
        )

    text = str(paragraph_scope or "")
    return ParagraphContext(text=text, source_block_id=_paragraph_source_block_id(None, text=text))


def _paragraph_label(raw_label, block: dict | None, page) -> str:
    label = str(raw_label or t("qa.paragraph_label", page=page or "?")).strip()
    block_index = _block_index(block)
    if block_index is None or "#" in label:
        return label
    return f"{label} #{block_index + 1}"


def _paragraph_source_block_id(block: dict | None, page=None, text: str = "") -> str:
    if isinstance(block, dict):
        explicit = str(block.get("id") or "").strip()
        if explicit:
            return explicit

    page_number = _coerce_int(
        page
        or (block or {}).get("page_number")
        or (block or {}).get("page_start")
        or (block or {}).get("page")
    )
    block_index = _block_index(block)
    source_text = str(text or ((block or {}).get("text") if isinstance(block, dict) else "") or "")
    clean_text = " ".join(normalize_unicode_math(source_text).split())
    digest = hashlib.sha1(clean_text.encode("utf-8")).hexdigest()[:12] if clean_text else "empty"
    page_part = f"p{page_number}" if page_number is not None else "p?"
    index_part = f"b{block_index}" if block_index is not None else "b?"
    return f"{page_part}:{index_part}:{digest}"


def _preprocess_paragraph_for_llm(text: str, blocks: list) -> str:
    paragraph = normalize_unicode_math(text or "")
    annotations: list[str] = []
    english = current_lang() == "en"

    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "figure":
            caption = normalize_unicode_math((block.get("caption") or block.get("text") or "").strip())
            if caption:
                label = "Figure on this page" if english else "Figure sur cette page"
                separator = ":" if english else " :"
                annotations.append(f'[{label}{separator} "{caption}"]')
            else:
                annotations.append("[Figure on this page]" if english else "[Figure sur cette page]")
        elif btype == "formula":
            formula = normalize_unicode_math(safe_formula_context_text(block.get("latex") or block.get("text")))
            if formula:
                label = "Displayed formula" if english else "Formule affichée"
                separator = ":" if english else " :"
                annotations.append(f"[{label}{separator} {formula}]")
            else:
                annotations.append("[Displayed formula]" if english else "[Formule affichée]")
        elif btype == "table":
            markdown = normalize_unicode_math((block.get("markdown") or block.get("text") or "").strip())
            rows, columns = _table_dimensions(block, markdown)
            label = (
                f"[Table {rows}×{columns} rows×columns]"
                if english
                else f"[Tableau {rows}×{columns} lignes×colonnes]"
            )
            if markdown:
                annotations.append(f"{label}\n{markdown}")
            else:
                annotations.append(label)
        for asset in _block_asset_entries(block):
            reason = asset.get("reason") or ("visual_context" if english else "contexte_visuel")
            page = block.get("page_number") or block.get("page_start") or block.get("page") or "?"
            if english:
                annotations.append(f"[Visual asset attached to the model: PDF crop page {page}, reason={reason}]")
            else:
                annotations.append(f"[Asset visuel joint au modèle : crop PDF page {page}, raison={reason}]")

    if not annotations:
        return paragraph
    heading = "Adjacent context:" if english else "Contexte adjacent:"
    return "\n\n".join([paragraph, heading, *annotations])


def _adjacent_context_blocks(current_block: dict | None, all_blocks: list, page_start=None, page_end=None) -> list:
    if not all_blocks:
        return []

    page_start_int = _coerce_int(page_start)
    page_end_int = _coerce_int(page_end) or page_start_int
    current_index = _find_block_index(current_block, all_blocks)
    selected: list[dict] = []

    if current_index is not None:
        start = max(0, current_index - 2)
        end = min(len(all_blocks), current_index + 3)
        for index in range(start, end):
            if index == current_index:
                continue
            block = all_blocks[index]
            if _is_context_block(block):
                selected.append(block)

    for block in all_blocks:
        if not isinstance(block, dict) or block.get("type") != "figure":
            continue
        page = _coerce_int(block.get("page_number") or block.get("page_start") or block.get("page"))
        if page is None or page_start_int is None:
            continue
        if (page_start_int - 1) <= page <= ((page_end_int or page_start_int) + 1) and not _contains_block(selected, block):
            selected.append(block)

    return selected


def _find_block_index(current_block: dict | None, all_blocks: list) -> int | None:
    if not isinstance(current_block, dict):
        return None
    for index, block in enumerate(all_blocks):
        if block is current_block:
            return index

    current_block_index = _block_index(current_block)
    if current_block_index is not None:
        for index, block in enumerate(all_blocks):
            if _block_index(block) == current_block_index:
                return index

    current_text = (current_block.get("text") or "").strip()
    current_page = current_block.get("page_number") or current_block.get("page_start") or current_block.get("page")
    for index, block in enumerate(all_blocks):
        if not isinstance(block, dict):
            continue
        text = (block.get("text") or "").strip()
        page = block.get("page_number") or block.get("page_start") or block.get("page")
        if current_text and text == current_text and page == current_page:
            return index
    return None


def _block_index(block) -> int | None:
    if not isinstance(block, dict):
        return None
    metadata = block.get("metadata") or {}
    value = metadata.get("block_index", block.get("block_index"))
    return _coerce_int(value)


def _is_context_block(block) -> bool:
    return isinstance(block, dict) and (
        block.get("type") in {"figure", "table", "formula"} or bool(_block_asset_entries(block))
    )


def _contains_block(blocks: list[dict], candidate: dict) -> bool:
    return any(block is candidate or block == candidate for block in blocks)


def _context_image_paths(blocks: list) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        for asset in _block_asset_entries(block):
            path = str(asset.get("path") or "").strip()
            if path and path not in seen:
                paths.append(path)
                seen.add(path)
    return paths[:4]


def _block_asset_entries(block: dict) -> list[dict]:
    if not isinstance(block, dict):
        return []
    metadata = block.get("metadata") or {}
    entries: list[dict] = []

    for asset in metadata.get("llm_assets") or []:
        if isinstance(asset, dict) and asset.get("type") == "image" and asset.get("path"):
            entries.append({
                "path": str(asset.get("path")),
                "reason": str(asset.get("reason") or "context_asset"),
            })

    for key, reason in (
        ("visible_asset_path", "visible_asset"),
        ("block_crop_path", "block_crop"),
        ("context_asset_path", "context_crop"),
        ("formula_image_path", "formula_crop"),
        ("table_image_path", "table_crop"),
    ):
        path = metadata.get(key)
        if path:
            entries.append({"path": str(path), "reason": reason})

    image_path = block.get("image_path")
    if image_path and block.get("type") in {"figure", "formula", "table"}:
        entries.append({"path": str(image_path), "reason": block.get("type")})

    deduped: list[dict] = []
    seen: set[str] = set()
    for entry in entries:
        path = entry["path"]
        if path in seen:
            continue
        deduped.append(entry)
        seen.add(path)
    return deduped


def _table_dimensions(block: dict, markdown: str = "") -> tuple[int, int]:
    metadata = block.get("metadata") or {}
    rows = _coerce_int(metadata.get("rows") or block.get("rows"))
    columns = _coerce_int(metadata.get("columns") or block.get("columns"))
    if rows is not None and columns is not None:
        return rows, columns

    parsed_rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in markdown.splitlines()
        if line.strip().startswith("|") and not set(line.strip().replace("|", "").replace(" ", "")) <= {"-", ":"}
    ]
    if rows is None:
        rows = len(parsed_rows)
    if columns is None:
        columns = max((len(row) for row in parsed_rows), default=0)
    return rows or 0, columns or 0


def _coerce_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _recent_question_types_from_history(history: list[dict]) -> list[str]:
    result: list[str] = []
    for item in history or []:
        if isinstance(item, dict) and item.get("question_type"):
            result.append(str(item.get("question_type")))
    return result[-6:]


def _source_context_excerpt(text: str, max_chars: int = 900) -> str:
    clean = " ".join((text or "").strip().split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "…"


def _adaptive_session_hint(gauges: dict | None) -> str:
    try:
        attention = float((gauges or {}).get("attention", 100.0))
    except (TypeError, ValueError):
        attention = 100.0
    if attention < 45.0:
        return t("qa.low_attention_hint")
    return ""


Companion = AdaptiveCompanion
