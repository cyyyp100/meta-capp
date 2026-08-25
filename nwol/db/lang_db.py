# db/lang_db.py — CRUD pour le module langue Assimil
from __future__ import annotations

import json
import logging

from db import get_connection

logger = logging.getLogger("DB.lang")


# ── Profils ───────────────────────────────────────────────────────────────────

def get_or_create_lang_profile(user_id: int, language: str) -> dict:
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO lang_profiles (user_id, language) VALUES (?, ?)",
            (user_id, language),
        )
    row = conn.execute(
        "SELECT * FROM lang_profiles WHERE user_id=? AND language=?",
        (user_id, language),
    ).fetchone()
    return dict(row)


def get_lang_profile_by_id(profile_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM lang_profiles WHERE id=?", (profile_id,)).fetchone()
    return dict(row) if row else None


def get_all_lang_profiles(user_id: int) -> list[dict]:
    """Tous les profils de langue d'un utilisateur (énumération pour les stats)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM lang_profiles WHERE user_id=? ORDER BY language",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_lang_profile(
    profile_id: int,
    *,
    current_lesson: int | None = None,
    phase: str | None = None,
    level: str | None = None,
    placement_done: int | None = None,
    touch_last_session: bool = True,
) -> None:
    conn = get_connection()
    updates: list[str] = []
    params: list = []
    if current_lesson is not None:
        updates.append("current_lesson=?")
        params.append(current_lesson)
    if phase is not None:
        updates.append("phase=?")
        params.append(phase)
    if level is not None:
        updates.append("level=?")
        params.append(level)
    if placement_done is not None:
        updates.append("placement_done=?")
        params.append(int(placement_done))
    if not updates and not touch_last_session:
        return
    # `last_session` n'est touché qu'à la clôture d'une vraie session (pas à
    # l'initialisation du profil) : touch_last_session=False pour la config seule.
    if touch_last_session:
        updates.append("last_session=datetime('now')")
    if not updates:
        return
    params.append(profile_id)
    with conn:
        conn.execute(
            f"UPDATE lang_profiles SET {', '.join(updates)} WHERE id=?",
            params,
        )


# ── Curriculum ────────────────────────────────────────────────────────────────

def get_curriculum(language: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM lang_curriculum WHERE language=? ORDER BY lesson_n",
        (language,),
    ).fetchall()
    return [_decode_curriculum_row(r) for r in rows]


def save_curriculum(language: str, lessons: list[dict]) -> None:
    conn = get_connection()
    with conn:
        for lesson in lessons:
            conn.execute(
                """INSERT OR REPLACE INTO lang_curriculum
                   (language, lesson_n, theme, grammar_point, vocabulary_json, level, reuses_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    language,
                    int(lesson["lesson_n"]),
                    lesson.get("theme", ""),
                    lesson.get("grammar_point", ""),
                    json.dumps(lesson.get("vocabulary", []), ensure_ascii=False),
                    lesson.get("level", "A1"),
                    json.dumps(lesson.get("reuses", []), ensure_ascii=False),
                ),
            )
    logger.info("Curriculum '%s' enregistré (%d leçons)", language, len(lessons))


def _decode_curriculum_row(row) -> dict:
    d = dict(row)
    for field, key in [("vocabulary_json", "vocabulary"), ("reuses_json", "reuses")]:
        raw = d.pop(field, None)
        try:
            d[key] = json.loads(raw) if raw else []
        except Exception:
            d[key] = []
    return d


# ── Cache de leçon ────────────────────────────────────────────────────────────

def get_lesson_cache(profile_id: int, lesson_n: int) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM lang_lesson_cache WHERE profile_id=? AND lesson_n=?",
        (profile_id, lesson_n),
    ).fetchone()
    return _decode_lesson_row(row) if row else None


def save_lesson_cache(
    profile_id: int,
    lesson_n: int,
    *,
    dialogue: list,
    notes: dict,
    vocabulary: list,
) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO lang_lesson_cache
               (profile_id, lesson_n, dialogue_json, notes_json, vocabulary_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                profile_id,
                lesson_n,
                json.dumps(dialogue, ensure_ascii=False),
                json.dumps(notes, ensure_ascii=False),
                json.dumps(vocabulary, ensure_ascii=False),
            ),
        )


