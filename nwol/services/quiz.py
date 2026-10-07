# services/quiz.py — Construction d'une session de quiz (tous types de questions)
# + correction des réponses rédigées + analyse de session.
from __future__ import annotations

import logging
import random

from config import question_types
from config.settings import (
    QUIZ_DEFAULT_QUESTIONS,
    QUIZ_EXPOSURE_FLOOR,
    QUIZ_EXPOSURE_HALF_LIFE_DAYS,
    QUIZ_FAILED_BONUS,
    QUIZ_FRESHNESS_FLOOR,
    QUIZ_FRESHNESS_HALF_LIFE_DAYS,
    QUIZ_MAX_QUESTIONS,
    QUIZ_MIN_QUESTIONS,
    QUIZ_REVIEW_MAX_COURSES,
    QUIZ_SEARCH_MAX_TERMS,
    QUIZ_SEARCH_POOL,
)
from config.subjects import canonical_subject
from db.documents import get_document
from db.metacog import CRITERIA
from db.practice_sessions import (
    end_practice_session,
    get_practice_session,
    get_quiz_answers,
    save_quiz_answers,
    update_practice_details,
)
from db.questions import get_question
from db.quiz_exposures import get_exposures, record_exposures
from db.quiz_questions import (
    STATIC_ID_OFFSET,
    count_quiz_questions,
    get_quiz_base_questions,
    get_static_quiz_questions,
)
from db.subjects import get_all_subjects, update_subject_from_answer
from db.user import DEFAULT_USER_ID
from services import practice, selection
from services.subjects import describe, owned_subjects
from llm.ollama_client import (
    evaluate_answer_async,
    generate_quiz_distractors_async,
    generate_quiz_session_analysis_async,
)
from metacog.gauges import QUESTION_TYPE_TARGET_GAUGES
from metacog.reflection import augment_evaluation_with_response_signals
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
    "record_quiz_session",
    "quiz_metrics",
    "analyze_session",
    "finalize_quiz_session",
]

_CONTEXT_MAX_CHARS = 500

# Verdicts corrigibles et leur poids dans le score de session. Le « partiel »
# vaut un demi-point : le renvoyer à zéro effacerait la moitié comprise, le
# compter juste effacerait la moitié manquante.
VERDICTS: tuple[str, ...] = ("correct", "partial", "incorrect")
VERDICT_SCORES: dict[str, float] = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}

# Bornes de ce qu'une séance enregistre de chaque réponse : un quiz se joue en
# minutes, une réponse au-delà d'une heure dit une fenêtre oubliée, pas un temps.
_MAX_RESPONSE_MS = 3_600_000
_MAX_ANSWER_CHARS = 4000


def clamp_quiz_length(n) -> int:
    """Longueur de session demandée, ramenée dans les bornes de `config.settings`."""
    try:
        value = int(n)
    except (TypeError, ValueError):
        return QUIZ_DEFAULT_QUESTIONS
    return max(QUIZ_MIN_QUESTIONS, min(QUIZ_MAX_QUESTIONS, value))


