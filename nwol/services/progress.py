# services/progress.py — « Ma progression » : le portrait longitudinal de l'apprenant.
#
# La base tient depuis longtemps tout ce qu'il faut pour montrer à quelqu'un
# comment il a lu — `metacog_history` (6 critères × chaque session),
# `session_gauges` (les courbes intra-session), `session_reflections` (ses
# propres mots), `page_dwell` (où il a ralenti) — et AUCUN routeur ne l'exposait.
# L'utilisateur ne voyait qu'un radar.
#
# Trois catégories de séances y figurent : la LECTURE (`reading_sessions`), le
# QUIZ et la LANGUE (`practice_sessions`). Elles ont chacune leurs particularités
# (où l'on a ralenti ; les réponses données ; ce qui a été gagné dans la langue)
# et un point commun : la courbe des jauges pendant la séance, et ce qu'elle a
# déplacé dans le profil.
#
# Ce module est la couche métier de cette exposition. Il n'invente aucune donnée
# et ne recalcule rien que `services/stats.py` calcule déjà : le radar, les
# tendances et les recommandations restent chez lui (`get_metacog_overview` est
# la source du profil courant). Ici on assemble l'HISTORIQUE, session par session.
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from db.documents import get_document
from db.flashcards import get_due_flashcards
from db.metacog import CRITERIA, ensure_profile, get_history
from db.page_dwell import get_page_dwell
from db.practice_sessions import (
    count_practice_sessions,
    get_practice_session,
    get_quiz_answers,
    list_practice_sessions,
)
from db.session_gauges import PRACTICE, READING, get_first_gauges, get_session_gauges
from db.session_pauses import get_session_pauses
from db.session_reflections import get_session_reflections
from db.sessions import count_sessions, get_session, list_sessions, reading_ranks
from db.user import DEFAULT_USER_ID
from services.session import session_metrics

logger = logging.getLogger("services.progress")

__all__ = [
    "KINDS",
    "list_progress_sessions",
    "get_session_progress",
    "get_practice_progress",
    "get_weekly_recap",
]

# Les catégories de « Ma progression », dans l'ordre de leurs onglets.
KINDS: tuple[str, ...] = ("reading", "quiz", "lang")

# Une timeline n'a pas vocation à tout remonter d'un bloc : au-delà, l'écran
# devient un mur et la réponse pèse pour rien.
DEFAULT_TIMELINE_LIMIT = 40
MAX_TIMELINE_LIMIT = 200

# En deçà, un critère n'a pas bougé : `update_profile` écrit une ligne d'historique
# pour les six critères, y compris ceux que la séance n'a pas mesurés (avant =
# après). Les compter disait « 6 critères déplacés » quand un seul l'était.
_MOVE_EPSILON = 0.05

# Le rapport hebdomadaire est LE BATTEMENT DE CŒUR de l'abonnement : c'est
# l'objet qui revient à intervalle fixe et qui justifie le prélèvement. Sept
# jours, pas « depuis toujours » — un bilan sans rythme n'est pas un rendez-vous.
WEEK_DAYS = 7
# Trois cartes, pas la pile entière : un rapport qui se termine par 40 révisions
# à faire n'est plus un bilan, c'est une dette.
RECAP_CARDS = 3
# Au-delà d'une semaine, une session ne peut pas entrer dans le bilan : on ne
# remonte donc jamais plus que ce que sept jours peuvent contenir.
RECAP_SESSION_POOL = 60