def _decode_lesson_row(row) -> dict:
    d = dict(row)
    for field, key, default in [
        ("dialogue_json", "dialogue", []),
        ("notes_json", "notes", {}),
        ("vocabulary_json", "vocabulary", []),
    ]:
        raw = d.pop(field, None)
        try:
            d[key] = json.loads(raw) if raw else default
        except Exception:
            d[key] = default
    return d


# ── Sessions ──────────────────────────────────────────────────────────────────

def save_lang_session(
    profile_id: int,
    lesson_n: int,
    duration_s: int,
    score: float,
    session_type: str = "dialogue_ecoute",
) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO lang_sessions (profile_id, lesson_n, duration_s, score, session_type)"
            " VALUES (?,?,?,?,?)",
            (profile_id, lesson_n, duration_s, score, session_type),
        )


def get_lang_session_count(profile_id: int) -> int:
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) as n FROM lang_sessions WHERE profile_id=?",
        (profile_id,),
    ).fetchone()
    return int(row["n"]) if row else 0


def get_last_session_type(profile_id: int) -> str | None:
    """Type de la dernière session jouée (pour la règle anti-répétition)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT session_type FROM lang_sessions WHERE profile_id=?"
        " ORDER BY date DESC, id DESC LIMIT 1",
        (profile_id,),
    ).fetchone()
    return row["session_type"] if row and row["session_type"] else None


def get_skill_distribution(profile_id: int, window: int = 7) -> dict[str, int]:
    """Répartition des compétences sur les `window` dernières sessions.

    Joint les sessions récentes au catalogue (session_type -> skill) et compte
    par compétence. Sert au rééquilibrage : le séquenceur favorise les skills
    les moins représentés récemment.
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT t.skill AS skill, COUNT(*) AS n
           FROM (
               SELECT session_type FROM lang_sessions
               WHERE profile_id=? ORDER BY date DESC, id DESC LIMIT ?
           ) s
           JOIN lang_session_types t ON t.code = s.session_type
           GROUP BY t.skill""",
        (profile_id, window),
    ).fetchall()
    return {r["skill"]: int(r["n"]) for r in rows}


def get_skill_scores(profile_id: int) -> dict[str, dict]:
    """Score moyen (0–100) et nombre d'exercices par compétence, sur tout l'historique.

    Joint les exercices joués (`lang_sessions`) au catalogue (session_type -> skill)
    et moyenne le score (stocké en 0–1) ramené sur 0–100. Sert à l'analyse poussée
    par compétence (page Langues + bilan de séance). Déterministe, jamais de LLM.
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT t.skill AS skill, AVG(s.score) AS avg01, COUNT(*) AS n
           FROM lang_sessions s
           JOIN lang_session_types t ON t.code = s.session_type
           WHERE s.profile_id=?
           GROUP BY t.skill""",
        (profile_id,),
    ).fetchall()
    return {
        r["skill"]: {"score": round(float(r["avg01"] or 0.0) * 100, 1), "count": int(r["n"])}
        for r in rows
    }


# ── Catalogue des types de session (statique, jamais généré par LLM) ──────────
#
# Source de vérité côté code. Seedée en base à chaque démarrage (INSERT OR REPLACE)
# pour que toute modification de libellé/description prenne effet immédiatement.
# Colonnes : (code, phase, skill, label, description, render_kind).
#   phase       : "passive" | "active" | "any" (filtre selon lang_profiles.phase)
#   skill       : compétence travaillée (pour la répartition / le rééquilibrage)
#   render_kind : forme du contenu + composant de rendu côté frontend / dispatch LLM
SESSION_TYPES_SEED: list[tuple[str, str, str, str, str, str]] = [
    ("dialogue_ecoute", "passive", "comprehension_orale", "Dialogue (écoute)",
     "Court dialogue à écouter (révélation progressive) pour entraîner la compréhension orale en contexte.",
     "dialogue"),
    ("dialogue_lecture", "passive", "comprehension_ecrite", "Dialogue (lecture)",
     "Court dialogue à lire avec traduction et notes, pour la compréhension écrite et l'assimilation passive.",
     "dialogue"),
    ("vocabulaire_contextuel", "passive", "vocabulaire", "Vocabulaire en contexte",
     "Série de mots-clés présentés en contexte de phrase, pour enrichir le vocabulaire sans liste sèche.",
     "vocabulary"),
    ("culture_courte", "passive", "comprehension_ecrite", "Texte culturel",
     "Court texte culturel sur le pays de la langue, suivi de questions de compréhension.",
     "reading"),
    ("phonetique_ciblee", "passive", "prononciation", "Phonétique ciblée",
     "Focus sur un son difficile via des paires minimales et des exercices de prononciation.",
     "phonetics"),
    ("histoire_courte", "passive", "comprehension_ecrite", "Mini-récit",
     "Mini-récit simple et progressif pour travailler la compréhension écrite de façon narrative.",
     "reading"),
    ("rappel_production", "active", "production_orale", "Rappel + production",
     "Réactivation du vocabulaire récent puis courte production orale guidée.",
     "production"),
    ("traduction_inverse", "active", "production_ecrite", "Traduction inverse",
     "Phrases en français à traduire dans la langue cible (production écrite).",
     "translation"),
    ("dictee_courte", "active", "comprehension_orale", "Dictée",
     "Courte dictée : l'apprenant écrit ce qu'il entend, segment par segment.",
     "dictation"),
    ("reformulation_libre", "active", "production_orale", "Reformulation libre",
     "Reformuler librement une idée donnée dans la langue cible (production ouverte).",
     "production"),
    ("mini_dialogue_simule", "active", "production_orale", "Dialogue simulé",
     "Jeu de rôle : l'apprenant complète les répliques manquantes d'un dialogue.",
     "production"),
    ("correction_guidee", "active", "grammaire_contexte", "Correction guidée",
     "Phrases contenant des erreurs typiques à repérer et corriger (grammaire en contexte).",
     "production"),
    ("revision_adaptative", "any", "revision", "Révision",
     "Révision ciblée des points faibles récents de l'apprenant (erreurs passées).",
     "revision"),
    # ── Phase « écriture » (scripts non-latins, avant la phase passive) ──────────
    ("ecriture_decouverte", "writing", "ecriture", "Découverte de l'écriture",
     "Présentation d'un lot de lettres/signes du système d'écriture, leur son et des mots-exemples.",
     "writing"),
    ("ecriture_lecture", "writing", "ecriture", "Lecture des signes",
     "Reconnaître et translittérer des signes/mots dans le système d'écriture cible.",
     "writing"),
    ("ecriture_dictee", "writing", "ecriture", "Dictée de signes",
     "Écrire les signes/mots entendus, segment par segment, dans le système d'écriture cible.",
     "dictation"),
    # ── Types interactifs (correction côté client, robustes hors-ligne) ──────────
    # Densifient la phase de manipulation : la marche manquante entre reconnaître
    # et produire. 4 render_kinds neufs (cloze/ordering/matching/transform).
    ("completion_choix", "passive", "vocabulaire", "Complétion (banque de mots)",
     "Compléter des phrases à trous en piochant le bon mot dans une banque (avec distracteurs).",
     "cloze"),
    ("cloze_libre", "active", "production_ecrite", "Complétion libre",
     "Compléter des phrases à trous en saisissant librement le mot manquant.",
     "cloze"),
    ("remise_en_ordre", "passive", "comprehension_ecrite", "Remise en ordre",
     "Remettre les mots d'une phrase mélangée dans le bon ordre.",
     "ordering"),
    ("construction_phrase", "active", "production_ecrite", "Construction de phrase",
     "Construire une phrase en assemblant les fragments proposés.",
     "ordering"),
    ("appariement", "passive", "vocabulaire", "Appariement",
     "Relier chaque mot à sa traduction (rappel lexical rapide).",
     "matching"),
    ("transformation", "active", "grammaire_contexte", "Transformation",
     "Transformer une phrase (temps, nombre, genre, forme) selon une consigne grammaticale.",
     "transform"),
]

# Maps dérivés (source de vérité unique = SESSION_TYPES_SEED), pour le dispatch
# côté services/LLM sans relire la base dans le worker.
SESSION_TYPE_RENDER_KIND: dict[str, str] = {t[0]: t[5] for t in SESSION_TYPES_SEED}
SESSION_TYPE_LABEL: dict[str, str] = {t[0]: t[3] for t in SESSION_TYPES_SEED}
DEFAULT_SESSION_TYPE = "dialogue_ecoute"


def seed_session_types() -> None:
    """Pose/rafraîchit le catalogue statique des types de session.

    Idempotent : INSERT OR REPLACE de toutes les lignes à chaque démarrage. Aucune
    donnée utilisateur ici, donc on peut écraser sans risque pour synchroniser
    le catalogue avec le code.
    """
    conn = get_connection()
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO lang_session_types
               (code, phase, skill, label, description, render_kind)
               VALUES (?, ?, ?, ?, ?, ?)""",
            SESSION_TYPES_SEED,
        )
    logger.info("Catalogue des types de session seedé (%d types)", len(SESSION_TYPES_SEED))


