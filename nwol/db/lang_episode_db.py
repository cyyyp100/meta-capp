# db/lang_episode_db.py — CRUD du module langues, méthode « feuilleton » (v35).
#
# Séparé de db/lang_db.py, qui porte le flux hérité : les deux flux cohabitent
# pendant le pilote (lang_profiles.flow), et aucune requête d'ici ne touche aux
# tables héritées. Aucune logique : la politique (quand un mot est acquis, quel
# mode de séance, quel cran de difficulté) vit dans services/lang_*.py.
from __future__ import annotations

import json
import logging
from typing import Any, Iterable

from db import get_connection

logger = logging.getLogger("DB.lang_episode")


def _dumps(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _loads(raw: str | None, default: Any = None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _decode(row, json_fields: dict[str, Any]) -> dict | None:
    """Ligne SQLite -> dict ; chaque `x_json` devient `x` décodé."""
    if row is None:
        return None
    d = dict(row)
    for field, default in json_fields.items():
        raw = d.pop(field, None)
        d[field[: -len("_json")]] = _loads(raw, default)
    return d


def _update(table: str, key_sql: str, key_params: tuple, fields: dict, allowed: set[str], json_cols: set[str]) -> None:
    sets, params = [], []
    for name, value in fields.items():
        if name not in allowed:
            raise ValueError(f"colonne non modifiable : {table}.{name}")
        column = f"{name}_json" if name in json_cols else name
        sets.append(f"{column}=?")
        params.append(_dumps(value) if name in json_cols else value)
    if not sets:
        return
    conn = get_connection()
    with conn:
        conn.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE {key_sql}", (*params, *key_params))


# ── Référence (D1-D3), réinjectée depuis nwol/data/lang/ ──────────────────────

def reference_version(table: str, key_column: str, key: str) -> str | None:
    """`source_version` stockée pour une langue (ou un script), None si absente."""
    row = get_connection().execute(
        f"SELECT source_version FROM {table} WHERE {key_column}=? LIMIT 1", (key,)
    ).fetchone()
    return row["source_version"] if row else None


def replace_program(language: str, points: list[dict], version: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM lang_program_points WHERE language=?", (language,))
        conn.executemany(
            """INSERT INTO lang_program_points
               (language, point_id, ord, cefr, kind, title, payload_json, source_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (language, p["id"], int(p["order"]), p["cefr"], p["kind"], p["title"],
                 json.dumps(p, ensure_ascii=False), version)
                for p in points
            ],
        )


def _decode_point(row) -> dict | None:
    if row is None:
        return None
    payload = _loads(row["payload_json"], {}) or {}
    payload.update({"id": row["point_id"], "order": row["ord"], "cefr": row["cefr"],
                    "kind": row["kind"], "title": row["title"]})
    return payload


def get_program(language: str) -> list[dict]:
    rows = get_connection().execute(
        "SELECT * FROM lang_program_points WHERE language=? ORDER BY ord", (language,)
    ).fetchall()
    return [_decode_point(r) for r in rows]


def get_point(language: str, point_id: str) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM lang_program_points WHERE language=? AND point_id=?", (language, point_id)
    ).fetchone()
    return _decode_point(row)


def get_point_by_order(language: str, order: int) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM lang_program_points WHERE language=? AND ord=?", (language, int(order))
    ).fetchone()
    return _decode_point(row)


def program_size(language: str) -> int:
    row = get_connection().execute(
        "SELECT COUNT(*) AS n FROM lang_program_points WHERE language=?", (language,)
    ).fetchone()
    return int(row["n"]) if row else 0


def replace_script_units(script: str, units: list[dict], version: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM lang_script_units WHERE script=?", (script,))
        conn.executemany(
            """INSERT INTO lang_script_units
               (script, unit_id, kind, display, payload_json, ord, source_version)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (script, u["id"], u["kind"], u["display"], json.dumps(u, ensure_ascii=False),
                 int(u.get("order", i)), version)
                for i, u in enumerate(units)
            ],
        )


def get_script_units(script: str, kind: str | None = None) -> list[dict]:
    sql = "SELECT * FROM lang_script_units WHERE script=?"
    params: list = [script]
    if kind:
        sql += " AND kind=?"
        params.append(kind)
    rows = get_connection().execute(sql + " ORDER BY ord", params).fetchall()
    return [_loads(r["payload_json"], {}) | {"id": r["unit_id"], "kind": r["kind"], "display": r["display"]}
            for r in rows]


def replace_placement(language: str, items: list[dict], version: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM lang_placement_items WHERE language=?", (language,))
        conn.executemany(
            """INSERT INTO lang_placement_items (language, item_id, ord, payload_json, source_version)
               VALUES (?, ?, ?, ?, ?)""",
            [(language, it["id"], i, json.dumps(it, ensure_ascii=False), version)
             for i, it in enumerate(items)],
        )


def get_placement_items(language: str) -> list[dict]:
    rows = get_connection().execute(
        "SELECT payload_json FROM lang_placement_items WHERE language=? ORDER BY ord", (language,)
    ).fetchall()
    return [_loads(r["payload_json"], {}) for r in rows]


# ── Profil (colonnes feuilleton, D20) ─────────────────────────────────────────

_PROFILE_FIELDS = {
    "flow", "episode_n", "program_order", "ladder_step", "interests", "onboarding_done",
    "second_wave_started", "last_bilan_episode_n", "force_respiration", "replay_queue",
    "level", "placement_done", "last_session", "explain_lang",
}
_PROFILE_JSON = {"interests", "replay_queue"}


def update_profile_fields(profile_id: int, **fields) -> None:
    _update("lang_profiles", "id=?", (profile_id,), fields, _PROFILE_FIELDS, _PROFILE_JSON)


def decode_profile(profile: dict) -> dict:
    """Décode les colonnes JSON du feuilleton d'un profil lu par db.lang_db."""
    d = dict(profile)
    for name in _PROFILE_JSON:
        raw = d.pop(f"{name}_json", None)
        d[name] = _loads(raw, [] if name == "replay_queue" else None)
    return d


# ── Bible et arcs (D4-D5) ─────────────────────────────────────────────────────

def save_bible(profile_id: int, bible: dict, source: str) -> int:
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS v FROM lang_story_bibles WHERE profile_id=?", (profile_id,)
    ).fetchone()
    with conn:
        cur = conn.execute(
            """INSERT INTO lang_story_bibles
               (profile_id, version, characters_json, setting, comic_springs, interests_json,
                register_notes, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                profile_id, int(row["v"]) + 1, _dumps(bible.get("characters") or []),
                bible.get("setting") or "", bible.get("comic_springs") or "",
                _dumps(bible.get("interests") or []), bible.get("register_notes") or "", source,
            ),
        )
    return int(cur.lastrowid)


def get_latest_bible(profile_id: int) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM lang_story_bibles WHERE profile_id=? ORDER BY version DESC LIMIT 1", (profile_id,)
    ).fetchone()
    return _decode(row, {"characters_json": [], "interests_json": []})


def save_arc(profile_id: int, arc_n: int, start_episode_n: int, beats: list[dict], source: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO lang_story_arcs (profile_id, arc_n, start_episode_n, beats_json, source)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(profile_id, arc_n) DO UPDATE SET
                 start_episode_n=excluded.start_episode_n, beats_json=excluded.beats_json,
                 source=excluded.source, created_at=datetime('now')""",
            (profile_id, int(arc_n), int(start_episode_n), _dumps(beats), source),
        )


def get_arc(profile_id: int, arc_n: int) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM lang_story_arcs WHERE profile_id=? AND arc_n=?", (profile_id, int(arc_n))
    ).fetchone()
    return _decode(row, {"beats_json": []})


def get_latest_arc(profile_id: int) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM lang_story_arcs WHERE profile_id=? ORDER BY arc_n DESC LIMIT 1", (profile_id,)
    ).fetchone()
    return _decode(row, {"beats_json": []})