def list_progress_sessions(
    user_id: int = DEFAULT_USER_ID,
    limit: int = DEFAULT_TIMELINE_LIMIT,
    kind: str | None = None,
) -> dict:
    """Timeline des séances : une ligne par séance, du plus récent au plus ancien.

    Toutes catégories mêlées, ou une seule (`kind` ∈ `KINDS`). Chaque ligne dit sa
    catégorie (`kind`) et porte de quoi dessiner la frise SANS un appel par
    séance : ce qui la nomme (document lu, matière du quiz, langue), la durée, et
    le mouvement du profil. Le détail — courbes, réponses, réflexions — reste
    derrière `get_session_progress` / `get_practice_progress`.

    `session_id` n'est unique qu'au sein d'une famille : une lecture et un quiz
    peuvent porter le même. La clé d'une ligne est donc (`kind`, `session_id`)."""
    limit = max(1, min(int(limit or DEFAULT_TIMELINE_LIMIT), MAX_TIMELINE_LIMIT))
    kind = kind if kind in KINDS else None

    items: list[dict] = []
    if kind in (None, "reading"):
        items += _reading_rows(user_id, limit)
    if kind in (None, "quiz", "lang"):
        items += _practice_rows(user_id, limit, kind)
    # Les deux tables datent leurs séances avec la même horloge (SQLite,
    # `datetime('now')`) : l'ordre chronologique se lit sur la chaîne.
    items.sort(key=lambda row: (row["started_at"], row["session_id"]), reverse=True)
    items = items[:limit]
    return {
        "sessions": items,
        "total": len(items),
        "counts": _counts(user_id),
        "criteria": list(CRITERIA),
    }


def get_session_progress(session_id: int, user_id: int = DEFAULT_USER_ID) -> dict | None:
    """Détail d'une LECTURE : métriques, courbes de jauges, mouvements, réflexions.

    Renvoie `None` si la session n'existe pas — le routeur en fait un 404.

    Les trois blocs répondent à trois questions différentes, et c'est le
    troisième qui crée l'attachement : « qu'ai-je écrit ce jour-là ». C'est la
    seule chose ici qu'aucun autre outil ne peut restituer."""
    session = get_session(session_id)
    if session is None:
        return None

    document = _safe(lambda: get_document(session.get("document_id")), None) or {}
    changes = _history_by(user_id).get(int(session_id), [])
    return {
        "kind": "reading",
        "session_id": int(session_id),
        "document": {
            "id": document.get("id"),
            "title": _document_title(document),
            "subject": document.get("subject") or "",
        },
        "reading_index": _safe(lambda: reading_ranks(user_id), {}).get(int(session_id), 0),
        "started_at": session.get("started_at") or "",
        "ended_at": session.get("ended_at") or "",
        "completed": bool(session.get("ended_at")),
        "metrics": _safe(lambda: session_metrics(int(session_id)), {}),
        "gauges": _gauge_series(int(session_id), READING, axis="time"),
        "profile_changes": changes,
        # Les mots de l'apprenant, relus TELS QUELS. Ni résumés, ni reformulés.
        "reflections": _reflections(int(session_id)),
        "page_dwell": _safe(lambda: get_page_dwell(int(session_id)), []),
        # Les pauses prises, chacune avec ce qui l'a précédée (conseil de Clikoda
        # accepté, recommandation récente, ou rien) — cf. services/pause.
        "pauses": _safe(lambda: get_session_pauses(int(session_id)), []),
    }