def get_session_types_for_phase(phase: str) -> list[dict]:
    """Types jouables pour une phase donnée (+ ceux marqués 'any')."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM lang_session_types WHERE phase=? OR phase='any' ORDER BY code",
        (phase,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_session_type(code: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM lang_session_types WHERE code=?", (code,)
    ).fetchone()
    return dict(row) if row else None


def log_sequencer_decision(
    profile_id: int, session_n: int, chosen_type: str, reason: str
) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO lang_sequencer_log (profile_id, session_n, chosen_type, reason)
               VALUES (?, ?, ?, ?)""",
            (profile_id, session_n, chosen_type, reason),
        )


# ── Erreurs ───────────────────────────────────────────────────────────────────

def save_lang_error(
    profile_id: int, lesson_n: int, error_type: str, word: str, context: str
) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO lang_errors (profile_id, lesson_n, error_type, word, context)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(profile_id, word, error_type)
               DO UPDATE SET count=count+1, last_seen=datetime('now'), context=excluded.context""",
            (profile_id, lesson_n, error_type, word, context),
        )


def get_lang_errors_for_revision(profile_id: int, limit: int = 10) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT word, error_type, context, count FROM lang_errors
           WHERE profile_id=? ORDER BY count DESC, last_seen DESC LIMIT ?""",
        (profile_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Cache d'exercices ─────────────────────────────────────────────────────────

def get_exercises_cache(
    profile_id: int, lesson_n: int, exercise_type: str
) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        """SELECT content_json FROM lang_exercises_cache
           WHERE profile_id=? AND lesson_n=? AND exercise_type=?""",
        (profile_id, lesson_n, exercise_type),
    ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["content_json"])
    except Exception:
        return None