def list_subjects(user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Les matières du sélecteur : celles de l'apprenant, exactement celles de son
    profil (`services.subjects`), chacune avec son nombre de questions jouables.

    Une matière encore sans question (document importé mais pas encore lu) reste
    listée avec `count = 0` : l'UI la montre sans la proposer, plutôt que de
    laisser croire qu'elle n'existe pas."""
    counts = count_quiz_questions()
    return [
        {**describe(subject), "count": counts.get(subject, 0)}
        for subject in owned_subjects(user_id)
    ]


def build_quiz(
    subject: str | None = None,
    n: int = QUIZ_DEFAULT_QUESTIONS,
    user_id: int = DEFAULT_USER_ID,
    topic: str | None = None,
    interleaved: bool = False,
) -> list[dict]:
    """Construit une session de quiz : questions de lecture + catalogue statique.

    ``topic`` est le sujet libre tapé par l'apprenant (« capitales », « révolution
    française ») : il classe les questions selon le COURS dont elles proviennent
    autant que selon leur énoncé (cf. ``course_search``). ``n`` est la longueur de
    session demandée, bornée par `config.settings`.

    ``interleaved`` est la **pratique entrelacée** : un tirage aléatoire dans toute
    la base, alterné d'un domaine à l'autre (cf. :func:`_interleave_by_category`).
    Ce mode ignore délibérément ``subject`` et ``topic`` — s'en tenir à une matière
    ou à un thème est exactement ce qu'il s'agit de ne pas faire. L'exclusivité est
    tranchée ici, et pas seulement grisée dans l'UI.

    Les questions de lecture passent d'abord ; le catalogue statique complète
    jusqu'à ``n`` — sinon une matière dont aucun document n'a encore été lu
    n'aurait aucun quiz à jouer. Le catalogue ne sert QUE les matières de
    l'apprenant (`services.subjects.owned_subjects`) : il complète ses matières,
    il ne lui en donne pas de nouvelles.

    **Dans tous les modes, on charge un VIVIER (`QUIZ_SEARCH_POOL`) puis on tire
    dedans** (:func:`_pick`). Prendre la tête d'une liste bornée par ``count``
    revenait à laisser le ``ORDER BY`` SQL choisir la session : deux quiz d'affilée
    sur la même matière rendaient exactement les mêmes questions, et le stock
    ancien n'était jamais rejoué. Les questions servies sont mémorisées
    (`db.quiz_exposures`) pour amortir leur retour au tour suivant.
    """
    count = clamp_quiz_length(n)
    owned = owned_subjects(user_id)
    if interleaved:
        # L'alternance se décide EN PYTHON, donc on charge un lot borné au lieu de
        # laisser le LIMIT SQL trancher avant. Le catalogue statique entre dans le
        # vivier, pour les matières de l'apprenant : il les étoffe, ce qui rend
        # l'alternance possible même quand une matière n'a qu'un document lu.
        # Le tirage pondéré passe AVANT la répartition par domaine (sinon la même
        # tête de paquet ouvre toutes les sessions entrelacées) et sépare lecture
        # et catalogue : `_interleave_by_category` conserve l'ordre reçu à
        # l'intérieur d'un domaine, ce qui fait passer le matériel de l'apprenant
        # devant le catalogue de secours.
        pool = _weighted_order(
            get_quiz_base_questions(user_id, QUIZ_SEARCH_POOL, None, shuffle=True), [], user_id,
        ) + _weighted_order(get_static_quiz_questions(QUIZ_SEARCH_POOL, subjects=owned), [], user_id)
        return _served(_assemble_quiz(_interleave_by_category(pool, count)), user_id)

    terms = _topic_terms(topic)
    base = _pick(
        _rank_by_topic(get_quiz_base_questions(user_id, QUIZ_SEARCH_POOL, subject), terms),
        terms, count, user_id,
    )
    if len(base) < count:
        missing = count - len(base)
        base.extend(_pick(
            _rank_by_topic(get_static_quiz_questions(QUIZ_SEARCH_POOL, subject, owned), terms),
            terms, missing, user_id,
        ))
    if not base:
        return []
    return _served(_assemble_quiz(base), user_id)


def _served(quiz: list[dict], user_id: int) -> list[dict]:
    """Marque la session comme servie, puis la renvoie telle quelle.

    Enregistré ICI, au départ vers le client, et non à la correction : une session
    abandonnée à la troisième question doit quand même faire tourner le stock au
    tour suivant. Best-effort — un quiz jouable prime sur son historique.
    """
    try:
        record_exposures(user_id, [(q["id"], q.get("source") or "reading") for q in quiz])
    except Exception:  # pragma: no cover - best-effort
        logger.debug("Enregistrement de l'exposition du quiz ignoré", exc_info=True)
    return quiz


def _assemble_quiz(base: list[dict]) -> list[dict]:
    """Questions sélectionnées → session jouable : widgets, distracteurs, format.

    Commun à tous les modes de sélection : c'est la sélection qui varie (matière,
    sujet libre, pratique entrelacée), pas la mise en forme.

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
    verdict: str | None = None,
) -> dict:
    """Met à jour la maîtrise de la matière, réponse par réponse.

    Le profil métacognitif, lui, ne bouge plus ici : la rétention glissait de 8 %
    à CHAQUE réponse, hors de toute séance, puis une seconde fois à la clôture —
    deux modèles de l'apprenant pour une même mesure. Les réponses font désormais
    une courbe de jauges (`record_quiz_session`), que la finalisation commune
    remonte au profil comme celle d'une lecture.

    ``verdict`` garde la nuance des réponses rédigées ; sans lui, il est déduit
    du booléen."""
    graded = (verdict or "").strip().lower()
    if graded not in VERDICTS:
        graded = "correct" if correct else "incorrect"
    # Seule une matière du vocabulaire (config/subjects.py) a un niveau : une
    # catégorie inconnue n'en crée pas une de plus.
    subject = canonical_subject(category)
    result = {"updated": bool(subject), "verdict": graded}
    if not subject:
        return result
    result["category"] = subject
    result["level"] = update_subject_from_answer(user_id, subject, bool(correct))
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
        # Ce que le LLM a lu de la réponse au-delà du verdict : la séance les
        # renvoie avec ses réponses, pour que la rédaction fasse bouger les
        # jauges comme dans le lecteur (`record_quiz_session`).
        signals=_clean_signals(evaluation),
    )


