# services/quiz.py — Construction des QCM (distracteurs LLM) + analyse de session.
from __future__ import annotations

import logging
import random

from db.quiz_questions import (
    get_quiz_base_questions,
    get_quiz_subjects,
)
from db.subjects import get_all_subjects, update_subject_from_answer
from db.user import DEFAULT_USER_ID
from llm.ollama_client import (
    generate_quiz_distractors_async,
    generate_quiz_session_analysis_async,
)
from services.llm_bridge import run_llm_sync

logger = logging.getLogger("services.quiz")

__all__ = ["build_quiz", "list_subjects", "submit_answer", "analyze_session"]

_CONTEXT_MAX_CHARS = 500


def list_subjects(user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Matières disponibles pour le quiz (avec effectif), pour le sélecteur."""
    return get_quiz_subjects(user_id)


def build_quiz(subject: str | None = None, n: int = 10, user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Construit une session de QCM à partir des questions de lecture stockées.

    Les distracteurs des questions qui en ont besoin sont générés par le LLM en **un
    seul** appel batch. Chaque QCM renvoyé contient 4 choix mélangés (dont la bonne
    réponse). Une question dont on ne peut pas construire 4 choix est dégradée en
    question ouverte (``choices=None``, auto-évaluation côté UI) si une réponse existe,
    sinon écartée.
    """
    base = get_quiz_base_questions(user_id, n, subject)
    if not base:
        return []

    # 1) Questions déjà munies de choix valides (≥4 dont la réponse) → réutilisées
    #    telles quelles. Les autres sont envoyées au LLM pour générer les distracteurs.
    llm_items: list[dict] = []
    for q in base:
        answer = (q.get("answer") or "").strip()
        existing = _valid_existing_choices(q.get("choices"), answer)
        if existing is not None:
            q["_choices"] = existing
            continue
        llm_items.append({
            "id": q["id"],
            "question": q.get("question") or "",
            "answer": answer,
            "context": _short_context(q),
        })

    distractors_map: dict[int, dict] = {}
    if llm_items:
        try:
            distractors_map = run_llm_sync(
                lambda ok, err: generate_quiz_distractors_async({"items": llm_items}, ok, err),
            ) or {}
        except Exception as exc:  # pragma: no cover - dégradation best-effort
            logger.warning("Génération des distracteurs de quiz échouée : %s", exc)
            distractors_map = {}

    # 2) Assemblage final
    quiz: list[dict] = []
    for q in base:
        choices = q.pop("_choices", None)
        stored_answer = (q.get("answer") or "").strip()
        llm = distractors_map.get(q["id"])
        # Quand le LLM a (re)formaté la réponse (maths en LaTeX $...$), on l'utilise
        # pour rester cohérent avec ses distracteurs ; sinon on garde la réponse stockée.
        llm_answer = str(llm.get("answer") or "").strip() if llm else ""
        answer = llm_answer or stored_answer

        if choices is None and llm and answer:
            choices = _assemble_choices(answer, llm.get("distractors") or [])

        item = {
            "id": q["id"],
            "question": q.get("question") or "",
            "answer": answer,
            "category": q.get("category") or "culture",
            "document": q.get("document"),
            "document_id": q.get("document_id"),
            "chapter_title": q.get("chapter_title"),
            "source": q.get("source") or "reading",
        }
        if choices is not None:
            item["choices"] = choices
            quiz.append(item)
        elif answer:
            # Repli : pas de QCM possible mais une réponse existe → question ouverte.
            item["choices"] = None
            quiz.append(item)
        # sinon (ni choix ni réponse) : question écartée.

    return quiz


def submit_answer(
    category: str | None,
    correct: bool,
    user_id: int = DEFAULT_USER_ID,
    session_id: int | None = None,
) -> dict:
    """Met à jour la maîtrise de la matière ET la rétention permanente.

    Un quiz de révision est une mesure directe de la mémorisation : il fait donc
    bouger le critère `retention` du profil long terme, en plus du niveau de la
    matière. Les deux mises à jour sont indépendantes — une question sans matière
    nourrit quand même la rétention."""
    from metacog.profile import update_retention_from_quiz

    retention = update_retention_from_quiz(
        user_id, "correct" if correct else "incorrect", session_id=session_id,
    )
    result = {
        "updated": bool(category),
        "retention": float(retention.get("retention", 50.0)),
    }
    if not category:
        return result
    result["category"] = category
    result["level"] = update_subject_from_answer(user_id, category, bool(correct))
    return result


def analyze_session(answers_history: list[dict], user_id: int = DEFAULT_USER_ID) -> dict:
    """Analyse LLM de fin de session + conseil de cours à renforcer.

    Réutilise le prompt/parseur existants puis enrichit chaque cours recommandé d'un
    ``document_id`` (déduit de l'historique) pour permettre le deep-link vers le reader.
    """
    history = answers_history or []
    empty = {"analysis": "", "weak_subjects": [], "courses_to_review": []}
    if not history:
        return empty

    subject_profiles = get_all_subjects(user_id)
    try:
        result = run_llm_sync(
            lambda ok, err: generate_quiz_session_analysis_async(
                {"answers_history": history, "subject_profiles": subject_profiles}, ok, err
            ),
        )
    except Exception as exc:  # pragma: no cover - dégradation best-effort
        logger.warning("Analyse de session de quiz échouée : %s", exc)
        return empty
    if not isinstance(result, dict):
        return empty

    # Map document (nom de fichier) -> document_id depuis l'historique des réponses.
    doc_map: dict[str, int] = {}
    for entry in history:
        doc = str(entry.get("document") or "").strip().lower()
        did = entry.get("document_id")
        if doc and isinstance(did, int):
            doc_map.setdefault(doc, did)

    courses = result.get("courses_to_review") or []
    for course in courses:
        if not isinstance(course, dict):
            continue
        key = str(course.get("document") or course.get("title") or "").strip().lower()
        course["document_id"] = doc_map.get(key)

    return {
        "analysis": result.get("analysis", ""),
        "weak_subjects": result.get("weak_subjects", []),
        "courses_to_review": courses,
    }


# ── Helpers ─────────────────────────────────────────────────────────────────

def _short_context(q: dict) -> str:
    context = (q.get("source_context") or q.get("course_context") or "").strip()
    context = " ".join(context.split())
    return context[:_CONTEXT_MAX_CHARS]


def _valid_existing_choices(choices, answer: str) -> list[str] | None:
    """Réutilise des choix déjà stockés s'ils forment un QCM valide (≥4, dont la réponse)."""
    if not isinstance(choices, list) or not answer:
        return None
    cleaned = list(dict.fromkeys(str(c).strip() for c in choices if str(c).strip()))
    if len(cleaned) < 4:
        return None
    if not any(c.lower() == answer.lower() for c in cleaned):
        return None
    pool = [c for c in cleaned if c.lower() != answer.lower()]
    return _assemble_choices(answer, pool)


def _assemble_choices(answer: str, distractors: list[str]) -> list[str] | None:
    """Construit 4 options uniques mélangées : la bonne réponse + 3 distracteurs."""
    answer = (answer or "").strip()
    if not answer:
        return None
    options = [answer]
    seen = {answer.lower()}
    for cand in distractors:
        cand = str(cand).strip()
        if cand and cand.lower() not in seen:
            seen.add(cand.lower())
            options.append(cand)
        if len(options) == 4:
            break
    if len(options) < 4:
        return None
    random.shuffle(options)
    return options