def get_practice_progress(session_id: int, user_id: int = DEFAULT_USER_ID) -> dict | None:
    """Détail d'une séance de QUIZ ou de LANGUE. `None` si elle n'existe pas.

    Le tronc est celui d'une lecture — courbe de jauges, mouvements du profil,
    réflexions, analyse de Clikoda —, la particularité de chaque catégorie vit
    dans sa propre clé : `quiz` (réglages, réponses, matières, cours à revoir) ou
    `lang` (langue, épisode ou thème, ce qui a été gagné, signaux)."""
    session = get_practice_session(session_id)
    if session is None:
        return None
    sid = int(session_id)
    kind = session.get("kind")
    settings = session.get("settings") or {}
    details = session.get("details") or {}
    detail = {
        "kind": kind,
        "session_id": sid,
        "started_at": session.get("started_at") or "",
        "ended_at": session.get("ended_at") or "",
        "completed": bool(session.get("ended_at")),
        "profile_changes": _history_by(user_id, practice=True).get(sid, []),
        "reflections": _reflections(sid, practice=True),
        # Ce que Clikoda a écrit à la fin de la séance — relu, jamais régénéré.
        "analysis": str(session.get("analysis") or ""),
    }
    duration = int(session.get("duration_s") or 0)
    if kind == "quiz":
        answers = _safe(lambda: get_quiz_answers(sid), [])
        from services.quiz import quiz_metrics

        detail["metrics"] = quiz_metrics(answers, duration)
        detail["gauges"] = _gauge_series(sid, PRACTICE, axis="question")
        detail["quiz"] = {
            "mode": settings.get("mode") or "subject",
            "subject": settings.get("subject"),
            "topic": settings.get("topic"),
            "answers": [_answer_view(answer) for answer in answers],
            "by_category": _by_category(answers),
            "courses_to_review": details.get("courses_to_review") or [],
            "weak_subjects": details.get("weak_subjects") or [],
        }
        return detail

    flow = settings.get("flow") or "feuilleton"
    signals = details.get("signals") or {}
    exercises = details.get("exercises") or []
    scored = [e["score"] for e in exercises if isinstance(e.get("score"), (int, float))]
    detail["metrics"] = {
        "duration_s": duration,
        # Feuilleton : items de jeux répondus ; leçon : exercices notés.
        "answered": int(signals.get("answered") or 0) if flow == "feuilleton" else len(scored),
    }
    # Une leçon se lit exercice par exercice ; un épisode, au fil de son temps effectif.
    detail["gauges"] = _gauge_series(sid, PRACTICE, axis="exercise" if flow == "lecons" else "time")
    detail["lang"] = {
        **_language_view(settings.get("language")),
        "flow": flow,
        "mode": settings.get("mode"),
        "theme": settings.get("theme") or "",
        "level": settings.get("level") or "",
        "episode": details.get("episode"),
        "point": details.get("point"),
        "new_words": details.get("new_words") or [],
        "cards_created": int(details.get("cards_created") or 0),
        "acquired_today": int(details.get("acquired_today") or 0),
        "units_acquired_today": int(details.get("units_acquired_today") or 0),
        "words_seen": details.get("words_seen"),
        "words_acquired": details.get("words_acquired"),
        "signals": {
            key: signals.get(key)
            for key in ("understood", "reveal_rate", "games_rate", "second_wave_rate", "answered")
        },
        "exercises": exercises,
    }
    return detail


# ── Lignes de la frise ────────────────────────────────────────────────────────

def _reading_rows(user_id: int, limit: int) -> list[dict]:
    sessions = list_sessions(user_id, limit=limit)
    moves = _history_by(user_id)
    titles = _titles_for(sessions)
    ranks = _safe(lambda: reading_ranks(user_id), {})
    rows: list[dict] = []
    for session in sessions:
        sid = int(session["id"])
        changes = moves.get(sid, [])
        rows.append({
            "kind": "reading",
            "session_id": sid,
            "document_id": session.get("document_id"),
            "document_title": titles.get(session.get("document_id"), ""),
            # « Lecture n » de ce document — le nom de la session dans la frise,
            # avec le titre. 0 quand la session n'a pas de document.
            "reading_index": ranks.get(sid, 0),
            "started_at": session.get("started_at") or "",
            "ended_at": session.get("ended_at") or "",
            "duration_s": int(session.get("duration_s") or 0),
            "pages_read": int(session.get("pages_read") or 0),
            # Une session ouverte (jamais close) n'a ni durée ni score : la
            # timeline le dit plutôt que d'afficher des zéros trompeurs.
            "completed": bool(session.get("ended_at")),
            **_movement(changes),
            "has_reflections": bool(_safe(lambda: get_session_reflections(sid), [])),
        })
    return rows


