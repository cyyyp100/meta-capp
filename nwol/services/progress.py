# services/progress.py — « Ma progression » : le portrait longitudinal de l'apprenant.
#
# La base tient depuis longtemps tout ce qu'il faut pour montrer à quelqu'un
# comment il a lu — `metacog_history` (6 critères × chaque session),
# `session_gauges` (les courbes intra-session), `session_reflections` (ses
# propres mots), `page_dwell` (où il a ralenti) — et AUCUN routeur ne l'exposait.
# L'utilisateur ne voyait qu'un radar.
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
from db.session_gauges import get_first_gauges, get_session_gauges
from db.session_reflections import get_session_reflections
from db.sessions import get_session, list_sessions
from db.user import DEFAULT_USER_ID
from services.session import session_metrics

logger = logging.getLogger("services.progress")

__all__ = ["list_progress_sessions", "get_session_progress", "get_weekly_recap"]

# Une timeline n'a pas vocation à tout remonter d'un bloc : au-delà, l'écran
# devient un mur et la réponse pèse pour rien.
DEFAULT_TIMELINE_LIMIT = 40
MAX_TIMELINE_LIMIT = 200

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
) -> dict:
    """Timeline des sessions : une ligne par séance, du plus récent au plus ancien.

    Chaque ligne porte de quoi dessiner la frise SANS un appel par session : le
    document lu, la durée, le score, et le mouvement du profil (somme des
    `value_after - value_before` de la session, tous critères confondus). Le
    détail — courbes, réflexions, dwell — reste derrière `get_session_progress`."""
    limit = max(1, min(int(limit or DEFAULT_TIMELINE_LIMIT), MAX_TIMELINE_LIMIT))
    sessions = list_sessions(user_id, limit=limit)
    moves = _history_by_session(user_id)
    titles = _titles_for(sessions)

    items: list[dict] = []
    for session in sessions:
        sid = int(session["id"])
        changes = moves.get(sid, [])
        items.append({
            "session_id": sid,
            "document_id": session.get("document_id"),
            "document_title": titles.get(session.get("document_id"), ""),
            "started_at": session.get("started_at") or "",
            "ended_at": session.get("ended_at") or "",
            "duration_s": int(session.get("duration_s") or 0),
            "pages_read": int(session.get("pages_read") or 0),
            # Une session ouverte (jamais close) n'a ni durée ni score : la
            # timeline le dit plutôt que d'afficher des zéros trompeurs.
            "completed": bool(session.get("ended_at")),
            "criteria_moved": len(changes),
            "profile_delta": round(sum(c["delta"] for c in changes), 2),
            "has_reflections": bool(_safe(lambda: get_session_reflections(sid), [])),
        })
    return {
        "sessions": items,
        "total": len(items),
        "criteria": list(CRITERIA),
    }


def get_session_progress(session_id: int, user_id: int = DEFAULT_USER_ID) -> dict | None:
    """Détail d'une session : métriques, courbes de jauges, mouvements, réflexions.

    Renvoie `None` si la session n'existe pas — le routeur en fait un 404.

    Les trois blocs répondent à trois questions différentes, et c'est le
    troisième qui crée l'attachement : « qu'ai-je écrit ce jour-là ». C'est la
    seule chose ici qu'aucun autre outil ne peut restituer."""
    session = get_session(session_id)
    if session is None:
        return None

    document = _safe(lambda: get_document(session.get("document_id")), None) or {}
    changes = _history_by_session(user_id).get(int(session_id), [])
    return {
        "session_id": int(session_id),
        "document": {
            "id": document.get("id"),
            "title": document.get("title") or "",
            "subject": document.get("subject") or "",
        },
        "started_at": session.get("started_at") or "",
        "ended_at": session.get("ended_at") or "",
        "completed": bool(session.get("ended_at")),
        "metrics": _safe(lambda: session_metrics(int(session_id)), {}),
        "gauges": _gauge_series(int(session_id)),
        "profile_changes": changes,
        # Les mots de l'apprenant, relus TELS QUELS. Ni résumés, ni reformulés.
        "reflections": [
            {
                "question": r.get("question_text") or "",
                "answer": r.get("answer_text") or "",
                "created_at": r.get("created_at") or "",
            }
            for r in _safe(lambda: get_session_reflections(int(session_id)), [])
        ],
        "page_dwell": _safe(lambda: get_page_dwell(int(session_id)), []),
    }


def _gauge_series(session_id: int) -> dict:
    """Courbes intra-session, une série par jauge, plus son amorce.

    L'amorce (profil × 0,8, cf. `services/session.LiveGauges.attach_session`) est
    remontée à part : une jauge restée dessus n'a rien mesuré, et la lire comme
    un « net retrait » est exactement l'erreur que `_measured_gauges` évite déjà
    côté finalisation. L'écran doit pouvoir faire la même distinction."""
    seed = _safe(lambda: get_first_gauges(session_id), {})
    rows = _safe(lambda: get_session_gauges(session_id), [])
    series: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        name = row.get("gauge_name")
        if not name:
            continue
        series[name].append({"t": round(float(row.get("t") or 0.0), 2),
                             "value": round(float(row.get("value") or 0.0), 2)})
    return {
        "seed": {k: round(float(v), 2) for k, v in seed.items()},
        "series": {name: points for name, points in series.items()},
        "measured": sorted(
            name for name, points in series.items()
            if points and abs(points[-1]["value"] - seed.get(name, points[-1]["value"])) > 1e-9
        ),
    }


def _history_by_session(user_id: int) -> dict[int, list[dict]]:
    """`metacog_history` regroupé par session : ce que la séance a déplacé.

    `value_before` → `value_after` est déjà stocké par critère à chaque
    finalisation — il n'y a rien à recalculer, seulement à regrouper."""
    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in _safe(lambda: get_history(user_id), []):
        sid = row.get("session_id")
        if sid is None:
            continue  # séance de langue / quiz : pas rattachée à une lecture
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


def _titles_for(sessions: list[dict]) -> dict[int, str]:
    """Titres des documents lus, une lecture par document et non par session."""
    titles: dict[int, str] = {}
    for session in sessions:
        doc_id = session.get("document_id")
        if doc_id is None or doc_id in titles:
            continue
        document = _safe(lambda: get_document(doc_id), None) or {}
        titles[doc_id] = document.get("title") or ""
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
    les lire : ce que j'ai lu, ce qui a bougé, ce que Gemma a remarqué, ce qu'il
    me reste à revoir.

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
        title = row["document_title"]
        if title and title not in documents:
            documents.append(title)

    profile = _safe(lambda: ensure_profile(user_id), {}) or {}
    cards = _safe(lambda: get_due_flashcards(user_id=user_id, limit=RECAP_CARDS), [])
    return {
        "since": since.date().isoformat(),
        "sessions": len(recent),
        "duration_s": sum(row["duration_s"] for row in recent),
        "pages_read": sum(row["pages_read"] for row in recent),
        "documents": documents,
        "movers": _top_movers(user_id, since),
        # Ce que Gemma a remarqué — le texte qu'elle réécrit à chaque
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
