# db/user.py — CRUD utilisateur local
from __future__ import annotations

import logging
from datetime import date, datetime

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


# Un jour manqué ne casse pas la série. C'est une décision de produit, pas un
# réglage : l'identité de Meta-Capp est bienveillante, et un streak qui punit
# retient mal les adultes — il fait surtout abandonner ceux qui viennent de
# rater une journée. Deux jours d'affilée sans lire, en revanche, sont une
# rupture de rythme : la série repart.
STREAK_GRACE_DAYS = 1


def get_streak(user_id: int = DEFAULT_USER_ID) -> dict:
    """Série d'étude, en LECTURE PURE. Aucun effet de bord.

    `GET /api/streak` incrémentait la série : ouvrir l'app comptait comme une
    journée d'étude, et un simple rechargement de page pouvait la faire vivre
    indéfiniment. La série n'avance plus que dans `record_study_day`, appelée à
    la fin d'une session réellement terminée."""
    conn = get_connection()
    row = conn.execute(
        "SELECT streak, longest_streak, last_study_day FROM login_streak WHERE user_id=?",
        (user_id,),
    ).fetchone()
    if row is None:
        return {"streak": 0, "longest_streak": 0, "last_study_day": None, "active": False}

    streak = int(row["streak"] or 0)
    last = row["last_study_day"]
    # Une série dont le dernier jour est trop ancien est FINIE : on l'affiche à
    # zéro sans rien écrire (l'écriture appartient à record_study_day). Une date
    # illisible compte comme trop ancienne — on n'invente pas une série.
    gap = _days_since(last)
    if gap is None or gap > STREAK_GRACE_DAYS + 1:
        streak = 0
    return {
        "streak": streak,
        "longest_streak": max(int(row["longest_streak"] or 0), streak),
        "last_study_day": last,
        "active": streak > 0,
    }


def record_study_day(user_id: int = DEFAULT_USER_ID, day: date | None = None) -> dict:
    """Enregistre AUJOURD'HUI (ou `day`) comme jour d'étude et fait avancer la série.

    Appelée une seule fois par session terminée (`services/session.py`). Le même
    jour compté deux fois ne bouge rien. `day` : le jour de la séance quand elle
    est finalisée plus tard — une lecture quittée en fermant le logiciel l'est
    au démarrage suivant, et ouvrir l'app le lendemain n'est pas étudier. Un jour
    antérieur au dernier compté ne change plus la série."""
    ensure_default_user()
    today = day or date.today()
    conn = get_connection()
    row = conn.execute(
        "SELECT streak, longest_streak, last_study_day FROM login_streak WHERE user_id=?",
        (user_id,),
    ).fetchone()

    if row is None:
        with conn:
            conn.execute(
                """INSERT INTO login_streak (user_id, streak, longest_streak, last_study_day)
                   VALUES (?, 1, 1, ?)""",
                (user_id, today.isoformat()),
            )
        return get_streak(user_id)

    last = row["last_study_day"]
    if last and str(last) >= today.isoformat():
        return get_streak(user_id)

    gap = _days_since(last, today)
    if gap is not None and gap <= STREAK_GRACE_DAYS + 1:
        streak = int(row["streak"] or 0) + 1
    else:
        streak = 1
    longest = max(int(row["longest_streak"] or 0), streak)

    with conn:
        conn.execute(
            """UPDATE login_streak
               SET streak=?, longest_streak=?, last_study_day=?
               WHERE user_id=?""",
            (streak, longest, today.isoformat(), user_id),
        )
    logger.info("Série d'étude user=%s : %s jour(s) (record %s)", user_id, streak, longest)
    return get_streak(user_id)


def _days_since(day: str | None, until: date | None = None) -> int | None:
    """Nombre de jours entre `day` (ISO) et `until` (aujourd'hui). None si illisible."""
    if not day:
        return None
    try:
        return ((until or date.today()) - date.fromisoformat(str(day))).days
    except ValueError:
        return None


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


def update_user_name(user_id: int, name: str) -> None:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Le nom utilisateur ne peut pas être vide")

    conn = get_connection()
    with conn:
        conn.execute("UPDATE user SET name=? WHERE id=?", (clean_name, user_id))
    logger.info("Nom utilisateur mis à jour id=%s à %s", user_id, datetime.now().isoformat())