# ── Épisodes (D6) ─────────────────────────────────────────────────────────────

_EPISODE_JSON = {"params", "lines", "glossary", "notes", "point", "aids", "generation"}
_EPISODE_FIELDS = _EPISODE_JSON | {
    "kind", "program_point_id", "format", "ladder_step", "title", "summary", "teaser",
    "status", "ready_at", "first_played_at",
}
_EPISODE_DECODE = {
    "params_json": {}, "lines_json": [], "glossary_json": [], "notes_json": [],
    "point_json": {}, "aids_json": {}, "generation_json": {},
}


def create_episode(
    profile_id: int, episode_n: int, *, kind: str, program_point_id: str | None,
    format: str, ladder_step: int, params: dict,
) -> int:
    """Réserve l'épisode (statut `queued`). Idempotent : un épisode déjà réservé
    garde son contenu, et son id est renvoyé."""
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO lang_episodes
               (profile_id, episode_n, kind, program_point_id, format, ladder_step, params_json, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'queued')""",
            (profile_id, int(episode_n), kind, program_point_id, format, int(ladder_step), _dumps(params)),
        )
    row = conn.execute(
        "SELECT id FROM lang_episodes WHERE profile_id=? AND episode_n=?", (profile_id, int(episode_n))
    ).fetchone()
    return int(row["id"])


def update_episode(episode_id: int, **fields) -> None:
    _update("lang_episodes", "id=?", (episode_id,), fields, _EPISODE_FIELDS, _EPISODE_JSON)


def get_episode(episode_id: int) -> dict | None:
    row = get_connection().execute("SELECT * FROM lang_episodes WHERE id=?", (episode_id,)).fetchone()
    return _decode(row, _EPISODE_DECODE)


def get_episode_by_n(profile_id: int, episode_n: int) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM lang_episodes WHERE profile_id=? AND episode_n=?", (profile_id, int(episode_n))
    ).fetchone()
    return _decode(row, _EPISODE_DECODE)


def list_episodes(profile_id: int, *, statuses: Iterable[str] | None = None, limit: int = 500,
                  newest_first: bool = True) -> list[dict]:
    sql = "SELECT * FROM lang_episodes WHERE profile_id=?"
    params: list = [profile_id]
    statuses = list(statuses or [])
    if statuses:
        sql += f" AND status IN ({', '.join('?' * len(statuses))})"
        params.extend(statuses)
    sql += f" ORDER BY episode_n {'DESC' if newest_first else 'ASC'} LIMIT ?"
    params.append(int(limit))
    return [_decode(r, _EPISODE_DECODE) for r in get_connection().execute(sql, params).fetchall()]


def played_episodes(profile_id: int, *, limit: int = 20, before_n: int | None = None) -> list[dict]:
    """Épisodes déjà joués (statut `played`), du plus récent au plus ancien."""
    sql = "SELECT * FROM lang_episodes WHERE profile_id=? AND status='played'"
    params: list = [profile_id]
    if before_n is not None:
        sql += " AND episode_n < ?"
        params.append(int(before_n))
    sql += " ORDER BY episode_n DESC LIMIT ?"
    params.append(int(limit))
    return [_decode(r, _EPISODE_DECODE) for r in get_connection().execute(sql, params).fetchall()]


def played_lines(profile_id: int) -> list[str]:
    """Texte de chaque réplique des épisodes joués : tout ce que l'apprenant a
    déjà lu, dans l'ordre des épisodes."""
    rows = get_connection().execute(
        "SELECT lines_json FROM lang_episodes WHERE profile_id=? AND status='played' ORDER BY episode_n",
        (profile_id,),
    ).fetchall()
    return [str(ln.get("text") or "") for r in rows for ln in _loads(r["lines_json"], []) or []
            if isinstance(ln, dict)]