def save_exercises_cache(
    profile_id: int, lesson_n: int, exercise_type: str, content: dict
) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO lang_exercises_cache
               (profile_id, lesson_n, exercise_type, content_json)
               VALUES (?, ?, ?, ?)""",
            (
                profile_id,
                lesson_n,
                exercise_type,
                json.dumps(content, ensure_ascii=False),
            ),
        )


# ── Séances (lang_lessons) ────────────────────────────────────────────────────
#
# Une séance = 10 exercices joués en séquence (arc 4 temps). Chaque exercice est
# par ailleurs tracé dans lang_sessions (grain compétence). Le contenu de chaque
# exercice est généré juste-à-temps puis mémorisé dans lang_exercises_cache, clé
# (profile_id, lesson_id, slot_index) — on réutilise les colonnes existantes
# (lesson_n porte lesson_id, exercise_type porte slot_index) pour éviter une
# migration : ce cache n'est utilisé QUE par le flux séance.

def create_lang_lesson(
    profile_id: int,
    lesson_n: int,
    *,
    theme: str,
    dialogue: list | dict | None,
    plan: list | dict,
    level: str,
) -> int:
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO lang_lessons
               (profile_id, lesson_n, theme, dialogue_json, plan_json, level, status)
               VALUES (?, ?, ?, ?, ?, ?, 'in_progress')""",
            (
                profile_id,
                lesson_n,
                theme or "",
                json.dumps(dialogue, ensure_ascii=False) if dialogue is not None else None,
                json.dumps(plan, ensure_ascii=False),
                level or "A1",
            ),
        )
    return int(cur.lastrowid)