def _practice_rows(user_id: int, limit: int, kind: str | None) -> list[dict]:
    sessions = _safe(lambda: list_practice_sessions(user_id, kind=kind, limit=limit), [])
    moves = _history_by(user_id, practice=True)
    rows: list[dict] = []
    for session in sessions:
        sid = int(session["id"])
        settings = session.get("settings") or {}
        details = session.get("details") or {}
        row = {
            "kind": session.get("kind"),
            "session_id": sid,
            "started_at": session.get("started_at") or "",
            "ended_at": session.get("ended_at") or "",
            "duration_s": int(session.get("duration_s") or 0),
            "completed": bool(session.get("ended_at")),
            **_movement(moves.get(sid, [])),
            "has_reflections": bool(_safe(lambda: get_session_reflections(sid, practice=True), [])),
        }
        if session.get("kind") == "quiz":
            answers = _safe(lambda: get_quiz_answers(sid), [])
            from services.quiz import quiz_metrics

            metrics = quiz_metrics(answers)
            row["quiz"] = {
                "mode": settings.get("mode") or "subject",
                "subject": settings.get("subject"),
                "topic": settings.get("topic"),
                "questions_answered": metrics["questions_answered"],
                "success_rate": metrics["success_rate"],
            }
        else:
            row["lang"] = {
                **_language_view(settings.get("language")),
                "flow": settings.get("flow") or "feuilleton",
                "mode": settings.get("mode"),
                "theme": settings.get("theme") or "",
                "episode": details.get("episode"),
            }
        rows.append(row)
    return rows


def _movement(changes: list[dict]) -> dict:
    """Ce qu'une séance a déplacé, résumé pour la frise. Seuls comptent les
    critères qui ont réellement bougé."""
    moved = [c for c in changes if abs(c["delta"]) >= _MOVE_EPSILON]
    return {
        "criteria_moved": len(moved),
        "profile_delta": round(sum(c["delta"] for c in changes), 2),
    }


def _counts(user_id: int) -> dict[str, int]:
    """Effectif de chaque catégorie, toutes séances confondues (onglets)."""
    counts = {kind: 0 for kind in KINDS}
    counts["reading"] = _safe(lambda: count_sessions(user_id), 0)
    for kind, n in _safe(lambda: count_practice_sessions(user_id), {}).items():
        if kind in counts:
            counts[kind] = int(n)
    return counts


# ── Briques communes du détail ────────────────────────────────────────────────

def _gauge_series(session_id: int, scope: str = READING, axis: str = "time") -> dict:
    """Courbes intra-session, une série par jauge, plus son amorce.

    L'amorce (profil × 0,8, cf. `services/session.LiveGauges.attach_session` et
    `services/practice.start`) est remontée à part : une jauge restée dessus n'a
    rien mesuré, et la lire comme un « net retrait » est exactement l'erreur que
    `_measured_gauges` évite déjà côté finalisation. L'écran doit pouvoir faire
    la même distinction.

    `axis` dit ce que porte `t` : des secondes (`time` — lecture, épisode de
    langue), un numéro de question (`question`) ou d'exercice (`exercise`)."""
    seed = _safe(lambda: get_first_gauges(session_id, scope=scope), {})
    rows = _safe(lambda: get_session_gauges(session_id, scope=scope), [])
    series: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        name = row.get("gauge_name")
        if not name:
            continue
        series[name].append({"t": round(float(row.get("t") or 0.0), 2),
                             "value": round(float(row.get("value") or 0.0), 2)})
    return {
        "axis": axis,
        "seed": {k: round(float(v), 2) for k, v in seed.items()},
        "series": {name: points for name, points in series.items()},
        "measured": sorted(
            name for name, points in series.items()
            if points and abs(points[-1]["value"] - seed.get(name, points[-1]["value"])) > 1e-9
        ),
    }