def record_quiz_session(
    settings: dict | None,
    answers: list[dict],
    duration_s: int = 0,
    user_id: int = DEFAULT_USER_ID,
) -> dict:
    """Enregistre une séance de quiz jouée : ses réponses, sa courbe de jauges.

    Le pendant de `POST /session/{id}/end` pour une lecture. Les réponses
    arrivent d'un bloc, à la fin (ou quand l'apprenant quitte en cours de route) :
    le quiz vit dans le navigateur et ses jauges ne s'affichent jamais pendant la
    séance, il n'y a donc rien à tenir à jour avant. Chaque réponse devient une
    mesure (`_quiz_measures`), rejouée par le moteur unique en une courbe dont
    l'axe est le numéro de question. Rien n'est enregistré sans réponse.

    Renvoie ``{session_id, metrics}`` — ``session_id`` sert ensuite à l'analyse
    (gardée avec la séance) et à la finalisation (qui fait glisser le profil)."""
    clean = [
        cleaned for index, entry in enumerate(answers or [])
        if isinstance(entry, dict) and (cleaned := _clean_answer(entry, index))
    ]
    if not clean:
        return {"session_id": None, "metrics": quiz_metrics([], duration_s)}
    scope = _session_scope(settings, len(clean))
    session_id = practice.start(
        "quiz", user_id,
        settings={key: scope[key] for key in ("mode", "subject", "topic")},
    )
    save_quiz_answers(session_id, clean)
    practice.record(session_id, _quiz_measures(clean))
    end_practice_session(session_id, duration_s)
    return {"session_id": session_id, "metrics": quiz_metrics(clean, duration_s)}


def quiz_metrics(answers: list[dict], duration_s: int | None = 0) -> dict:
    """Métriques d'une séance de quiz, tirées de ses réponses. Un « partiel »
    compte un demi-point, comme dans le bilan affiché."""
    total = len(answers)
    points = sum(VERDICT_SCORES.get(a.get("verdict"), 0.0) for a in answers)
    return {
        "duration_s": max(0, int(duration_s or 0)),
        "pages_read": 0,
        "questions_answered": total,
        "correct": sum(1 for a in answers if a.get("verdict") == "correct"),
        "partial": sum(1 for a in answers if a.get("verdict") == "partial"),
        "points": points,
        "success_rate": round(100 * points / total) if total else 0,
    }