def requeue_stuck_generations() -> int:
    """G20 : un épisode resté `generating` (application fermée pendant la
    génération) repasse `queued` au démarrage."""
    conn = get_connection()
    with conn:
        cur = conn.execute("UPDATE lang_episodes SET status='queued' WHERE status='generating'")
    return int(cur.rowcount or 0)


def pending_episodes(profile_id: int | None = None) -> list[dict]:
    """Épisodes réservés et jamais écrits : `queued` (pas encore lancé, ou
    interrompu puis remis en file) ou `failed`, au-delà du dernier épisode joué
    de leur profil (`episode_n`). Chacun porte la langue de son profil, du plus
    ancien au plus récent."""
    sql = (
        "SELECT e.*, p.language AS language FROM lang_episodes e "
        "JOIN lang_profiles p ON p.id = e.profile_id "
        "WHERE e.status IN ('queued', 'failed') AND e.episode_n > COALESCE(p.episode_n, 0)"
    )
    params: list = []
    if profile_id is not None:
        sql += " AND e.profile_id = ?"
        params.append(int(profile_id))
    sql += " ORDER BY e.profile_id, e.episode_n"
    return [_decode(r, _EPISODE_DECODE) for r in get_connection().execute(sql, params).fetchall()]


# ── Séances (D7-D11) ──────────────────────────────────────────────────────────

_RUN_FIELDS = {
    "status", "current_step", "ended_at", "effective_seconds", "end_reason", "feeling", "plan",
    "episode_id", "second_wave_episode_id",
}
_RUN_JSON = {"plan"}


