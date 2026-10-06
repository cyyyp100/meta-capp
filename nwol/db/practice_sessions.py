# db/practice_sessions.py — Séances de pratique (quiz, langues) et réponses de quiz
#
# Une séance de pratique est l'équivalent, hors lecture, d'une `reading_sessions` :
# elle porte une courbe de jauges (`db.session_gauges`, scope "practice"), des
# mouvements de profil (`metacog_history.practice_session_id`) et des réflexions
# (`session_reflections.practice_session_id`). Ce qui est propre à chaque
# activité reste chez elle : les réponses d'un quiz ici (rien d'autre ne les
# gardait), le détail d'une séance de langue dans les tables `lang_*`.
from __future__ import annotations

import json
import logging
from datetime import datetime

from db import get_connection
from db.user import DEFAULT_USER_ID, ensure_default_user

logger = logging.getLogger("DB.practice_sessions")

KINDS = ("quiz", "lang")
_JSON_COLUMNS = ("seed_json", "settings_json", "details_json")


def create_practice_session(
    kind: str,
    user_id: int = DEFAULT_USER_ID,
    *,
    seed: dict | None = None,
    settings: dict | None = None,
    lang_run_id: int | None = None,
    lang_lesson_id: int | None = None,
    started_at: str | None = None,
) -> int:
    if kind not in KINDS:
        raise ValueError(f"Type de séance inconnu : {kind!r}")
    ensure_default_user()
    columns = ["kind", "user_id", "seed_json", "settings_json", "lang_run_id", "lang_lesson_id"]
    values: list = [kind, user_id, _dumps(seed), _dumps(settings), lang_run_id, lang_lesson_id]
    if started_at:
        # Même horloge que la séance d'origine (une séance de langue a commencé
        # bien avant d'être enregistrée ici) : sinon la frise la classerait à
        # l'heure de sa clôture.
        columns.append("started_at")
        values.append(started_at)
    conn = get_connection()
    with conn:
        cur = conn.execute(
            f"INSERT INTO practice_sessions ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' * len(columns))})",
            values,
        )
    logger.info("Séance de pratique créée id=%s kind=%s", cur.lastrowid, kind)
    return int(cur.lastrowid)


def get_practice_session(session_id: int) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM practice_sessions WHERE id=?", (session_id,),
    ).fetchone()
    return _decode(row) if row else None


def find_practice_session(*, lang_run_id: int | None = None, lang_lesson_id: int | None = None) -> dict | None:
    """La séance de pratique d'une séance de langue (au plus une, index unique)."""
    if lang_run_id is not None:
        query, param = "SELECT * FROM practice_sessions WHERE lang_run_id=?", lang_run_id
    elif lang_lesson_id is not None:
        query, param = "SELECT * FROM practice_sessions WHERE lang_lesson_id=?", lang_lesson_id
    else:
        return None
    row = get_connection().execute(query, (param,)).fetchone()
    return _decode(row) if row else None


def list_practice_sessions(
    user_id: int = DEFAULT_USER_ID,
    *,
    kind: str | None = None,
    limit: int = 20,
) -> list[dict]:
    params: list = [user_id]
    query = "SELECT * FROM practice_sessions WHERE user_id=?"
    if kind:
        query += " AND kind=?"
        params.append(kind)
    query += " ORDER BY started_at DESC, id DESC LIMIT ?"
    params.append(int(limit))
    rows = get_connection().execute(query, params).fetchall()
    return [_decode(row) for row in rows]


def count_practice_sessions(user_id: int = DEFAULT_USER_ID) -> dict[str, int]:
    """Effectif par type : {'quiz': n, 'lang': n} (types absents omis)."""
    rows = get_connection().execute(
        "SELECT kind, COUNT(*) AS n FROM practice_sessions WHERE user_id=? GROUP BY kind",
        (user_id,),
    ).fetchall()
    return {row["kind"]: int(row["n"]) for row in rows}


def end_practice_session(session_id: int, duration_s: int | None = None) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE practice_sessions SET ended_at=?, duration_s=? WHERE id=?",
            (datetime.now().isoformat(), max(0, int(duration_s or 0)), session_id),
        )


def mark_finalized(session_id: int) -> bool:
    """Pose `finalized_at` une seule fois. False si la séance l'était déjà :
    deux finalisations ne font pas glisser le profil deux fois."""
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "UPDATE practice_sessions SET finalized_at=? WHERE id=? AND finalized_at IS NULL",
            (datetime.now().isoformat(), session_id),
        )
    return cur.rowcount > 0


def update_practice_details(
    session_id: int,
    *,
    analysis: str | None = None,
    details: dict | None = None,
) -> None:
    """Analyse de Clikoda et détails propres à l'activité. `details` est FUSIONNÉ
    dans l'existant : deux écritures (bilan, puis analyse) ne s'effacent pas."""
    current = get_practice_session(session_id)
    if current is None:
        return
    assignments: list[str] = []
    params: list = []
    if analysis is not None:
        assignments.append("analysis=?")
        params.append(str(analysis).strip())
    if details:
        merged = {**(current.get("details") or {}), **details}
        assignments.append("details_json=?")
        params.append(_dumps(merged))
    if not assignments:
        return
    params.append(session_id)
    conn = get_connection()
    with conn:
        conn.execute(f"UPDATE practice_sessions SET {', '.join(assignments)} WHERE id=?", params)


def delete_practice_session(session_id: int) -> bool:
    conn = get_connection()
    with conn:
        cur = conn.execute("DELETE FROM practice_sessions WHERE id=?", (session_id,))
    return cur.rowcount > 0


# ── Réponses d'un quiz ────────────────────────────────────────────────────────

def save_quiz_answers(session_id: int, answers: list[dict]) -> None:
    """Réponses d'une séance de quiz, dans l'ordre où elles ont été données.

    `position` est unique par séance : renvoyer le même lot ne double rien."""
    rows = [
        (
            session_id,
            int(a.get("position", index)),
            a.get("question_id"),
            str(a.get("question") or ""),
            a.get("question_type") or None,
            a.get("category") or None,
            a.get("source") or None,
            a.get("document_id"),
            a.get("chapter_title") or None,
            str(a.get("user_answer") or ""),
            str(a.get("verdict") or ""),
            int(bool(a.get("graded", True))),
            a.get("response_time_ms"),
            _dumps(a.get("signals")),
        )
        for index, a in enumerate(answers)
    ]
    if not rows:
        return
    conn = get_connection()
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO quiz_session_answers
               (session_id, position, question_id, question, question_type, category, source,
                document_id, chapter_title, user_answer, verdict, graded, response_time_ms, signals_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )


def get_quiz_answers(session_id: int) -> list[dict]:
    rows = get_connection().execute(
        "SELECT * FROM quiz_session_answers WHERE session_id=? ORDER BY position, id",
        (session_id,),
    ).fetchall()
    answers = []
    for row in rows:
        item = dict(row)
        item["graded"] = bool(item.get("graded"))
        item["signals"] = _loads(item.pop("signals_json", None))
        answers.append(item)
    return answers


def _decode(row) -> dict:
    item = dict(row)
    for column in _JSON_COLUMNS:
        item[column.removesuffix("_json")] = _loads(item.pop(column, None)) or {}
    return item


def _dumps(value) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _loads(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None