def get_lang_lesson(lesson_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM lang_lessons WHERE id=?", (lesson_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    for field, key, default in [("dialogue_json", "dialogue", None), ("plan_json", "plan", [])]:
        raw = d.pop(field, None)
        try:
            d[key] = json.loads(raw) if raw else default
        except Exception:
            d[key] = default
    return d


def complete_lang_lesson(lesson_id: int, *, score: float, duration_s: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """UPDATE lang_lessons
               SET status='completed', score=?, duration_s=?, completed_at=datetime('now')
               WHERE id=?""",
            (float(score or 0.0), int(duration_s or 0), lesson_id),
        )


def get_lang_lesson_count(profile_id: int, *, completed_only: bool = True) -> int:
    conn = get_connection()
    sql = "SELECT COUNT(*) AS n FROM lang_lessons WHERE profile_id=?"
    if completed_only:
        sql += " AND status='completed'"
    row = conn.execute(sql, (profile_id,)).fetchone()
    return int(row["n"]) if row else 0


def save_lang_exercise(
    profile_id: int,
    lesson_id: int,
    lesson_n: int,
    slot_index: int,
    temps: str,
    session_type: str,
    score: float,
) -> None:
    """Trace un exercice joué dans lang_sessions (grain compétence + rattachement séance)."""
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO lang_sessions
               (profile_id, lesson_n, duration_s, score, session_type, lesson_id, slot_index, temps)
               VALUES (?, ?, 0, ?, ?, ?, ?, ?)""",
            (profile_id, lesson_n, float(score or 0.0), session_type, lesson_id, slot_index, temps),
        )


# ── Signaux de calibration de difficulté (déterministes, lus, jamais LLM) ──────

def get_flashcard_count(profile_id: int, language: str) -> int:
    """Nombre de flashcards acquises pour cette langue (richesse lexicale)."""
    conn = get_connection()
    row = conn.execute(
        """SELECT COUNT(*) AS n FROM flashcards
           WHERE language=? AND user_id=(SELECT user_id FROM lang_profiles WHERE id=?)""",
        (language, profile_id),
    ).fetchone()
    return int(row["n"]) if row else 0


def get_due_flashcards_for_language(
    profile_id: int, language: str, limit: int = 8
) -> list[dict]:
    """Cartes de cette langue dues à la révision (répétition espacée), urgentes d'abord.

    Réutilise la logique d'échéance du SR global (colonne `due_at` de `flashcards`),
    filtrée par langue. C'est la source du « pont SR → séance » : l'ancrage et la
    clôture repêchent activement les cartes qui commencent à s'effacer (2e vague
    Assimil), pas seulement celles où l'apprenant s'est trompé. Aucune dépendance LLM.

    Recto = français (`front`), verso = langue cible (`back`) — convention des
    flashcards de vocabulaire (cf. create_lang_vocab_flashcards).
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, front, back, interval_days, due_at
           FROM flashcards
           WHERE language=?
             AND user_id=(SELECT user_id FROM lang_profiles WHERE id=?)
             AND due_at IS NOT NULL
             AND due_at <= datetime('now', 'localtime')
           ORDER BY due_at ASC
           LIMIT ?""",
        (language, profile_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_recent_flashcards_for_language(
    profile_id: int, language: str, limit: int = 5
) -> list[dict]:
    """Cartes les plus récentes de cette langue (complète le warm-up si peu sont dues)."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, front, back
           FROM flashcards
           WHERE language=?
             AND user_id=(SELECT user_id FROM lang_profiles WHERE id=?)
           ORDER BY created_at DESC, id DESC
           LIMIT ?""",
        (language, profile_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def _fold(text: str) -> str:
    """Repli accent-insensible/minuscule pour rapprocher un item d'une carte SR."""
    from utils.text import fold

    return fold(text)