def finalize_quiz_session(
    responses: list[str],
    score: float,
    questions_answered: int = 0,
    correct: int = 0,
    duration_s: int = 0,
    subject: str | None = None,
    topic: str | None = None,
    user_id: int = DEFAULT_USER_ID,
    session_id: int | None = None,
) -> dict | None:
    """Clôture d'une séance de quiz : réflexions + glissement du profil long terme.

    Même chemin de finalisation qu'une lecture ou qu'une séance de langue
    (`services.session.nudge_metacog_profile`) : un quiz est une mesure
    d'apprentissage, il doit peser sur le profil.

    Avec ``session_id`` (séance enregistrée par `record_quiz_session`), le profil
    glisse vers la courbe de jauges de la séance, au prorata de ses réponses, et
    les métriques sont relues en base : le client n'a rien à recompter. Renvoie
    None si la séance n'existe pas. Sans ``session_id`` (ancien client), le repli
    d'avant : les trois critères de performance vers le taux de réussite.
    """
    if session_id is not None:
        session = get_practice_session(int(session_id))
        if session is None or session.get("kind") != "quiz":
            return None
        answers = get_quiz_answers(int(session_id))
        metrics = {
            **quiz_metrics(answers, session.get("duration_s")),
            **{key: (session.get("settings") or {}).get(key) for key in ("mode", "subject", "topic")},
        }
        try:
            from services.session import nudge_metacog_profile

            nudge_metacog_profile(
                user_id, float(metrics["success_rate"]), list(responses or []), metrics,
                session_id=None, practice_session_id=int(session_id), measures=len(answers),
            )
        except Exception:  # pragma: no cover - best-effort : la clôture ne doit pas casser
            logger.debug("Nudge métacognitif (quiz) ignoré", exc_info=True)
        return {"ok": True, "score": float(metrics["success_rate"]), "session_id": int(session_id)}

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

        nudge_metacog_profile(user_id, score, list(responses or []), metrics, session_id=None, kind="quiz")
    except Exception:  # pragma: no cover - best-effort : la clôture ne doit pas casser
        logger.debug("Nudge métacognitif (quiz) ignoré", exc_info=True)
    return {"ok": True, "score": score}


def analyze_session(
    answers_history: list[dict],
    user_id: int = DEFAULT_USER_ID,
    settings: dict | None = None,
    session_id: int | None = None,
) -> dict:
    """Bilan de fin de session : cours à renforcer (calculés) + analyse LLM.

    Les **cours à renforcer** ne viennent pas du LLM : ce sont les documents de la
    bibliothèque dont des questions ont été manquées (:func:`_courses_to_review`).
    Laissé à lui-même, le LLM en fabriquait à partir des questions du catalogue
    statique (« git commit »), qui n'a aucun cours derrière lui — la carte
    affichait alors un cours introuvable. ``weak_subjects`` est calculé de même.

    L'**analyse** est rédigée dans le cadre que l'apprenant a choisi en lançant la
    session (``settings`` : mode, matière, précision). Sans lui, elle commentait le
    profil entier, y compris des matières absentes de la session. Seule l'analyse
    dépend du LLM : s'il échoue, le reste du bilan est rendu quand même.

    Avec ``session_id``, le bilan est gardé avec la séance : « Ma progression » le
    relit tel quel, sans jamais le régénérer.
    """
    history = [entry for entry in (answers_history or []) if isinstance(entry, dict)]
    result = {"analysis": "", "weak_subjects": [], "courses_to_review": []}
    if not history:
        return result

    scope = _session_scope(settings, len(history))
    courses = _courses_to_review(history)
    result["weak_subjects"] = _weak_subjects(history)
    result["courses_to_review"] = courses
    context = {
        "session": scope,
        "answers_history": [_history_for_prompt(entry) for entry in history],
        "courses_to_review": [
            {key: course[key] for key in ("title", "chapters", "answered", "missed")}
            for course in courses
        ],
        "subject_profiles": _session_profiles(user_id, scope, history),
    }
    try:
        analysis = run_llm_sync(
            lambda ok, err: generate_quiz_session_analysis_async(context, ok, err),
        )
    except Exception as exc:  # pragma: no cover - dégradation best-effort
        logger.warning("Analyse de session de quiz échouée : %s", exc)
        analysis = None
    if isinstance(analysis, dict):
        result["analysis"] = str(analysis.get("analysis") or "").strip()
    _keep_analysis(session_id, result)
    return result


