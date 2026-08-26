# services/quiz.py — Construction des QCM (distracteurs LLM) + analyse de session.
from __future__ import annotations

import logging
import random

from config import question_types
from config.settings import (
    QUIZ_DEFAULT_QUESTIONS,
    QUIZ_MAX_QUESTIONS,
    QUIZ_MIN_QUESTIONS,
    QUIZ_SEARCH_MAX_TERMS,
    QUIZ_SEARCH_POOL,
)
from db.quiz_questions import (
    get_quiz_base_questions,
    get_quiz_subjects,
    get_static_quiz_questions,
)
from db.subjects import get_all_subjects, update_subject_from_answer
from db.user import DEFAULT_USER_ID
from llm.ollama_client import (
    generate_quiz_distractors_async,
    generate_quiz_session_analysis_async,
)
from services.llm_bridge import run_llm_sync
from utils.text import fold

logger = logging.getLogger("services.quiz")

__all__ = [
    "build_quiz",
    "clamp_quiz_length",
    "list_subjects",
    "submit_answer",
    "analyze_session",
    "finalize_quiz_session",
]

_CONTEXT_MAX_CHARS = 500


def clamp_quiz_length(n) -> int:
    """Longueur de session demandée, ramenée dans les bornes de `config.settings`."""
    try:
        value = int(n)
    except (TypeError, ValueError):
        return QUIZ_DEFAULT_QUESTIONS
    return max(QUIZ_MIN_QUESTIONS, min(QUIZ_MAX_QUESTIONS, value))