def _history_by(user_id: int, practice: bool = False) -> dict[int, list[dict]]:
    """`metacog_history` regroupé par séance : ce que la séance a déplacé.

    `value_before` → `value_after` est déjà stocké par critère à chaque
    finalisation — il n'y a rien à recalculer, seulement à regrouper. Une ligne
    appartient à une lecture (`session_id`) ou à une séance de pratique
    (`practice_session_id`, avec `practice=True`)."""
    column = "practice_session_id" if practice else "session_id"
    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in _safe(lambda: get_history(user_id), []):
        sid = row.get(column)
        if sid is None:
            continue
        before = float(row.get("value_before", 50.0))
        after = float(row.get("value_after", 50.0))
        grouped[int(sid)].append({
            "criterion": row.get("criterion"),
            "before": round(before, 2),
            "after": round(after, 2),
            "delta": round(after - before, 2),
            "recorded_at": row.get("recorded_at") or "",
        })
    return grouped


def _reflections(session_id: int, practice: bool = False) -> list[dict]:
    return [
        {
            "question": r.get("question_text") or "",
            "answer": r.get("answer_text") or "",
            "created_at": r.get("created_at") or "",
        }
        for r in _safe(lambda: get_session_reflections(session_id, practice=practice), [])
    ]


def _answer_view(answer: dict) -> dict:
    """Une réponse de quiz telle que la séance l'a jouée. Le titre du cours est
    relu en base : renommé depuis, c'est le titre actuel qui s'affiche."""
    document_id = answer.get("document_id")
    document = _safe(lambda: get_document(document_id), None) if document_id else None
    return {
        "position": int(answer.get("position") or 0),
        "question": answer.get("question") or "",
        "question_type": answer.get("question_type") or "",
        "category": answer.get("category") or "",
        "source": answer.get("source") or "",
        "user_answer": answer.get("user_answer") or "",
        "verdict": answer.get("verdict") or "",
        "graded": bool(answer.get("graded")),
        "response_time_ms": answer.get("response_time_ms"),
        "document_id": document_id if document else None,
        "document_title": _document_title(document or {}),
        "chapter_title": answer.get("chapter_title") or "",
    }


def _by_category(answers: list[dict]) -> list[dict]:
    """Points par matière, dans l'ordre où les matières sont apparues. Un
    « partiel » vaut un demi-point, comme dans le bilan de fin de quiz."""
    from services.quiz import VERDICT_SCORES

    totals: dict[str, dict] = {}
    for answer in answers:
        category = answer.get("category") or ""
        entry = totals.setdefault(category, {"category": category, "points": 0.0, "total": 0})
        entry["points"] += VERDICT_SCORES.get(answer.get("verdict"), 0.0)
        entry["total"] += 1
    return list(totals.values())


def _language_view(code: str | None) -> dict:
    """Libellé et drapeau d'une langue, tels que la page Langues les affiche."""
    from services.lang import LANGUAGES

    entry = next((lang for lang in LANGUAGES if lang["code"] == code), None)
    return {
        "language": code or "",
        "language_label": (entry or {}).get("label") or (code or "").capitalize(),
        "flag": (entry or {}).get("flag") or "",
    }


def _document_title(document: dict) -> str:
    """Le titre d'un document EST son `filename` (renommable, cf. `rename_document`) :
    la ligne `documents` n'a pas de colonne `title`, c'est `services/library._summary`
    qui l'expose sous ce nom. Lire `title` ici rendait toujours une chaîne
    vide — et la frise affichait le même libellé générique pour chaque
    session."""
    return document.get("filename") or ""


def _titles_for(sessions: list[dict]) -> dict[int, str]:
    """Titres des documents lus, une lecture par document et non par session."""
    titles: dict[int, str] = {}
    for session in sessions:
        doc_id = session.get("document_id")
        if doc_id is None or doc_id in titles:
            continue
        document = _safe(lambda: get_document(doc_id), None) or {}
        titles[doc_id] = _document_title(document)
    return titles


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        logger.debug("Lecture de progression ignorée", exc_info=True)
        return default