def _keep_analysis(session_id: int | None, result: dict) -> None:
    """Garde le bilan avec sa séance (best-effort). Une analyse vide — LLM absent —
    n'efface pas celle qu'une première demande aurait déjà obtenue."""
    if session_id is None:
        return
    try:
        session = get_practice_session(int(session_id))
        if session is None or session.get("kind") != "quiz":
            return
        update_practice_details(
            int(session_id),
            analysis=result["analysis"] or None,
            details={key: result[key] for key in ("weak_subjects", "courses_to_review")},
        )
    except Exception:  # pragma: no cover - le bilan affiché prime sur sa trace
        logger.debug("Bilan de quiz non gardé avec la séance", exc_info=True)


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


def _weights(items: list[dict], terms: list[str], user_id: int) -> list[float]:
    """Poids de tirage d'un vivier de questions. Quatre facteurs multiplicatifs.

    - **pertinence** ``1 + termes distincts trouvés`` : avec un sujet libre, une
      question qui touche trois mots de la requête pèse le double d'une qui n'en
      touche qu'un. Sans sujet, facteur neutre.
    - **échec** ``QUIZ_FAILED_BONUS`` si la question a déjà été ratée en lecture :
      la répétition espacée garde la priorité, MALGRÉ l'amortissement ci-dessous.
    - **amortissement** : une question servie récemment retombe à
      ``QUIZ_EXPOSURE_FLOOR`` et remonte en ``QUIZ_EXPOSURE_HALF_LIFE_DAYS``.
      C'est ce qui différencie deux sessions d'affilée. Jamais nul : rien n'est
      définitivement verrouillé.
    - **fraîcheur** : le cours de la semaine garde un avantage, borné par
      ``QUIZ_FRESHNESS_FLOOR``. Sans ce plancher, le matériel neuf écrase l'ancien
      et le stock ne tourne jamais — le défaut d'origine, en plus doux.
    """
    ids = [q.get("id") for q in items]
    try:
        exposures = get_exposures(user_id, ids)
    except Exception:  # pragma: no cover - une table absente ne casse pas un quiz
        logger.debug("Lecture des expositions de quiz ignorée", exc_info=True)
        exposures = {}

    weights: list[float] = []
    for q in items:
        weight = 1.0 + float(q.get("_topic_hits") or 0)
        if q.get("failed"):
            weight *= QUIZ_FAILED_BONUS
        seen = exposures.get(q.get("id"))
        weight *= selection.cooldown(
            seen.get("last_served_at") if seen else None,
            QUIZ_EXPOSURE_HALF_LIFE_DAYS,
            QUIZ_EXPOSURE_FLOOR,
        )
        # Le catalogue statique n'a pas de date de création : il est intemporel,
        # donc ni avantagé ni pénalisé (facteur plein).
        created = q.get("created_at")
        if created:
            fresh = selection.decay(
                selection.age_days(created), QUIZ_FRESHNESS_HALF_LIFE_DAYS,
            )
            weight *= max(QUIZ_FRESHNESS_FLOOR, fresh)
        weights.append(weight)
    return weights


def _pick(items: list[dict], terms: list[str], count: int, user_id: int) -> list[dict]:
    """``count`` questions tirées dans le vivier, pondérées par :func:`_weights`."""
    if count <= 0 or not items:
        return []
    return selection.weighted_sample(items, _weights(items, terms, user_id), count)


