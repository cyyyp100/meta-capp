# services/quiz.py — Construction d'une session de quiz (tous types de questions)
# + correction des réponses rédigées + analyse de session.
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
from db.questions import get_question
from db.quiz_questions import (
    STATIC_ID_OFFSET,
    get_quiz_base_questions,
    get_quiz_subjects,
    get_static_quiz_questions,
)
from db.subjects import get_all_subjects, update_subject_from_answer
from db.user import DEFAULT_USER_ID
from llm.ollama_client import (
    evaluate_answer_async,
    generate_quiz_distractors_async,
    generate_quiz_session_analysis_async,
)
from services.assistant import objective_verdict
from services.llm_bridge import run_llm_sync
from utils.text import fold

logger = logging.getLogger("services.quiz")

__all__ = [
    "build_quiz",
    "clamp_quiz_length",
    "list_subjects",
    "submit_answer",
    "evaluate_quiz_answer",
    "analyze_session",
    "finalize_quiz_session",
]

_CONTEXT_MAX_CHARS = 500

# Verdicts corrigibles et leur poids dans le score de session. Le « partiel »
# vaut un demi-point : le renvoyer à zéro effacerait la moitié comprise, le
# compter juste effacerait la moitié manquante.
VERDICTS: tuple[str, ...] = ("correct", "partial", "incorrect")
VERDICT_SCORES: dict[str, float] = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}


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
    """Construit une session de quiz : questions de lecture + catalogue statique.

    ``topic`` est le sujet libre tapé par l'apprenant (« capitales », « révolution
    française ») : il classe les questions selon le COURS dont elles proviennent
    autant que selon leur énoncé (cf. ``course_search``). ``n`` est la longueur de
    session demandée, bornée par `config.settings`.

    Les questions de lecture passent d'abord ; le catalogue statique complète
    jusqu'à ``n`` — sinon une base neuve, ou un thème sans document importé,
    n'aurait aucun quiz à jouer.

    **Chaque question garde le type sous lequel elle a été posée pendant la
    lecture**, et donc son widget de réponse (`config.question_types.widget`) :
    QCM et ordre de grandeur en liste de choix, remise en ordre en étapes à
    replacer, tout le reste en réponse rédigée corrigée par
    :func:`evaluate_quiz_answer`. Transformer d'office ces types en QCM — ce que
    faisait le quiz — affichait « explique à un débutant » au-dessus de quatre
    boutons, et réduisait toute session à un questionnaire à choix multiples.

    Seuls les types à liste de choix passent donc par le LLM, en **un seul** appel
    batch, pour compléter leurs distracteurs (4 choix mélangés dont la bonne
    réponse). Faute de choix constructibles, la question redevient une question à
    rédiger si une réponse existe, sinon elle est écartée.
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

    # 1) Préparation par widget. Les listes de choix déjà valides (≥4 dont la
    #    réponse) sont réutilisées telles quelles ; les autres partent au LLM pour
    #    leurs distracteurs. Une remise en ordre garde ses étapes — elles SONT la
    #    réponse —, une question à rédiger n'a rien à préparer.
    llm_items: list[dict] = []
    for q in base:
        answer = (q.get("answer") or "").strip()
        widget = question_types.widget(_question_type(q))
        if widget == question_types.WIDGET_ORDERING:
            steps = _ordering_steps(q.get("choices"))
            if steps is None:
                # Sans étapes, une remise en ordre n'est pas rejouable
                # (`question_types.requires_choices`) : on l'écarte.
                q["_skip"] = True
            else:
                q["_choices"] = steps
            continue
        if widget != question_types.WIDGET_CHOICES:
            continue
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
        if q.pop("_skip", False):
            continue
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
            # Type à rédiger, ou QCM dont les distracteurs ont manqué : la
            # réponse attendue suffit à jouer et à corriger la question.
            item["choices"] = None
            quiz.append(item)
        # sinon (ni choix ni réponse) : question écartée.

    return quiz


def submit_answer(
    category: str | None,
    correct: bool,
    user_id: int = DEFAULT_USER_ID,
    session_id: int | None = None,
    verdict: str | None = None,
) -> dict:
    """Met à jour la maîtrise de la matière ET la rétention permanente.

    Un quiz de révision est une mesure directe de la mémorisation : il fait donc
    bouger le critère `retention` du profil long terme, en plus du niveau de la
    matière. Les deux mises à jour sont indépendantes — une question sans matière
    nourrit quand même la rétention.

    ``verdict`` transporte la nuance des réponses rédigées : la rétention connaît
    une cible « partial » (`metacog.profile`), que le booléen à lui seul écrasait
    en « incorrect ». Sans verdict, il est déduit du booléen."""
    from metacog.profile import update_retention_from_quiz

    graded = (verdict or "").strip().lower()
    if graded not in VERDICTS:
        graded = "correct" if correct else "incorrect"
    retention = update_retention_from_quiz(user_id, graded, session_id=session_id)
    result = {
        "updated": bool(category),
        "verdict": graded,
        "retention": float(retention.get("retention", 50.0)),
    }
    if not category:
        return result
    result["category"] = category
    result["level"] = update_subject_from_answer(user_id, category, bool(correct))
    return result


def evaluate_quiz_answer(
    question_id: int | None,
    question: str,
    user_answer: str,
    question_type: str = "",
    expected_answer: str = "",
    choices: list[str] | None = None,
    user_id: int = DEFAULT_USER_ID,
) -> dict:
    """Corrige une réponse de quiz : verdict objectif quand il existe, LLM sinon.

    C'est le pendant, hors lecture, de `services.assistant.evaluate_page_answer` :
    même verdict objectif partagé (`objective_verdict` — QCM, remise en ordre),
    même prompt d'évaluation, mais le passage de référence est le contexte
    persisté avec la question au lieu de la page ouverte. Sans lui, un quiz ne
    pouvait poser que des QCM : une réponse rédigée n'aurait eu personne pour la
    corriger.

    La question de lecture persistée fait foi (réponse canonique, propositions,
    type, passage) ; ce que la session envoie ne sert que pour le catalogue
    statique, qui n'est pas dans la table `questions`.

    Renvoie ``{verdict, score, feedback, hint, completion, expected_answer,
    graded}``. ``graded=False`` signale que la correction n'a pas pu être faite
    (LLM indisponible) : l'appelant repasse alors à l'auto-évaluation plutôt que
    de bloquer la session.
    """
    stored = _stored_reading_question(question_id)
    qtype = _question_type({"question_type": stored.get("question_type") or question_type})
    expected = str(stored.get("answer") or expected_answer or "").strip()
    options = [str(c).strip() for c in (stored.get("choices") or choices or []) if str(c).strip()]
    given = (user_answer or "").strip()

    # Rien à juger : ni le LLM ni l'apprenant n'ont à trancher une case vide
    # (« je ne sais pas » de l'UI).
    if not given:
        return _evaluation("incorrect", expected)

    verdict = objective_verdict(qtype, given, expected, options)
    if verdict:
        return _evaluation(verdict, expected)

    question_block: dict = {
        "question": str(stored.get("question") or question or ""),
        "question_type": qtype,
    }
    if expected:
        question_block["expected_answer"] = expected
    if options:
        question_block["choices"] = options
    context = {
        "question": question_block,
        "user_answer": given,
        # Le passage d'origine : le LLM corrige en le voyant, au lieu de juger la
        # réponse sur sa seule culture générale.
        "paragraph": str(stored.get("source_context") or ""),
        "metacog_profile": _metacog_profile(user_id),
        "objective_verdict": "",
    }
    try:
        evaluation = run_llm_sync(
            lambda ok, err: evaluate_answer_async(context, ok, err),
        ) or {}
    except Exception as exc:  # dégradation best-effort : auto-évaluation côté UI
        logger.warning("Correction de la réponse de quiz échouée : %s", exc)
        return _evaluation("", expected, graded=False)

    verdict = str(evaluation.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        return _evaluation("", expected, graded=False)
    return _evaluation(
        verdict,
        expected,
        feedback=str(evaluation.get("feedback") or ""),
        hint=str(evaluation.get("hint") or "") if verdict == "incorrect" else "",
        completion=str(evaluation.get("completion") or "") if verdict == "partial" else "",
    )


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


def _evaluation(
    verdict: str,
    expected_answer: str,
    *,
    feedback: str = "",
    hint: str = "",
    completion: str = "",
    graded: bool = True,
) -> dict:
    """Résultat de correction, tel que l'UI du quiz l'attend."""
    return {
        "verdict": verdict,
        "score": VERDICT_SCORES.get(verdict, 0.0),
        "feedback": feedback,
        "hint": hint,
        "completion": completion,
        "expected_answer": expected_answer,
        "graded": bool(graded and verdict in VERDICTS),
    }


def _stored_reading_question(question_id) -> dict:
    """Question de lecture persistée, ou {} si l'id n'en désigne aucune.

    Le catalogue statique porte des ids décalés (`STATIC_ID_OFFSET`) et ne vit pas
    dans la table `questions` : pour lui, la correction s'en tient à ce que la
    session a reçu."""
    try:
        qid = int(question_id)
    except (TypeError, ValueError):
        return {}
    if qid <= 0 or qid >= STATIC_ID_OFFSET:
        return {}
    try:
        return get_question(qid) or {}
    except Exception:  # pragma: no cover - lecture best-effort
        logger.debug("Lecture de la question %s ignorée", qid, exc_info=True)
        return {}


def _metacog_profile(user_id: int) -> dict:
    """Profil long terme, pour que la correction s'adresse à CET apprenant."""
    try:
        from metacog.profile import ensure_profile

        return ensure_profile(user_id) or {}
    except Exception:  # pragma: no cover - le profil n'est qu'un contexte
        logger.debug("Profil métacognitif indisponible pour la correction", exc_info=True)
        return {}


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
