# db/user.py — CRUD utilisateur local
from __future__ import annotations

import logging
from datetime import datetime, date, timedelta

from db import get_connection

logger = logging.getLogger("DB.user")


DEFAULT_USER_ID = 1
DEFAULT_USER_NAME = "Utilisateur"


def ensure_default_user(name: str = DEFAULT_USER_NAME) -> int:
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO user (id, name) VALUES (?, ?)",
            (DEFAULT_USER_ID, name),
        )
        conn.execute(
            """INSERT OR IGNORE INTO metacog_profile
               (user_id, attention, context_comprehension, creativity, retention, curiosity)
               VALUES (?, 50.0, 50.0, 50.0, 50.0, 50.0)""",
            (DEFAULT_USER_ID,),
        )
    return DEFAULT_USER_ID


def get_user(user_id: int = DEFAULT_USER_ID) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM user WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_default_user() -> dict:
    ensure_default_user()
    user = get_user(DEFAULT_USER_ID)
    if user is None:
        raise RuntimeError("Impossible d'initialiser l'utilisateur par défaut")
    return user


def get_user_speed(user_id: int = DEFAULT_USER_ID) -> int:
    conn = get_connection()
    row = conn.execute("SELECT speed_ms FROM user WHERE id=?", (user_id,)).fetchone()
    if row and row["speed_ms"] is not None:
        return int(row["speed_ms"])

    from config.settings import READING_SPEED_INITIAL_MS

    return READING_SPEED_INITIAL_MS


def save_user_speed(user_id: int, speed_ms: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute("UPDATE user SET speed_ms=? WHERE id=?", (int(speed_ms), user_id))


def record_login_and_get_streak(user_id: int = DEFAULT_USER_ID) -> int:
    conn = get_connection()
    today = date.today().isoformat()

    row = conn.execute(
        "SELECT streak, last_login FROM login_streak WHERE user_id=?", (user_id,)
    ).fetchone()

    if row is None:
        with conn:
            conn.execute(
                "INSERT INTO login_streak (user_id, streak, last_login) VALUES (?, 1, ?)",
                (user_id, today),
            )
        return 1

    last_login = row["last_login"]
    streak = row["streak"]

    if last_login == today:
        return streak

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    new_streak = streak + 1 if last_login == yesterday else 1

    with conn:
        conn.execute(
            "UPDATE login_streak SET streak=?, last_login=? WHERE user_id=?",
            (new_streak, today, user_id),
        )
    logger.info("Streak utilisateur id=%s : %s jour(s)", user_id, new_streak)
    return new_streak


def get_user_lang(user_id: int = DEFAULT_USER_ID) -> str:
    conn = get_connection()
    row = conn.execute("SELECT lang FROM user WHERE id=?", (user_id,)).fetchone()
    if row and row["lang"]:
        return row["lang"]
    return "fr"


def set_user_lang(user_id: int, lang: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute("UPDATE user SET lang=? WHERE id=?", (lang, user_id))


def get_assistant_prefs(user_id: int = DEFAULT_USER_ID) -> dict:
    """Préférences de la bulle assistant : mode + position mémorisée."""
    from config.settings import ASSISTANT_DEFAULT_MODE, ASSISTANT_MODES

    conn = get_connection()
    row = conn.execute(
        "SELECT assistant_mode, bubble_rel_x, bubble_rel_y FROM user WHERE id=?",
        (user_id,),
    ).fetchone()
    mode = row["assistant_mode"] if row and row["assistant_mode"] else ASSISTANT_DEFAULT_MODE
    if mode not in ASSISTANT_MODES:
        mode = ASSISTANT_DEFAULT_MODE
    return {
        "mode": mode,
        "bubble_rel_x": row["bubble_rel_x"] if row else None,
        "bubble_rel_y": row["bubble_rel_y"] if row else None,
    }


def save_assistant_mode(user_id: int, mode: str) -> None:
    from config.settings import ASSISTANT_MODES

    if mode not in ASSISTANT_MODES:
        raise ValueError(f"Mode assistant inconnu : {mode}")
    conn = get_connection()
    with conn:
        conn.execute("UPDATE user SET assistant_mode=? WHERE id=?", (mode, user_id))


def save_bubble_position(user_id: int, rel_x: float, rel_y: float) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE user SET bubble_rel_x=?, bubble_rel_y=? WHERE id=?",
            (max(0.0, min(1.0, float(rel_x))), max(0.0, min(1.0, float(rel_y))), user_id),
        )


def update_user_name(user_id: int, name: str) -> None:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Le nom utilisateur ne peut pas être vide")

    conn = get_connection()
    with conn:
        conn.execute("UPDATE user SET name=? WHERE id=?", (clean_name, user_id))
    logger.info("Nom utilisateur mis à jour id=%s à %s", user_id, datetime.now().isoformat())