def _weighted_order(items: list[dict], terms: list[str], user_id: int) -> list[dict]:
    """Vivier réordonné par tirage pondéré, sans le tronquer.

    La pratique entrelacée a besoin de TOUS les candidats (elle les répartit
    ensuite par domaine), mais dans un ordre qui tienne compte de ce qui a déjà
    été servi — d'où un tirage de longueur totale plutôt qu'un `sort`.
    """
    return selection.weighted_sample(items, _weights(items, terms, user_id), len(items))


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
    distinct, _total = selection.relevance(haystack, terms)
    return distinct


def _rank_by_topic(items: list[dict], terms: list[str]) -> list[dict]:
    """Filtre le vivier sur le sujet libre et note la pertinence de chaque question.

    Ne classe plus : le nombre de termes distincts est rangé dans ``_topic_hits``,
    que :func:`_weights` transforme en poids de tirage. Trier ici puis prendre la
    tête revenait à rendre la même session à chaque fois — une question très
    pertinente restait indéfiniment devant ses quasi-égales.

    Sans sujet, la liste passe telle quelle (poids de pertinence neutre).
    """
    if not terms:
        return list(items)
    kept: list[dict] = []
    for q in items:
        hits = _topic_hits(q, terms)
        if hits:
            q["_topic_hits"] = hits
            kept.append(q)
    return kept


def _interleave_by_category(items: list[dict], count: int) -> list[dict]:
    """``count`` questions tirées à tour de rôle dans chaque domaine disponible.

    C'est la pratique entrelacée : deux questions voisines viennent de domaines
    différents tant qu'il reste des domaines à servir. Prendre les ``count``
    premières d'une liste mélangée ne suffirait pas — un domaine bien fourni
    raflerait la session par la seule loi des grands nombres.

    L'ordre des paquets est mélangé pour qu'un même domaine n'ouvre pas toutes
    les sessions. À l'intérieur d'un paquet, l'ordre reçu est conservé : comme
    l'appelant concatène les questions de lecture avant le catalogue statique,
    le matériel de l'apprenant passe en premier et le catalogue ne sert qu'à
    garantir la diversité.
    """
    buckets: dict[str, list[dict]] = {}
    for q in items:
        buckets.setdefault(q.get("category") or "culture", []).append(q)

    order = list(buckets)
    random.shuffle(order)

    picked: list[dict] = []
    while len(picked) < count:
        drained = True
        for category in order:
            bucket = buckets[category]
            if not bucket:
                continue
            picked.append(bucket.pop(0))
            drained = False
            if len(picked) >= count:
                break
        if drained:  # tous les domaines épuisés avant `count`
            break
    return picked


# Champs de l'historique transmis au prompt d'analyse. Le score brut (0.0 / 0.5 /
# 1.0) n'y est pas : le verdict dit la même chose, et le LLM recopiait « (score de
# 0.0) » tel quel dans le texte destiné à l'apprenant.
_PROMPT_HISTORY_FIELDS = (
    "question", "user_answer", "verdict", "category", "source", "document", "chapter_title",
)


def _entry_score(entry: dict) -> float:
    """Poids d'une réponse de l'historique : le verdict fait foi, le score est un repli."""
    verdict = str(entry.get("verdict") or "").strip().lower()
    if verdict in VERDICT_SCORES:
        return VERDICT_SCORES[verdict]
    try:
        return max(0.0, min(1.0, float(entry.get("score"))))
    except (TypeError, ValueError):
        return 0.0


def _session_scope(settings: dict | None, answered: int) -> dict:
    """Réglages choisis au lancement de la session, normalisés pour le prompt.

    Même exclusivité que :func:`build_quiz` : le multi-apprentissage n'a ni
    matière ni précision, quoi que le client envoie."""
    settings = settings if isinstance(settings, dict) else {}
    interleaved = settings.get("mode") == "multi"
    subject = "" if interleaved else str(settings.get("subject") or "").strip()
    topic = "" if interleaved else str(settings.get("topic") or "").strip()
    return {
        "mode": "multi" if interleaved else "subject",
        "subject": subject or None,
        "topic": topic or None,
        "answered": answered,
    }