def create_run(profile_id: int, *, mode: str, plan: dict, episode_id: int | None,
               second_wave_episode_id: int | None, absence_days: int | None, study_date: str) -> int:
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO lang_runs
               (profile_id, mode, episode_id, second_wave_episode_id, plan_json, absence_days,
                status, study_date)
               VALUES (?, ?, ?, ?, ?, ?, 'in_progress', ?)""",
            (profile_id, mode, episode_id, second_wave_episode_id, _dumps(plan), absence_days, study_date),
        )
    return int(cur.lastrowid)


def get_run(run_id: int) -> dict | None:
    row = get_connection().execute("SELECT * FROM lang_runs WHERE id=?", (run_id,)).fetchone()
    return _decode(row, {"plan_json": {}})


def update_run(run_id: int, **fields) -> None:
    _update("lang_runs", "id=?", (run_id,), fields, _RUN_FIELDS, _RUN_JSON)


def open_runs(profile_id: int) -> list[dict]:
    rows = get_connection().execute(
        "SELECT * FROM lang_runs WHERE profile_id=? AND status='in_progress' ORDER BY id DESC",
        (profile_id,),
    ).fetchall()
    return [_decode(r, {"plan_json": {}}) for r in rows]


def recent_runs(profile_id: int, *, limit: int = 10, statuses: Iterable[str] = ("completed",)) -> list[dict]:
    statuses = list(statuses)
    rows = get_connection().execute(
        f"""SELECT * FROM lang_runs WHERE profile_id=? AND status IN ({', '.join('?' * len(statuses))})
            ORDER BY id DESC LIMIT ?""",
        (profile_id, *statuses, int(limit)),
    ).fetchall()
    return [_decode(r, {"plan_json": {}}) for r in rows]


def count_runs(profile_id: int, status: str = "completed") -> int:
    row = get_connection().execute(
        "SELECT COUNT(*) AS n FROM lang_runs WHERE profile_id=? AND status=?", (profile_id, status)
    ).fetchone()
    return int(row["n"]) if row else 0


def count_played(profile_id: int) -> int:
    row = get_connection().execute(
        "SELECT COUNT(*) AS n FROM lang_episodes WHERE profile_id=? AND status='played'", (profile_id,)
    ).fetchone()
    return int(row["n"]) if row else 0


def runs_between(profile_id: int, start_date: str, end_date: str) -> list[dict]:
    rows = get_connection().execute(
        """SELECT * FROM lang_runs WHERE profile_id=? AND study_date>=? AND study_date<=?
           ORDER BY id""",
        (profile_id, start_date, end_date),
    ).fetchall()
    return [_decode(r, {"plan_json": {}}) for r in rows]


def upsert_step(run_id: int, step: str, *, started_at: str | None = None, ended_at: str | None = None,
                seconds: int | None = None, skipped: bool | None = None, signal: str | None = None) -> None:
    """Crée ou complète la ligne d'une étape : une valeur absente (None) ne
    remplace jamais une valeur déjà écrite (les lots d'événements peuvent être
    renvoyés)."""
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO lang_run_steps (run_id, step, started_at, ended_at, seconds, skipped, signal)
               VALUES (?, ?, ?, ?, COALESCE(?, 0), COALESCE(?, 0), ?)
               ON CONFLICT(run_id, step) DO UPDATE SET
                 started_at=COALESCE(lang_run_steps.started_at, excluded.started_at),
                 ended_at=COALESCE(excluded.ended_at, lang_run_steps.ended_at),
                 seconds=MAX(lang_run_steps.seconds, excluded.seconds),
                 skipped=MAX(lang_run_steps.skipped, excluded.skipped),
                 signal=COALESCE(excluded.signal, lang_run_steps.signal)""",
            (run_id, step, started_at, ended_at, seconds, int(skipped) if skipped is not None else None, signal),
        )