def get_weekly_recap(user_id: int = DEFAULT_USER_ID) -> dict:
    """Bilan des sept derniers jours.

    Quatre éléments, dans cet ordre, parce que c'est l'ordre dans lequel on veut
    les lire : ce que j'ai fait, ce qui a bougé, ce que Clikoda a remarqué, ce qu'il
    me reste à revoir.

    Les trois catégories comptent : un quiz ou une séance de langue fait bouger le
    profil comme une lecture, et une semaine de quiz qui annonçait « rien à
    raconter » au-dessus de critères déplacés se contredisait. Pages et documents
    restent ceux de la lecture.

    Rien n'est calculé ici qui ne le soit déjà ailleurs : les métriques viennent
    de `list_progress_sessions`, l'analyse de `metacog_profile.general_analysis`
    (écrite à chaque finalisation par `services/session._update_general_analysis`)
    et les cartes de `db/flashcards.get_due_flashcards`. C'est du câblage, et
    c'est voulu — un second calcul serait un second modèle de l'apprenant."""
    since = datetime.now() - timedelta(days=WEEK_DAYS)
    timeline = list_progress_sessions(user_id, limit=RECAP_SESSION_POOL)
    recent = [
        row for row in timeline["sessions"]
        if row["completed"] and _after(row["started_at"], since)
    ]

    documents: list[str] = []
    for row in recent:
        title = row.get("document_title")
        if title and title not in documents:
            documents.append(title)

    profile = _safe(lambda: ensure_profile(user_id), {}) or {}
    cards = _safe(lambda: get_due_flashcards(user_id=user_id, limit=RECAP_CARDS), [])
    return {
        "since": since.date().isoformat(),
        "sessions": len(recent),
        "by_kind": {kind: sum(1 for row in recent if row["kind"] == kind) for kind in KINDS},
        "duration_s": sum(row["duration_s"] for row in recent),
        "pages_read": sum(row.get("pages_read", 0) for row in recent),
        "documents": documents,
        "movers": _top_movers(user_id, since),
        # Ce que Clikoda a remarqué — le texte qu'elle réécrit à chaque
        # finalisation, jamais régénéré pour ce bilan.
        "analysis": str(profile.get("general_analysis") or ""),
        "analysis_updated_at": str(profile.get("general_analysis_updated_at") or ""),
        "cards": [
            {"id": card.get("id"), "front": card.get("front") or "", "back": card.get("back") or ""}
            for card in cards
        ],
    }


def _top_movers(user_id: int, since: datetime) -> list[dict]:
    """Critères ayant le plus bougé sur la période, du plus au moins déplacé.

    On somme les deltas SIGNÉS et non leurs valeurs absolues : trois hausses et
    trois baisses de même ampleur sur un critère décrivent une semaine agitée,
    pas une progression, et le bilan doit le dire ainsi."""
    totals: dict[str, float] = defaultdict(float)
    for row in _safe(lambda: get_history(user_id), []):
        if not _after(row.get("recorded_at") or "", since):
            continue
        criterion = row.get("criterion")
        if criterion not in CRITERIA:
            continue
        totals[criterion] += float(row.get("value_after", 0.0)) - float(row.get("value_before", 0.0))
    movers = [
        {"criterion": criterion, "delta": round(delta, 2)}
        for criterion, delta in totals.items()
        if abs(delta) >= 0.05
    ]
    movers.sort(key=lambda item: abs(item["delta"]), reverse=True)
    return movers[:3]


def _after(timestamp: str, since: datetime) -> bool:
    """Vrai si l'horodatage ISO est postérieur à `since`. Illisible -> exclu."""
    if not timestamp:
        return False
    try:
        return datetime.fromisoformat(str(timestamp).replace("Z", "")) >= since
    except ValueError:
        return False