def _history_for_prompt(entry: dict) -> dict:
    return {key: entry.get(key) for key in _PROMPT_HISTORY_FIELDS}


def _session_profiles(user_id: int, scope: dict, history: list[dict]) -> list[dict]:
    """Niveaux de maîtrise des SEULES matières de la session.

    Tout le profil partait au prompt : l'analyse d'un quiz d'informatique finissait
    sur « d'autres domaines où les données sont limitées »."""
    wanted = {str(entry.get("category") or "").strip().lower() for entry in history}
    if scope.get("subject"):
        wanted.add(scope["subject"].lower())
    wanted.discard("")
    return [
        {key: row.get(key) for key in ("subject", "level", "questions_count", "correct_count")}
        for row in get_all_subjects(user_id)
        if str(row.get("subject") or "").strip().lower() in wanted
    ]


def _weak_subjects(history: list[dict]) -> list[str]:
    """Matières où au moins une réponse n'est pas juste, la plus faible d'abord."""
    scores: dict[str, list[float]] = {}
    for entry in history:
        category = str(entry.get("category") or "").strip()
        if category:
            scores.setdefault(category, []).append(_entry_score(entry))
    weak = [(sum(s) / len(s), category) for category, s in scores.items() if min(s) < 1.0]
    return [category for _average, category in sorted(weak)]


def _courses_to_review(history: list[dict]) -> list[dict]:
    """Documents de la bibliothèque à relire, d'après les questions manquées.

    Seules les questions de LECTURE ont un cours derrière elles : celles du
    catalogue statique n'en ont pas, et ne produisent donc aucune carte. Chaque
    document est relu en base — un ``document_id`` envoyé par le client mais
    supprimé depuis (ou forgé) n'ouvrirait rien —, et c'est son titre ACTUEL qui
    s'affiche, renommage compris. Le plus faible score moyen passe en premier.
    """
    groups: dict[int, dict] = {}
    for entry in history:
        doc_id = entry.get("document_id")
        if entry.get("source") != "reading" or not isinstance(doc_id, int) or isinstance(doc_id, bool):
            continue
        group = groups.setdefault(doc_id, {"answered": 0, "points": 0.0, "missed": 0, "chapters": []})
        score = _entry_score(entry)
        group["answered"] += 1
        group["points"] += score
        if score < 1.0:
            group["missed"] += 1
            chapter = str(entry.get("chapter_title") or "").strip()
            if chapter and chapter not in group["chapters"]:
                group["chapters"].append(chapter)

    ranked: list[tuple[float, int, dict]] = []
    for doc_id, group in groups.items():
        if not group["missed"]:
            continue
        doc = get_document(doc_id)
        if not doc:
            continue
        ranked.append((group["points"] / group["answered"], -group["missed"], {
            "document_id": doc_id,
            "title": doc.get("filename") or "",
            "subject": doc.get("subject") or "",
            "chapters": group["chapters"],
            "answered": group["answered"],
            "missed": group["missed"],
        }))
    ranked.sort(key=lambda item: item[:2])
    return [course for _average, _missed, course in ranked[:QUIZ_REVIEW_MAX_COURSES]]


def _evaluation(
    verdict: str,
    expected_answer: str,
    *,
    feedback: str = "",
    hint: str = "",
    completion: str = "",
    graded: bool = True,
    signals: dict | None = None,
) -> dict:
    """Résultat de correction, tel que l'UI du quiz l'attend. ``signals`` : ceux
    du LLM, absents d'un verdict objectif (QCM, remise en ordre, case vide)."""
    return {
        "verdict": verdict,
        "score": VERDICT_SCORES.get(verdict, 0.0),
        "feedback": feedback,
        "hint": hint,
        "completion": completion,
        "expected_answer": expected_answer,
        "graded": bool(graded and verdict in VERDICTS),
        "signals": signals,
    }