def get_steps(run_id: int) -> list[dict]:
    rows = get_connection().execute(
        "SELECT * FROM lang_run_steps WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def add_reveals(run_id: int, episode_id: int | None, events: list[dict]) -> int:
    conn = get_connection()
    with conn:
        cur = conn.executemany(
            """INSERT OR IGNORE INTO lang_reveal_events
               (run_id, episode_id, line_idx, token_idx, lexeme_id, pass)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(run_id, e.get("episode_id", episode_id), int(e["line_idx"]), int(e["token_idx"]),
              e.get("lexeme_id"), e.get("pass") or "p2") for e in events],
        )
    return int(cur.rowcount or 0)


def get_reveals(run_id: int) -> list[dict]:
    rows = get_connection().execute(
        "SELECT * FROM lang_reveal_events WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _in(values: Iterable[str]) -> tuple[str, list[str]]:
    values = list(values)
    return ", ".join("?" * len(values)), values


def reveals_for_episode(profile_id: int, episode_id: int, passes: Iterable[str] = ("p2",)) -> list[dict]:
    """Taps d'un épisode, toutes séances confondues (jalons : première lecture)."""
    marks, values = _in(passes)
    rows = get_connection().execute(
        f"""SELECT e.*, r.started_at AS run_started_at FROM lang_reveal_events e
            JOIN lang_runs r ON r.id = e.run_id
            WHERE r.profile_id=? AND e.episode_id=? AND e.pass IN ({marks}) ORDER BY e.run_id""",
        (profile_id, episode_id, *values),
    ).fetchall()
    return [dict(r) for r in rows]


def reveal_counts(profile_id: int, passes: Iterable[str]) -> dict[int, int]:
    """Taps par épisode pendant les lectures `passes`, toutes séances confondues."""
    marks, values = _in(passes)
    rows = get_connection().execute(
        f"""SELECT e.episode_id AS eid, COUNT(*) AS n FROM lang_reveal_events e
            JOIN lang_runs r ON r.id = e.run_id
            WHERE r.profile_id=? AND e.pass IN ({marks}) GROUP BY e.episode_id""",
        (profile_id, *values),
    ).fetchall()
    return {int(r["eid"]): int(r["n"]) for r in rows if r["eid"] is not None}


def add_line_reveals(run_id: int, events: list[dict]) -> int:
    """« Traduction montrée » d'une réplique ; une fois par (épisode, réplique, passe)."""
    conn = get_connection()
    with conn:
        cur = conn.executemany(
            """INSERT OR IGNORE INTO lang_line_reveals (run_id, episode_id, line_idx, pass, via)
               VALUES (?, ?, ?, ?, ?)""",
            [(run_id, int(e["episode_id"]), int(e["line_idx"]), e.get("pass") or "lecture", e.get("via") or "line")
             for e in events],
        )
    return int(cur.rowcount or 0)


def get_line_reveals(run_id: int) -> list[dict]:
    rows = get_connection().execute(
        "SELECT * FROM lang_line_reveals WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_attempt(run_id: int, step: str, game_kind: str, item_ref: str, *, expected: Any,
                   given: Any, correct: bool | None, ms: int | None) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO lang_item_attempts
               (run_id, step, game_kind, item_ref, expected_json, given_json, correct, ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id, step, item_ref) DO UPDATE SET
                 given_json=excluded.given_json, correct=excluded.correct, ms=excluded.ms,
                 at=datetime('now')""",
            (run_id, step, game_kind, item_ref, _dumps(expected), _dumps(given),
             None if correct is None else int(bool(correct)), ms),
        )


def get_attempts(run_id: int) -> list[dict]:
    rows = get_connection().execute(
        "SELECT * FROM lang_item_attempts WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall()
    return [_decode(r, {"expected_json": None, "given_json": None}) for r in rows]


def upsert_second_wave_rating(run_id: int, episode_id: int | None, line_idx: int, *,
                              typed: str | None, rating: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO lang_second_wave_ratings (run_id, episode_id, line_idx, typed, rating)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(run_id, episode_id, line_idx) DO UPDATE SET
                 typed=excluded.typed, rating=excluded.rating""",
            (run_id, episode_id, int(line_idx), typed, rating),
        )


def get_second_wave_ratings(run_id: int) -> list[dict]:
    rows = get_connection().execute(
        "SELECT * FROM lang_second_wave_ratings WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Leçon d'un point (v40), partagée entre profils ────────────────────────────

_LESSON_DECODE = {"lesson_json": None, "generation_json": {}}


def get_point_lesson(language: str, point_id: str, explain_lang: str) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM lang_point_lessons WHERE language=? AND point_id=? AND explain_lang=?",
        (language, point_id, explain_lang),
    ).fetchone()
    return _decode(row, _LESSON_DECODE)


def save_point_lesson(language: str, point_id: str, explain_lang: str, *, status: str, lesson: dict | None,
                      point_hash: str, model: str | None, attempts: int, generation: dict | None) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO lang_point_lessons
               (language, point_id, explain_lang, status, lesson_json, point_hash, model, attempts, generation_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(language, point_id, explain_lang) DO UPDATE SET
                 status=excluded.status, lesson_json=excluded.lesson_json, point_hash=excluded.point_hash,
                 model=excluded.model, attempts=excluded.attempts, generation_json=excluded.generation_json,
                 updated_at=datetime('now')""",
            (language, point_id, explain_lang, status, _dumps(lesson), point_hash, model, int(attempts),
             _dumps(generation)),
        )


# ── Expression écrite (v40) ───────────────────────────────────────────────────

_WRITING_JSON = {"task", "checks", "feedback", "generation"}
_WRITING_FIELDS = _WRITING_JSON | {"text", "status", "corrected_at", "seen_at"}
_WRITING_DECODE = {"task_json": {}, "checks_json": None, "feedback_json": None, "generation_json": {}}


def create_writing(profile_id: int, run_id: int | None, episode_id: int | None, *, task: dict, text: str,
                   checks: dict | None, status: str) -> int:
    """Une expression écrite ; une seule par séance (index unique partiel) :
    l'id de celle qui existe déjà est renvoyé, sans rien écraser."""
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO lang_writings (profile_id, run_id, episode_id, task_json, text, checks_json, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (profile_id, run_id, episode_id, _dumps(task), text, _dumps(checks), status),
        )
    if run_id is None:
        row = conn.execute("SELECT id FROM lang_writings WHERE rowid=last_insert_rowid()").fetchone()
    else:
        row = conn.execute("SELECT id FROM lang_writings WHERE run_id=?", (run_id,)).fetchone()
    return int(row["id"])


def get_writing(writing_id: int) -> dict | None:
    row = get_connection().execute("SELECT * FROM lang_writings WHERE id=?", (writing_id,)).fetchone()
    return _decode(row, _WRITING_DECODE)


def get_writing_for_run(run_id: int) -> dict | None:
    row = get_connection().execute("SELECT * FROM lang_writings WHERE run_id=?", (run_id,)).fetchone()
    return _decode(row, _WRITING_DECODE)


def update_writing(writing_id: int, **fields) -> None:
    _update("lang_writings", "id=?", (writing_id,), fields, _WRITING_FIELDS, _WRITING_JSON)


def latest_unseen_writing(profile_id: int) -> dict | None:
    """La dernière correction prête que l'apprenant n'a pas encore vue."""
    row = get_connection().execute(
        """SELECT * FROM lang_writings WHERE profile_id=? AND status='ready' AND seen_at IS NULL
           ORDER BY id DESC LIMIT 1""",
        (profile_id,),
    ).fetchone()
    return _decode(row, _WRITING_DECODE)


def requeue_stuck_writings() -> list[int]:
    """Une correction restée `correcting` (application fermée pendant l'appel)
    repasse `pending` au démarrage ; renvoie les ids à relancer."""
    conn = get_connection()
    with conn:
        conn.execute("UPDATE lang_writings SET status='pending' WHERE status='correcting'")
    rows = conn.execute("SELECT id FROM lang_writings WHERE status='pending' ORDER BY id").fetchall()
    return [int(r["id"]) for r in rows]


# ── Lexique (D12) ─────────────────────────────────────────────────────────────

_LEXEME_FIELDS = {
    "form", "translation", "pos", "gender", "pron", "vocalized", "transparent", "card_id", "acquired_at",
}


def get_lexicon(profile_id: int) -> dict[str, dict]:
    rows = get_connection().execute(
        "SELECT * FROM lang_lexicon WHERE profile_id=?", (profile_id,)
    ).fetchall()
    return {r["lemma"]: dict(r) for r in rows}


def get_lexeme(profile_id: int, lemma: str) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM lang_lexicon WHERE profile_id=? AND lemma=?", (profile_id, lemma)
    ).fetchone()
    return dict(row) if row else None


def insert_lexeme(profile_id: int, entry: dict, episode_n: int | None) -> int:
    """Nouveau mot ; renvoie l'id, existant ou neuf. Un mot déjà connu garde
    tout, sauf la prononciation qui lui manquait (inscrit avant que Clikoda la
    donne pour les langues latines) : il la reçoit."""
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO lang_lexicon
               (profile_id, form, lemma, translation, pos, gender, pron, vocalized, transparent,
                first_episode_n)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(profile_id, lemma) DO UPDATE SET pron = excluded.pron
               WHERE COALESCE(lang_lexicon.pron, '') = '' AND COALESCE(excluded.pron, '') <> ''""",
            (
                profile_id, entry.get("form") or entry["lemma"], entry["lemma"],
                entry.get("translation") or "", entry.get("pos"), entry.get("gender"),
                entry.get("pron"), entry.get("vocalized"), int(bool(entry.get("transparent"))),
                episode_n,
            ),
        )
    row = conn.execute(
        "SELECT id FROM lang_lexicon WHERE profile_id=? AND lemma=?", (profile_id, entry["lemma"])
    ).fetchone()
    return int(row["id"])


def update_lexeme(lexeme_id: int, **fields) -> None:
    _update("lang_lexicon", "id=?", (lexeme_id,), fields, _LEXEME_FIELDS, set())


def bump_lexeme(lexeme_id: int, *, episode_n: int | None = None, exposures: int = 0, reveals: int = 0,
                ok: int = 0, ko: int = 0) -> None:
    """Incrémente les compteurs d'un mot. `episode_n` compte un épisode
    distinct de plus s'il diffère du dernier vu."""
    conn = get_connection()
    with conn:
        conn.execute(
            """UPDATE lang_lexicon SET
                 exposures=exposures+?, reveals=reveals+?,
                 recognitions_ok=recognitions_ok+?, recognitions_ko=recognitions_ko+?,
                 episodes_seen=episodes_seen + (CASE WHEN ? IS NOT NULL
                     AND (last_episode_n IS NULL OR last_episode_n != ?) THEN 1 ELSE 0 END),
                 last_episode_n=COALESCE(?, last_episode_n)
               WHERE id=?""",
            (exposures, reveals, ok, ko, episode_n, episode_n, episode_n, lexeme_id),
        )


def lexicon_counts(profile_id: int) -> dict:
    row = get_connection().execute(
        """SELECT COUNT(*) AS seen, SUM(CASE WHEN acquired_at IS NOT NULL THEN 1 ELSE 0 END) AS acquired
           FROM lang_lexicon WHERE profile_id=?""",
        (profile_id,),
    ).fetchone()
    return {"seen": int(row["seen"] or 0), "acquired": int(row["acquired"] or 0)}


# ── Signes d'écriture (D13) ───────────────────────────────────────────────────

def get_script_progress(profile_id: int, script: str) -> dict[str, dict]:
    rows = get_connection().execute(
        "SELECT * FROM lang_script_progress WHERE profile_id=? AND script=?", (profile_id, script)
    ).fetchall()
    return {r["unit_key"]: dict(r) for r in rows}


def bump_script_unit(profile_id: int, script: str, unit_key: str, *, episode_n: int | None = None,
                     exposures: int = 0, ok: int = 0, ko: int = 0) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO lang_script_progress (profile_id, script, unit_key)
               VALUES (?, ?, ?)""",
            (profile_id, script, unit_key),
        )
        conn.execute(
            """UPDATE lang_script_progress SET
                 exposures=exposures+?, recognitions_ok=recognitions_ok+?, recognitions_ko=recognitions_ko+?,
                 episodes_seen=episodes_seen + (CASE WHEN ? IS NOT NULL
                     AND (last_episode_n IS NULL OR last_episode_n != ?) THEN 1 ELSE 0 END),
                 last_episode_n=COALESCE(?, last_episode_n)
               WHERE profile_id=? AND script=? AND unit_key=?""",
            (exposures, ok, ko, episode_n, episode_n, episode_n, profile_id, script, unit_key),
        )


def set_script_unit_acquired(profile_id: int, script: str, unit_key: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """UPDATE lang_script_progress SET acquired_at=COALESCE(acquired_at, datetime('now'))
               WHERE profile_id=? AND script=? AND unit_key=?""",
            (profile_id, script, unit_key),
        )


# ── Programme et niveau (D14-D15) ─────────────────────────────────────────────

def set_point_status(profile_id: int, point_id: str, status: str, *, introduced_episode_n: int | None = None) -> None:
    """`introduit` ne rétrograde jamais un point déjà `consolide`."""
    conn = get_connection()
    with conn:
        if status == "consolide":
            conn.execute(
                """INSERT INTO lang_program_progress (profile_id, point_id, status, introduced_episode_n,
                                                      consolidated_at)
                   VALUES (?, ?, 'consolide', ?, datetime('now'))
                   ON CONFLICT(profile_id, point_id) DO UPDATE SET status='consolide',
                     consolidated_at=COALESCE(lang_program_progress.consolidated_at, datetime('now'))""",
                (profile_id, point_id, introduced_episode_n),
            )
        else:
            conn.execute(
                """INSERT INTO lang_program_progress (profile_id, point_id, status, introduced_episode_n)
                   VALUES (?, ?, 'introduit', ?)
                   ON CONFLICT(profile_id, point_id) DO NOTHING""",
                (profile_id, point_id, introduced_episode_n),
            )


def get_program_progress(profile_id: int) -> dict[str, dict]:
    rows = get_connection().execute(
        "SELECT * FROM lang_program_progress WHERE profile_id=?", (profile_id,)
    ).fetchall()
    return {r["point_id"]: dict(r) for r in rows}


def add_level_history(profile_id: int, cefr: str, program_order: int, source: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO lang_level_history (profile_id, cefr, program_order, source) VALUES (?, ?, ?, ?)",
            (profile_id, cefr, int(program_order), source),
        )


def get_level_history(profile_id: int) -> list[dict]:
    rows = get_connection().execute(
        "SELECT * FROM lang_level_history WHERE profile_id=? ORDER BY id", (profile_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Qualité du contenu (D16-D17) ──────────────────────────────────────────────

def get_vocalized_forms(language: str, bare: str) -> list[dict]:
    rows = get_connection().execute(
        "SELECT * FROM lang_vocalized_forms WHERE language=? AND bare=?", (language, bare)
    ).fetchall()
    return [dict(r) for r in rows]


def record_vocalized_candidate(language: str, bare: str, stem_vocalized: str, episode_id: int | None) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO lang_vocalized_forms (language, bare, stem_vocalized, status, first_episode_id)
               VALUES (?, ?, ?, 'candidat', ?)
               ON CONFLICT(language, bare, stem_vocalized) DO UPDATE SET occurrences=occurrences+1""",
            (language, bare, stem_vocalized, episode_id),
        )