def find_lang_flashcard_id(profile_id: int, language: str, text: str) -> int | None:
    """Retrouve l'id d'une carte de cette langue par son recto OU verso (accent-folded).

    Sert au bouclage du pont SR : quand un item de révision issu d'une carte est
    réussi/raté en séance, on remonte à la carte pour repousser/rapprocher son
    échéance. Sans ce bouclage, réviser en séance ne « compterait » pas pour la
    mémoire long terme.
    """
    needle = _fold(text)
    if not needle:
        return None
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, front, back FROM flashcards
           WHERE language=? AND user_id=(SELECT user_id FROM lang_profiles WHERE id=?)""",
        (language, profile_id),
    ).fetchall()
    for r in rows:
        if _fold(r["front"]) == needle or _fold(r["back"]) == needle:
            return int(r["id"])
    return None


def get_recent_lesson_score_avg(profile_id: int, window: int = 5) -> float:
    """Moyenne glissante (0-1) des scores des `window` dernières séances terminées.

    Neutre (0.5) s'il n'y a pas encore d'historique : ni poussée, ni recul. Les
    scores sont stockés sur 0-100 dans lang_lessons -> normalisés ici en 0-1.
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT score FROM lang_lessons
           WHERE profile_id=? AND status='completed' AND score IS NOT NULL
           ORDER BY completed_at DESC, id DESC LIMIT ?""",
        (profile_id, window),
    ).fetchall()
    if not rows:
        return 0.5
    return (sum(r["score"] for r in rows) / len(rows)) / 100.0


def get_last_lesson_theme(profile_id: int) -> str | None:
    """Thème de la dernière séance (terminée ou en cours) — fil rouge entre séances."""
    conn = get_connection()
    row = conn.execute(
        """SELECT theme FROM lang_lessons
           WHERE profile_id=? AND theme IS NOT NULL AND theme != ''
           ORDER BY id DESC LIMIT 1""",
        (profile_id,),
    ).fetchone()
    return row["theme"] if row and row["theme"] else None


def get_last_completed_lesson_difficulty(profile_id: int) -> int | None:
    """Indice de difficulté de la dernière séance terminée (lu dans plan_json)."""
    conn = get_connection()
    row = conn.execute(
        """SELECT plan_json FROM lang_lessons
           WHERE profile_id=? AND status='completed'
           ORDER BY completed_at DESC, id DESC LIMIT 1""",
        (profile_id,),
    ).fetchone()
    if not row or not row["plan_json"]:
        return None
    try:
        d = json.loads(row["plan_json"]).get("difficulty_target")
        return int(d) if d is not None else None
    except Exception:
        return None


def get_lesson_exercise_cache(profile_id: int, lesson_id: int, slot_index: int) -> dict | None:
    return get_exercises_cache(profile_id, lesson_id, str(slot_index))


def save_lesson_exercise_cache(
    profile_id: int, lesson_id: int, slot_index: int, content: dict
) -> None:
    save_exercises_cache(profile_id, lesson_id, str(slot_index), content)


# ── Progression ───────────────────────────────────────────────────────────────

def get_lang_progress(profile_id: int) -> dict:
    conn = get_connection()
    rows = conn.execute(
        "SELECT lesson_n, duration_s, score, date FROM lang_sessions "
        "WHERE profile_id=? ORDER BY date",
        (profile_id,),
    ).fetchall()
    sessions = [dict(r) for r in rows]
    # Séances terminées (grain Assimil) : c'est la métrique affichée sur le profil.
    lessons = conn.execute(
        "SELECT score FROM lang_lessons WHERE profile_id=? AND status='completed'",
        (profile_id,),
    ).fetchall()
    lesson_scores = [r["score"] for r in lessons if r["score"] is not None]
    avg_lesson = sum(lesson_scores) / len(lesson_scores) if lesson_scores else 0.0
    avg_score = (
        sum(s["score"] for s in sessions if s["score"] is not None) / len(sessions)
        if sessions else 0.0
    )
    return {
        "sessions": sessions,
        "total_sessions": len(sessions),
        "total_lessons": len(lessons),
        "avg_score": avg_lesson if lessons else avg_score,
        "avg_exercise_score": avg_score,
    }
