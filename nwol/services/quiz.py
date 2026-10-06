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
from db.documents import get_document
from db.questions import get_question
from db.quiz_exposures import get_exposures, record_exposures
from db.quiz_questions import (
    STATIC_ID_OFFSET,
    get_quiz_base_questions,
    get_quiz_subjects,
    get_static_quiz_questions,
)
from db.subjects import get_all_subjects, update_subject_from_answer
from db.user import DEFAULT_USER_ID
from services import selection
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
    jusqu'à ``n`` — sinon une base neuve, ou un thème sans document importé,
    n'aurait aucun quiz à jouer.

    **Dans tous les modes, on charge un VIVIER (`QUIZ_SEARCH_POOL`) puis on tire
    dedans** (:func:`_pick`). Prendre la tête d'une liste bornée par ``count``
    revenait à laisser le ``ORDER BY`` SQL choisir la session : deux quiz d'affilée
    sur la même matière rendaient exactement les mêmes questions, et le stock
    ancien n'était jamais rejoué. Les questions servies sont mémorisées
    (`db.quiz_exposures`) pour amortir leur retour au tour suivant.
    """
    count = clamp_quiz_length(n)
    if interleaved:
        # L'alternance se décide EN PYTHON, donc on charge un lot borné au lieu de
        # laisser le LIMIT SQL trancher avant. Le catalogue statique entre dans le
        # vivier — il couvre à lui seul plusieurs domaines, ce qui rend l'alternance
        # possible même quand un seul document a été importé.
        # Le tirage pondéré passe AVANT la répartition par domaine (sinon la même
        # tête de paquet ouvre toutes les sessions entrelacées) et sépare lecture
        # et catalogue : `_interleave_by_category` conserve l'ordre reçu à
        # l'intérieur d'un domaine, ce qui fait passer le matériel de l'apprenant
        # devant le catalogue de secours.
        pool = _weighted_order(
            get_quiz_base_questions(user_id, QUIZ_SEARCH_POOL, None, shuffle=True), [], user_id,
        ) + _weighted_order(get_static_quiz_questions(QUIZ_SEARCH_POOL), [], user_id)
        return _served(_assemble_quiz(_interleave_by_category(pool, count)), user_id)

    terms = _topic_terms(topic)
    base = _pick(
        _rank_by_topic(get_quiz_base_questions(user_id, QUIZ_SEARCH_POOL, subject), terms),
        terms, count, user_id,
    )
    if len(base) < count:
        missing = count - len(base)
        base.extend(_pick(
            _rank_by_topic(get_static_quiz_questions(QUIZ_SEARCH_POOL, subject), terms),
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


def analyze_session(
    answers_history: list[dict],
    user_id: int = DEFAULT_USER_ID,
    settings: dict | None = None,
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
        return result
    if isinstance(analysis, dict):
        result["analysis"] = str(analysis.get("analysis") or "").strip()
    return result


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