def _clean_signals(raw) -> dict | None:
    """Signaux d'une évaluation, ramenés à ce que le moteur de jauges sait lire.

    Ils font l'aller-retour par le navigateur (correction pendant la séance,
    enregistrement à la fin) : on n'en garde que les clés connues, bornées.
    Sans `metacog_signals`, rien — la réponse est alors mesurée par son verdict."""
    if not isinstance(raw, dict) or not isinstance(raw.get("metacog_signals"), dict):
        return None
    metacog: dict[str, float] = {}
    for criterion, value in raw["metacog_signals"].items():
        if criterion not in CRITERIA or isinstance(value, bool):
            continue
        try:
            metacog[criterion] = max(-2.0, min(2.0, float(value)))
        except (TypeError, ValueError):
            continue
    curiosity = raw.get("curiosity_signals")
    creativity = raw.get("creativity_signals")
    clean_creativity: dict = {}
    if isinstance(creativity, dict):
        for key, value in creativity.items():
            if key == "depth_of_reflection":
                try:
                    clean_creativity[key] = max(0.0, min(1.0, float(value)))
                except (TypeError, ValueError):
                    continue
            else:
                clean_creativity[str(key)] = bool(value)
    return {
        "metacog_signals": metacog,
        "curiosity_signals": (
            {str(k): bool(v) for k, v in curiosity.items()} if isinstance(curiosity, dict) else {}
        ),
        "creativity_signals": clean_creativity,
    }


def _clean_answer(entry: dict, index: int) -> dict | None:
    """Une réponse de séance, telle qu'on la garde. Sans verdict, pas de réponse :
    une question laissée en plan n'est pas une mesure."""
    verdict = str(entry.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        return None
    document_id = entry.get("document_id")
    if not isinstance(document_id, int) or isinstance(document_id, bool) or not get_document(document_id):
        # Un document supprimé depuis (ou forgé) ne se relie à rien.
        document_id = None
    try:
        response_ms = max(0, min(_MAX_RESPONSE_MS, int(entry.get("response_time_ms"))))
    except (TypeError, ValueError):
        response_ms = None
    question_id = entry.get("question_id")
    source = str(entry.get("source") or "").strip().lower()
    return {
        "position": index,
        "question_id": question_id if isinstance(question_id, int) and not isinstance(question_id, bool) else None,
        "question": str(entry.get("question") or "")[:_MAX_ANSWER_CHARS],
        "question_type": _question_type(entry),
        "category": (str(entry.get("category") or "").strip() or None),
        "source": source if source in ("reading", "static") else "reading",
        "document_id": document_id,
        "chapter_title": (str(entry.get("chapter_title") or "").strip() or None),
        "user_answer": str(entry.get("user_answer") or "")[:_MAX_ANSWER_CHARS],
        "verdict": verdict,
        "graded": bool(entry.get("graded", True)),
        "response_time_ms": response_ms,
        "signals": _clean_signals(entry.get("signals")),
    }


def _quiz_measures(answers: list[dict]) -> list[dict]:
    """Chaque réponse est une mesure ; l'axe de la courbe est le numéro de question.

    Corrigée par le LLM (signaux à l'appui), elle suit le modèle du lecteur, la
    forme de la réponse comprise (`augment_evaluation_with_response_signals`) ;
    jugée par son seul verdict (QCM, remise en ordre, auto-évaluation, « je ne
    sais pas »), elle tire vers sa cible les jauges que vise son type."""
    measures = []
    for answer in answers:
        qtype = answer.get("question_type") or "open"
        measure = {
            "t": float(int(answer.get("position", len(measures))) + 1),
            "verdict": answer["verdict"],
            "question_type": qtype,
            "targets": QUESTION_TYPE_TARGET_GAUGES.get(qtype, ()),
            "response_time_ms": answer.get("response_time_ms"),
        }
        if answer.get("signals"):
            measure["evaluation"] = augment_evaluation_with_response_signals(
                {**answer["signals"], "verdict": answer["verdict"]}, answer.get("user_answer") or "",
            )
        measures.append(measure)
    return measures


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