def list_vocalized_forms(language: str, *, status: str | None = None, min_occurrences: int = 1) -> list[dict]:
    """Formes observées, regroupées par mot nu, les plus fréquentes d'abord :
    l'ordre de relecture de tools/review_vocalized_forms.py (A7)."""
    sql = "SELECT * FROM lang_vocalized_forms WHERE language=? AND occurrences>=?"
    params: list = [language, int(min_occurrences)]
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY (SELECT SUM(occurrences) FROM lang_vocalized_forms f2 WHERE f2.language=lang_vocalized_forms.language AND f2.bare=lang_vocalized_forms.bare) DESC, bare, occurrences DESC"
    return [dict(r) for r in get_connection().execute(sql, params).fetchall()]


def set_vocalized_status(language: str, bare: str, stem_vocalized: str, status: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO lang_vocalized_forms (language, bare, stem_vocalized, status)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(language, bare, stem_vocalized) DO UPDATE SET status=excluded.status,
                 reports=reports + (CASE WHEN excluded.status='signale' THEN 1 ELSE 0 END)""",
            (language, bare, stem_vocalized, status),
        )


def add_report(profile_id: int, *, episode_id: int | None, line_idx: int | None, token_idx: int | None,
               kind: str, comment: str) -> int:
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO lang_reports (profile_id, episode_id, line_idx, token_idx, kind, comment)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (profile_id, episode_id, line_idx, token_idx, kind, comment),
        )
    return int(cur.lastrowid)


def list_reports(profile_id: int | None = None, *, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM lang_reports WHERE 1=1"
    params: list = []
    if profile_id is not None:
        sql += " AND profile_id=?"
        params.append(profile_id)
    if status:
        sql += " AND status=?"
        params.append(status)
    return [dict(r) for r in get_connection().execute(sql + " ORDER BY id", params).fetchall()]


def reported_tokens(episode_id: int) -> set[tuple[int, int]]:
    rows = get_connection().execute(
        "SELECT line_idx, token_idx FROM lang_reports WHERE episode_id=? AND line_idx IS NOT NULL",
        (episode_id,),
    ).fetchall()
    return {(int(r["line_idx"]), int(r["token_idx"] if r["token_idx"] is not None else -1)) for r in rows}


# ── Activité (D18-D19) ────────────────────────────────────────────────────────

def bump_daily_activity(profile_id: int, study_date: str, *, effective_seconds: int = 0,
                        runs_completed: int = 0, rereads: int = 0, cards_reviewed: int = 0,
                        reveals: int = 0, items_answered: int = 0, first_start_local: str | None = None) -> dict:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO lang_daily_activity (profile_id, study_date, first_start_local)
               VALUES (?, ?, ?) ON CONFLICT(profile_id, study_date) DO NOTHING""",
            (profile_id, study_date, first_start_local),
        )
        conn.execute(
            """UPDATE lang_daily_activity SET
                 effective_seconds=effective_seconds+?, runs_completed=runs_completed+?,
                 rereads=rereads+?, cards_reviewed=cards_reviewed+?, reveals=reveals+?,
                 items_answered=items_answered+?,
                 first_start_local=COALESCE(first_start_local, ?)
               WHERE profile_id=? AND study_date=?""",
            (int(effective_seconds), int(runs_completed), int(rereads), int(cards_reviewed),
             int(reveals), int(items_answered), first_start_local, profile_id, study_date),
        )
    return get_daily_activity(profile_id, study_date) or {}