def list_subjects(user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Matières disponibles pour le quiz (avec effectif), pour le sélecteur."""
    return get_quiz_subjects(user_id)


def build_quiz(
    subject: str | None = None,
    n: int = QUIZ_DEFAULT_QUESTIONS,
    user_id: int = DEFAULT_USER_ID,
    topic: str | None = None,
) -> list[dict]:
    """Construit une session de QCM : questions de lecture + catalogue statique.

    ``topic`` est le sujet libre tapé par l'apprenant (« capitales », « révolution
    française ») : il classe les questions selon le COURS dont elles proviennent
    autant que selon leur énoncé (cf. ``course_search``). ``n`` est la longueur de
    session demandée, bornée par `config.settings`.

    Les questions de lecture passent d'abord ; le catalogue statique complète
    jusqu'à ``n`` — sinon une base neuve, ou un thème sans document importé,
    n'aurait aucun quiz à jouer.

    Les distracteurs des questions qui en ont besoin sont générés par le LLM en **un
    seul** appel batch. Chaque QCM renvoyé contient 4 choix mélangés (dont la bonne
    réponse). Une question dont on ne peut pas construire 4 choix est dégradée en
    question ouverte (``choices=None``, auto-évaluation côté UI) si une réponse existe,
    sinon écartée.
    """
    count = clamp_quiz_length(n)
    terms = _topic_terms(topic)
    # Avec un sujet libre, le filtrage se fait EN PYTHON (accents pliés) : on charge
    # un lot borné au lieu de laisser le LIMIT SQL trancher avant le filtre.
    pool = QUIZ_SEARCH_POOL if terms else count

    base = _rank_by_topic(get_quiz_base_questions(user_id, pool, subject), terms)[:count]
    if len(base) < count:
        missing = count - len(base)
        static = _rank_by_topic(
            get_static_quiz_questions(pool if terms else missing, subject), terms,
        )
        base.extend(static[:missing])
    if not base:
        return []

    # 1) Questions déjà munies de choix valides (≥4 dont la réponse) → réutilisées
    #    telles quelles. Les autres sont envoyées au LLM pour générer les distracteurs,
    #    sauf celles dont le type ne s'y prête pas : une remise en ordre garde ses
    #    étapes, une production longue (explication, contre-exemple…) reste ouverte —
    #    en faire un QCM trahirait le type affiché à l'apprenant.
    llm_items: list[dict] = []
    for q in base:
        answer = (q.get("answer") or "").strip()
        qtype = _question_type(q)
        if qtype == "ordering":
            steps = _ordering_steps(q.get("choices"))
            if steps is not None:
                q["_choices"] = steps
            continue
        existing = _valid_existing_choices(q.get("choices"), answer)
        if existing is not None:
            q["_choices"] = existing
            continue
        if not question_types.quiz_mcq_convertible(qtype):
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
            # Le type pilote le widget de réponse côté UI (mêmes composants que
            # la carte Q&R du lecteur) : sans lui, tout redevenait un QCM ou un
            # champ texte anonyme.
            "question_type": _question_type(q),
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


def finalize_quiz_session(
    responses: list[str],
    score: float,
    questions_answered: int = 0,
    correct: int = 0,
    duration_s: int = 0,
    subject: str | None = None,
    topic: str | None = None,
    user_id: int = DEFAULT_USER_ID,
) -> dict:
    """Sas de sortie d'une session de quiz : réflexions + nudge du profil long terme.

    Même rituel de clôture qu'une lecture PDF ou qu'une séance de langue, et
    surtout le MÊME chemin de finalisation (`services.session.nudge_metacog_profile`) :
    un quiz est une mesure d'apprentissage, il doit peser sur le profil. `session_id=None`
    parce qu'un quiz n'est pas une session de lecture (aucun document derrière).
    """
    score = max(0.0, min(100.0, float(score or 0.0)))
    metrics = {
        "duration_s": max(0, int(duration_s or 0)),
        "pages_read": 0,
        "questions_answered": max(0, int(questions_answered or 0)),
        "correct": max(0, int(correct or 0)),
        "success_rate": round(score),
        "subject": subject or None,
        "topic": (topic or "").strip() or None,
    }
    try:
        from services.session import nudge_metacog_profile

        nudge_metacog_profile(user_id, score, list(responses or []), metrics, session_id=None)
    except Exception:  # pragma: no cover - best-effort : la clôture ne doit pas casser
        logger.debug("Nudge métacognitif (quiz) ignoré", exc_info=True)
    return {"ok": True, "score": score}


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

def _topic_terms(topic: str | None) -> list[str]:
    """Mots significatifs du sujet de session, repliés (mêmes règles que la biblio)."""
    if not (topic or "").strip():
        return []
    from services.brainstorm_search import extract_terms

    terms = extract_terms(topic or "", max_terms=QUIZ_SEARCH_MAX_TERMS)
    if terms:
        return terms
    # « ia », « c++ », « uk » : requêtes courtes légitimes que le découpage en
    # mots significatifs rejette.
    folded = fold(topic or "")
    return [folded] if len(folded) >= 2 else []


def _topic_hits(q: dict, terms: list[str]) -> int:
    """Nombre de termes DISTINCTS du sujet retrouvés dans la question ou son cours."""
    haystack = fold(" ".join(str(part) for part in (
        q.get("question") or "",
        q.get("answer") or "",
        " ".join(str(c) for c in (q.get("choices") or [])),
        q.get("category") or "",
        # Remontée à la fiche du cours : le sujet cherché est souvent celui du
        # document, pas un mot de l'énoncé.
        q.get("course_search") or "",
    )))
    return sum(1 for term in terms if term in haystack)


def _rank_by_topic(items: list[dict], terms: list[str]) -> list[dict]:
    """Garde les questions touchées par le sujet, les plus pertinentes d'abord.

    Classement calqué sur `services.library.search_documents` : nombre de termes
    distincts trouvés d'abord, ordre d'origine (déjà « ratées puis récentes »)
    pour départager. Sans sujet, la liste passe telle quelle.
    """
    if not terms:
        return list(items)
    scored = [
        (hits, rank, q)
        for rank, q in enumerate(items)
        if (hits := _topic_hits(q, terms))
    ]
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [q for (_hits, _rank, q) in scored]


def _question_type(q: dict) -> str:
    """Type stocké, normalisé. "open" pour les questions d'avant la grille typée."""
    qtype = (q.get("question_type") or "").strip().lower()
    return qtype if qtype in question_types.KEYS else "open"


def _ordering_steps(choices) -> list[str] | None:
    """Étapes d'une remise en ordre, DANS L'ORDRE CORRECT (l'UI les mélangera).

    Contrairement à un QCM, on ne touche ni au nombre ni à l'ordre : c'est la
    réponse elle-même. Sans assez d'étapes, la question repasse en réponse libre."""
    if not isinstance(choices, list):
        return None
    minimum, maximum = question_types.choice_bounds("ordering")
    steps = [str(c).strip() for c in choices if str(c).strip()]
    return steps[:maximum] if len(steps) >= minimum else None


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