def set_daily_counted(profile_id: int, study_date: str, counted: bool) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE lang_daily_activity SET counted=? WHERE profile_id=? AND study_date=?",
            (int(bool(counted)), profile_id, study_date),
        )


def get_daily_activity(profile_id: int, study_date: str) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM lang_daily_activity WHERE profile_id=? AND study_date=?", (profile_id, study_date)
    ).fetchone()
    return dict(row) if row else None


def list_daily_activity(profile_id: int, *, since: str | None = None) -> list[dict]:
    sql = "SELECT * FROM lang_daily_activity WHERE profile_id=?"
    params: list = [profile_id]
    if since:
        sql += " AND study_date>=?"
        params.append(since)
    return [dict(r) for r in get_connection().execute(sql + " ORDER BY study_date", params).fetchall()]


def last_counted_study_date(profile_id: int, *, before: str | None = None) -> str | None:
    sql = "SELECT MAX(study_date) AS d FROM lang_daily_activity WHERE profile_id=? AND counted=1"
    params: list = [profile_id]
    if before:
        sql += " AND study_date<?"
        params.append(before)
    row = get_connection().execute(sql, params).fetchone()
    return row["d"] if row and row["d"] else None


def get_weekly(profile_id: int, week_start: str) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM lang_weekly_analysis WHERE profile_id=? AND week_start=?", (profile_id, week_start)
    ).fetchone()
    return _decode(row, {"aggregates_json": {}, "analysis_json": None})


def latest_weekly(profile_id: int) -> dict | None:
    row = get_connection().execute(
        """SELECT * FROM lang_weekly_analysis WHERE profile_id=? AND status='ready'
           ORDER BY week_start DESC LIMIT 1""",
        (profile_id,),
    ).fetchone()
    return _decode(row, {"aggregates_json": {}, "analysis_json": None})


def save_weekly(profile_id: int, week_start: str, *, aggregates: dict, analysis: dict | None, status: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO lang_weekly_analysis (profile_id, week_start, aggregates_json, analysis_json, status)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(profile_id, week_start) DO UPDATE SET aggregates_json=excluded.aggregates_json,
                 analysis_json=COALESCE(excluded.analysis_json, lang_weekly_analysis.analysis_json),
                 status=excluded.status""",
            (profile_id, week_start, _dumps(aggregates), _dumps(analysis), status),
        )
