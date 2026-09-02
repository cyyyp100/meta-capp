# db/migrations.py — Migrations SQLite idempotentes
from __future__ import annotations

import logging

from config.settings import DB_SCHEMA_VERSION

logger = logging.getLogger("DB.migrations")


TARGET_SCHEMA_VERSION = DB_SCHEMA_VERSION


def run_migrations(conn) -> None:
    """Applique les migrations nécessaires jusqu'à la version cible."""
    current = _current_version(conn)
    if current < 2 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v2(conn)
        _set_version(conn, 2)
        current = 2

    if current < 3 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v3(conn)
        _set_version(conn, 3)
        current = 3

    if current < 4 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v4(conn)
        _set_version(conn, 4)
        current = 4

    if current < 5 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v5(conn)
        _set_version(conn, 5)
        current = 5

    if current < 6 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v6(conn)
        _set_version(conn, 6)
        current = 6

    if current < 7 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v7(conn)
        _set_version(conn, 7)
        current = 7

    if current < 8 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v8(conn)
        _set_version(conn, 8)
        current = 8

    if current < 9 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v9(conn)
        _set_version(conn, 9)
        current = 9

    if current < 10 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v10(conn)
        _set_version(conn, 10)
        current = 10

    if current < 11 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v11(conn)
        _set_version(conn, 11)
        current = 11

    if current < 12 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v12(conn)
        _set_version(conn, 12)
        current = 12

    if current < 13 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v13(conn)
        _set_version(conn, 13)
        current = 13

    if current < 14 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v14(conn)
        _set_version(conn, 14)
        current = 14

    if current < 15 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v15(conn)
        _set_version(conn, 15)
        current = 15

    if current < 16 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v16(conn)
        _set_version(conn, 16)
        current = 16

    if current < 17 <= TARGET_SCHEMA_VERSION:
        # v17 est réservé : la branche `refonte` a posé ce numéro avec un autre
        # contenu sur les bases existantes. Aucune action ici.
        _set_version(conn, 17)
        current = 17

    if current < 18 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v18(conn)
        _set_version(conn, 18)
        current = 18

    if current < 19 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v19(conn)
        _set_version(conn, 19)
        current = 19

    if current < 20 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v20(conn)
        _set_version(conn, 20)
        current = 20

    if current < 21 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v21(conn)
        _set_version(conn, 21)
        current = 21

    if current < 22 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v22(conn)
        _set_version(conn, 22)
        current = 22

    if current < 23 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v23(conn)
        _set_version(conn, 23)
        current = 23

    if current < 24 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v24(conn)
        _set_version(conn, 24)
        current = 24

    if current < 25 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v25(conn)
        _set_version(conn, 25)
        current = 25

    if current < 26 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v26(conn)
        _set_version(conn, 26)
        current = 26

    if current < 27 <= TARGET_SCHEMA_VERSION:
        _migrate_to_v27(conn)
        _set_version(conn, 27)
        current = 27

    if current < TARGET_SCHEMA_VERSION:
        _set_version(conn, TARGET_SCHEMA_VERSION)


def _current_version(conn) -> int:
    row = conn.execute(
        "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
    ).fetchone()
    return int(row["version"]) if row else 1


def _set_version(conn, version: int) -> None:
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    logger.info("Version schéma SQLite : v%s", version)


def _migrate_to_v2(conn) -> None:
    logger.info("Migration SQLite v2 démarrée")

    _ensure_column(conn, "documents", "doc_type", "TEXT DEFAULT 'book'")
    _ensure_column(conn, "questions", "llm_model", "TEXT")
    _ensure_column(conn, "reading_sessions", "user_id", "INTEGER DEFAULT 1")
    _ensure_column(conn, "reading_sessions", "duration_s", "INTEGER")
    _ensure_column(conn, "reading_sessions", "chapters_completed", "TEXT")

    _ensure_v2_tables(conn)
    logger.info("Migration SQLite v2 terminée")


def _ensure_column(conn, table: str, column: str, definition: str) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        logger.info("Colonne SQLite ajoutée : %s.%s", table, column)


def _migrate_to_v3(conn) -> None:
    logger.info("Migration SQLite v3 démarrée")
    _ensure_column(conn, "questions", "session_id", "INTEGER")
    _ensure_column(conn, "questions", "chapter_id", "INTEGER")
    _ensure_column(conn, "questions", "question_type", "TEXT")
    _ensure_column(conn, "questions", "choices_json", "TEXT")
    logger.info("Migration SQLite v3 terminée")


def _migrate_to_v4(conn) -> None:
    logger.info("Migration SQLite v4 démarrée")
    renames = (
        ("text_comprehension", "context_comprehension"),
        ("space_vision", "retention"),
        ("math", "curiosity"),
    )
    for old, new in renames:
        _rename_column_if_exists(conn, "metacog_profile", old, new)

    _ensure_column(conn, "metacog_profile", "context_comprehension", "REAL DEFAULT 50.0")
    _ensure_column(conn, "metacog_profile", "retention", "REAL DEFAULT 50.0")
    _ensure_column(conn, "metacog_profile", "curiosity", "REAL DEFAULT 50.0")
    _rename_criterion_values(conn, "metacog_history", "criterion", renames)
    _rename_criterion_values(conn, "session_gauges", "gauge_name", renames)
    logger.info("Migration SQLite v4 terminée")


def _migrate_to_v5(conn) -> None:
    logger.info("Migration SQLite v5 démarrée")
    _ensure_column(conn, "metacog_profile", "meta_cognition", "REAL DEFAULT 50.0")
    logger.info("Migration SQLite v5 terminée")


def _migrate_to_v6(conn) -> None:
    logger.info("Migration SQLite v6 démarrée")
    _ensure_column(conn, "flashcards", "assets_json", "TEXT")
    logger.info("Migration SQLite v6 terminée")


def _migrate_to_v7(conn) -> None:
    logger.info("Migration SQLite v7 démarrée")
    _ensure_column(conn, "user", "speed_ms", "INTEGER DEFAULT 500")
    logger.info("Migration SQLite v7 terminée")


def _migrate_to_v8(conn) -> None:
    logger.info("Migration SQLite v8 démarrée")
    _ensure_column(conn, "documents", "subject", "TEXT")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS subject_profile (
            user_id         INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
            subject         TEXT NOT NULL,
            level           REAL DEFAULT 50.0,
            questions_count INTEGER DEFAULT 0,
            correct_count   INTEGER DEFAULT 0,
            updated_at      DATETIME DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, subject)
        );
        CREATE INDEX IF NOT EXISTS idx_subject_profile_user ON subject_profile(user_id);
        """
    )
    logger.info("Migration SQLite v8 terminée")


def _migrate_to_v9(conn) -> None:
    logger.info("Migration SQLite v9 démarrée")
    _ensure_subject_history_table(conn)
    logger.info("Migration SQLite v9 terminée")


def _rename_column_if_exists(conn, table: str, old: str, new: str) -> None:
    columns = _table_columns(conn, table)
    if old not in columns:
        return
    if new in columns:
        logger.warning("Renommage ignoré : %s.%s et %s.%s existent déjà", table, old, table, new)
        return
    conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
    logger.info("Colonne SQLite renommée : %s.%s -> %s", table, old, new)


def _rename_criterion_values(conn, table: str, column: str, renames: tuple[tuple[str, str], ...]) -> None:
    columns = _table_columns(conn, table)
    if column not in columns:
        return
    for old, new in renames:
        conn.execute(f"UPDATE {table} SET {column}=? WHERE {column}=?", (new, old))


def _table_columns(conn, table: str) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _ensure_v2_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS user (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            speed_ms    INTEGER DEFAULT 500,
            created_at  DATETIME DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS answers (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id        INTEGER REFERENCES questions(id) ON DELETE CASCADE,
            user_id            INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
            session_id         INTEGER REFERENCES reading_sessions(id) ON DELETE SET NULL,
            answer_text        TEXT NOT NULL,
            verdict            TEXT,
            feedback           TEXT,
            completion         TEXT,
            hint               TEXT,
            response_time_ms   INTEGER,
            length_chars       INTEGER,
            length_words       INTEGER,
            metacog_signals    TEXT,
            attempt_number     INTEGER DEFAULT 1,
            answered_at        DATETIME DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS session_gauges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL REFERENCES reading_sessions(id) ON DELETE CASCADE,
            t           REAL NOT NULL,
            gauge_name  TEXT NOT NULL,
            value       REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS metacog_profile (
            user_id             INTEGER PRIMARY KEY REFERENCES user(id) ON DELETE CASCADE,
            context_comprehension REAL DEFAULT 50.0,
            creativity          REAL DEFAULT 50.0,
            retention           REAL DEFAULT 50.0,
            curiosity           REAL DEFAULT 50.0,
            meta_cognition      REAL DEFAULT 50.0,
            attention           REAL DEFAULT 50.0,
            sessions_count      INTEGER DEFAULT 0,
            updated_at          DATETIME DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS metacog_history (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
            session_id     INTEGER REFERENCES reading_sessions(id) ON DELETE SET NULL,
            criterion      TEXT NOT NULL,
            value_before   REAL NOT NULL,
            value_after    REAL NOT NULL,
            session_score  REAL NOT NULL,
            alpha          REAL NOT NULL,
            recorded_at    DATETIME DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS flashcards (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
            question_id    INTEGER REFERENCES questions(id) ON DELETE SET NULL,
            document_id    INTEGER REFERENCES documents(id) ON DELETE SET NULL,
            chapter_id     INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
            front          TEXT NOT NULL,
            back           TEXT NOT NULL,
            tags           TEXT,
            assets_json    TEXT,
            difficulty     INTEGER DEFAULT 2,
            source         TEXT DEFAULT 'auto',
            last_reviewed  DATETIME,
            review_count   INTEGER DEFAULT 0,
            last_verdict   TEXT,
            created_at     DATETIME DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rephrasing (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id       INTEGER REFERENCES questions(id) ON DELETE SET NULL,
            session_id        INTEGER REFERENCES reading_sessions(id) ON DELETE SET NULL,
            angle             TEXT,
            rephrased_text    TEXT NOT NULL,
            note              TEXT,
            created_at        DATETIME DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS session_reflections (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER REFERENCES reading_sessions(id) ON DELETE CASCADE,
            user_id         INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
            question_text   TEXT NOT NULL,
            answer_text     TEXT NOT NULL,
            question_order  INTEGER DEFAULT 0,
            created_at      DATETIME DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_answers_session ON answers(session_id);
        CREATE INDEX IF NOT EXISTS idx_answers_question ON answers(question_id);
        CREATE INDEX IF NOT EXISTS idx_session_gauges_session ON session_gauges(session_id);
        CREATE INDEX IF NOT EXISTS idx_flashcards_user ON flashcards(user_id);
        CREATE INDEX IF NOT EXISTS idx_metacog_history_user ON metacog_history(user_id);
        CREATE INDEX IF NOT EXISTS idx_session_reflections_session ON session_reflections(session_id);
        """
    )


def _migrate_to_v10(conn) -> None:
    logger.info("Migration SQLite v10 démarrée")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS login_streak (
            user_id    INTEGER PRIMARY KEY REFERENCES user(id) ON DELETE CASCADE,
            streak     INTEGER DEFAULT 1,
            last_login TEXT NOT NULL
        );
        """
    )
    logger.info("Migration SQLite v10 terminée")


def _migrate_to_v11(conn) -> None:
    logger.info("Migration SQLite v11 démarrée")
    _ensure_column(conn, "questions", "source_context", "TEXT")
    logger.info("Migration SQLite v11 terminée")


def _migrate_to_v12(conn) -> None:
    logger.info("Migration SQLite v12 démarrée")
    _ensure_column(conn, "questions", "source_block_id", "TEXT")
    logger.info("Migration SQLite v12 terminée")


def _migrate_to_v13(conn) -> None:
    logger.info("Migration SQLite v13 démarrée")
    _ensure_column(conn, "pages_cache", "enrich_assets", "INTEGER DEFAULT 1")
    _ensure_column(conn, "pages_cache", "page_plan_json", "TEXT")
    _ensure_column(conn, "pages_cache", "layout_risk_json", "TEXT")
    _ensure_column(conn, "pages_cache", "quality_score", "REAL")
    _ensure_column(conn, "pages_cache", "warnings_json", "TEXT")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS document_index (
            doc_id                   INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
            pdf_hash                 TEXT NOT NULL,
            opendataloader_status    TEXT NOT NULL DEFAULT 'pending',
            detected_document_type   TEXT,
            chapters_json            TEXT,
            global_assets_json       TEXT,
            backend_report_json      TEXT,
            created_at               DATETIME DEFAULT (datetime('now')),
            updated_at               DATETIME DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS llm_pdf_cache (
            cache_key    TEXT NOT NULL,
            task_type    TEXT NOT NULL,
            input_hash   TEXT NOT NULL,
            output_json  TEXT NOT NULL,
            confidence   REAL,
            model        TEXT,
            created_at   DATETIME DEFAULT (datetime('now')),
            PRIMARY KEY (cache_key, task_type)
        );

        CREATE TABLE IF NOT EXISTS asset_cache (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id       INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_number  INTEGER NOT NULL,
            block_id     TEXT,
            asset_type   TEXT NOT NULL,
            image_path   TEXT NOT NULL,
            bbox         TEXT,
            source       TEXT,
            confidence   REAL,
            created_at   DATETIME DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_document_index_hash ON document_index(pdf_hash);
        CREATE INDEX IF NOT EXISTS idx_llm_pdf_cache_task ON llm_pdf_cache(task_type);
        CREATE INDEX IF NOT EXISTS idx_asset_cache_doc_page ON asset_cache(doc_id, page_number);
        """
    )
    logger.info("Migration SQLite v13 terminée")


def _migrate_to_v14(conn) -> None:
    logger.info("Migration SQLite v14 démarrée")
    _ensure_column(conn, "user", "lang", "TEXT NOT NULL DEFAULT 'fr'")
    logger.info("Migration SQLite v14 terminée")


def _migrate_to_v15(conn) -> None:
    logger.info("Migration SQLite v15 démarrée")
    _ensure_column(conn, "flashcards", "session_id", "INTEGER REFERENCES reading_sessions(id) ON DELETE SET NULL")
    logger.info("Migration SQLite v15 terminée")


def _migrate_to_v16(conn) -> None:
    logger.info("Migration SQLite v16 démarrée")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS lang_profiles (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
            language       TEXT NOT NULL,
            current_lesson INTEGER DEFAULT 1,
            phase          TEXT DEFAULT 'passive',
            created_at     DATETIME DEFAULT (datetime('now')),
            last_session   DATETIME,
            UNIQUE(user_id, language)
        );

        CREATE TABLE IF NOT EXISTS lang_curriculum (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            language       TEXT NOT NULL,
            lesson_n       INTEGER NOT NULL,
            theme          TEXT NOT NULL,
            grammar_point  TEXT,
            vocabulary_json TEXT,
            level          TEXT DEFAULT 'A1',
            reuses_json    TEXT,
            generated_at   DATETIME DEFAULT (datetime('now')),
            UNIQUE(language, lesson_n)
        );

        CREATE TABLE IF NOT EXISTS lang_lesson_cache (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id      INTEGER NOT NULL REFERENCES lang_profiles(id) ON DELETE CASCADE,
            lesson_n        INTEGER NOT NULL,
            dialogue_json   TEXT,
            notes_json      TEXT,
            vocabulary_json TEXT,
            generated_at    DATETIME DEFAULT (datetime('now')),
            UNIQUE(profile_id, lesson_n)
        );

        CREATE TABLE IF NOT EXISTS lang_sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id  INTEGER NOT NULL REFERENCES lang_profiles(id) ON DELETE CASCADE,
            lesson_n    INTEGER NOT NULL,
            date        DATETIME DEFAULT (datetime('now')),
            duration_s  INTEGER,
            score       REAL
        );

        CREATE TABLE IF NOT EXISTS lang_errors (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id  INTEGER NOT NULL REFERENCES lang_profiles(id) ON DELETE CASCADE,
            lesson_n    INTEGER NOT NULL,
            error_type  TEXT,
            word        TEXT,
            context     TEXT,
            count       INTEGER DEFAULT 1,
            last_seen   DATETIME DEFAULT (datetime('now')),
            UNIQUE(profile_id, word, error_type)
        );

        CREATE TABLE IF NOT EXISTS lang_exercises_cache (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id     INTEGER NOT NULL REFERENCES lang_profiles(id) ON DELETE CASCADE,
            lesson_n       INTEGER NOT NULL,
            exercise_type  TEXT NOT NULL,
            content_json   TEXT,
            generated_at   DATETIME DEFAULT (datetime('now')),
            UNIQUE(profile_id, lesson_n, exercise_type)
        );

        CREATE INDEX IF NOT EXISTS idx_lang_profiles_user    ON lang_profiles(user_id);
        CREATE INDEX IF NOT EXISTS idx_lang_curriculum_lang  ON lang_curriculum(language);
        CREATE INDEX IF NOT EXISTS idx_lang_lesson_profile   ON lang_lesson_cache(profile_id);
        CREATE INDEX IF NOT EXISTS idx_lang_sessions_profile ON lang_sessions(profile_id);
        CREATE INDEX IF NOT EXISTS idx_lang_errors_profile   ON lang_errors(profile_id);
        CREATE INDEX IF NOT EXISTS idx_lang_exercises_profile ON lang_exercises_cache(profile_id);
    """)
    logger.info("Migration SQLite v16 terminée")


def _migrate_to_v18(conn) -> None:
    """Lecteur scroll libre + bulle assistant : préférences utilisateur et index.

    Idempotente : certaines bases v17 viennent d'une autre branche.
    """
    logger.info("Migration SQLite v18 démarrée")
    _ensure_column(conn, "user", "assistant_mode", "TEXT NOT NULL DEFAULT 'normal'")
    _ensure_column(conn, "user", "bubble_rel_x", "REAL")
    _ensure_column(conn, "user", "bubble_rel_y", "REAL")
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_questions_session ON questions(session_id);
        CREATE INDEX IF NOT EXISTS idx_questions_scope ON questions(scope_type);
        """
    )
    logger.info("Migration SQLite v18 terminée")


def _migrate_to_v19(conn) -> None:
    """Répétition espacée des flashcards + persistance du dwell par page."""
    logger.info("Migration SQLite v19 démarrée")
    _ensure_column(conn, "flashcards", "due_at", "DATETIME")
    _ensure_column(conn, "flashcards", "interval_days", "REAL DEFAULT 1.0")
    # Cartes existantes : dues immédiatement pour amorcer le cycle de révision.
    # Heure locale pour rester comparable aux échéances écrites par db.flashcards.
    conn.execute("UPDATE flashcards SET due_at = datetime('now', 'localtime') WHERE due_at IS NULL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS page_dwell (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL REFERENCES reading_sessions(id) ON DELETE CASCADE,
            page        INTEGER NOT NULL,
            dwell_s     REAL DEFAULT 0.0,
            visits      INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_page_dwell_session ON page_dwell(session_id);
        CREATE INDEX IF NOT EXISTS idx_flashcards_due ON flashcards(user_id, due_at);
        """
    )
    logger.info("Migration SQLite v19 terminée")


def _migrate_to_v20(conn) -> None:
    """Surlignages persistants du lecteur web (mémorisés entre sessions).

    Le texte surligné par l'étudiant est conservé en base : il réapparaît à la
    réouverture du PDF et enrichit le contexte transmis au LLM.
    """
    logger.info("Migration SQLite v20 démarrée")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS reader_highlights (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
            document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page         INTEGER NOT NULL,
            quote        TEXT NOT NULL,
            rects_json   TEXT NOT NULL,
            color        TEXT DEFAULT 'key',
            created_at   DATETIME DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_reader_highlights_doc ON reader_highlights(document_id);
        CREATE INDEX IF NOT EXISTS idx_reader_highlights_user_doc ON reader_highlights(user_id, document_id);
        """
    )
    logger.info("Migration SQLite v20 terminée")


def _migrate_to_v21(conn) -> None:
    """v21 : analyse générale de l'apprenant (texte rédigé par le LLM en fin de
    session) stockée sur le profil métacognitif et affichée sur la page profil."""
    logger.info("Migration SQLite v21 démarrée")
    _ensure_column(conn, "metacog_profile", "general_analysis", "TEXT")
    _ensure_column(conn, "metacog_profile", "general_analysis_updated_at", "DATETIME")
    logger.info("Migration SQLite v21 terminée")


def _migrate_to_v22(conn) -> None:
    """Séquenceur adaptatif de sessions de langue (méthode Assimil).

    Chaque session est désormais décidée et générée juste-à-temps : on mémorise
    le TYPE joué par session (anti-répétition + répartition des compétences), on
    pose le catalogue statique des types (jamais généré par LLM), et on trace les
    décisions du séquenceur. `lang_curriculum` n'est plus alimentée mais reste en
    base (pas de migration destructive). Le catalogue est seedé au démarrage par
    db.lang_db.seed_session_types (source de vérité côté code).
    """
    logger.info("Migration SQLite v22 démarrée")
    _ensure_column(conn, "lang_sessions", "session_type", "TEXT DEFAULT 'dialogue_ecoute'")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS lang_session_types (
            code         TEXT PRIMARY KEY,
            phase        TEXT NOT NULL,
            skill        TEXT NOT NULL,
            label        TEXT NOT NULL,
            description  TEXT,
            render_kind  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS lang_sequencer_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id  INTEGER REFERENCES lang_profiles(id) ON DELETE CASCADE,
            session_n   INTEGER,
            chosen_type TEXT,
            reason      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_lang_sequencer_profile ON lang_sequencer_log(profile_id);
        """
    )
    logger.info("Migration SQLite v22 terminée")


def _migrate_to_v23(conn) -> None:
    """Page « Brainstorming » : chat libre avec Gemma + mémoire par discussion.

    Chaque discussion garde l'historique complet de ses messages (réouvrable tel
    quel) PLUS un résumé glissant (`summary`) utilisé comme aperçu dans la liste
    et comme contexte compacté envoyé au LLM quand l'historique devient long.
    """
    logger.info("Migration SQLite v23 démarrée")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS brainstorm_discussions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id             INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
            title               TEXT NOT NULL,
            summary             TEXT DEFAULT '',
            summary_upto_msg_id INTEGER DEFAULT 0,
            message_count       INTEGER DEFAULT 0,
            created_at          DATETIME DEFAULT (datetime('now')),
            updated_at          DATETIME DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS brainstorm_messages (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            discussion_id INTEGER NOT NULL REFERENCES brainstorm_discussions(id) ON DELETE CASCADE,
            role          TEXT NOT NULL,
            content       TEXT NOT NULL,
            sources_json  TEXT,
            created_at    DATETIME DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_bm_discussion ON brainstorm_messages(discussion_id);
        """
    )
    logger.info("Migration SQLite v23 terminée")


def _migrate_to_v24(conn) -> None:
    """Séances de langue façon Assimil (10 exercices, arc 4 temps) + écriture + niveau.

    Une « séance » (`lang_lessons`) regroupe désormais 10 exercices joués en
    séquence sur une page dédiée. Chaque exercice reste tracé dans `lang_sessions`
    (au grain compétence, pour le séquenceur) mais rattaché à sa séance via
    `lesson_id`/`slot_index`/`temps`. Le profil porte un niveau CEFR explicite et un
    drapeau de test de niveau passé. Les flashcards gagnent une colonne `language`
    pour accueillir le vocabulaire auto-généré (recto FR / verso langue cible).
    Les nouveaux types de session (phase `writing`) sont posés par
    db.lang_db.seed_session_types au démarrage (source de vérité côté code).
    """
    logger.info("Migration SQLite v24 démarrée")
    # Séance = 10 exercices, arc 4 temps, thème/dialogue central partagé.
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS lang_lessons (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id    INTEGER NOT NULL REFERENCES lang_profiles(id) ON DELETE CASCADE,
            lesson_n      INTEGER NOT NULL,
            theme         TEXT DEFAULT '',
            dialogue_json TEXT,
            plan_json     TEXT,
            level         TEXT DEFAULT 'A1',
            status        TEXT DEFAULT 'in_progress',
            score         REAL,
            duration_s    INTEGER,
            created_at    DATETIME DEFAULT (datetime('now')),
            completed_at  DATETIME
        );
        CREATE INDEX IF NOT EXISTS idx_lang_lessons_profile ON lang_lessons(profile_id);
        """
    )
    # lang_sessions devient le record par EXERCICE, rattaché à sa séance.
    _ensure_column(conn, "lang_sessions", "lesson_id", "INTEGER REFERENCES lang_lessons(id) ON DELETE CASCADE")
    _ensure_column(conn, "lang_sessions", "slot_index", "INTEGER")
    _ensure_column(conn, "lang_sessions", "temps", "TEXT")
    # Profil : niveau CEFR explicite + test de niveau passé.
    _ensure_column(conn, "lang_profiles", "level", "TEXT DEFAULT 'A1'")
    _ensure_column(conn, "lang_profiles", "placement_done", "INTEGER DEFAULT 0")
    # Flashcards de vocabulaire de langue (NULL pour les flashcards PDF).
    _ensure_column(conn, "flashcards", "language", "TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_flashcards_lang ON flashcards(user_id, language)"
    )
    logger.info("Migration SQLite v24 terminée")


def _ensure_subject_history_table(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS subject_history (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
            session_id     INTEGER REFERENCES reading_sessions(id) ON DELETE SET NULL,
            subject        TEXT NOT NULL,
            value_before   REAL NOT NULL,
            value_after    REAL NOT NULL,
            source         TEXT DEFAULT 'session',
            recorded_at    DATETIME DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_subject_history_user ON subject_history(user_id);
        CREATE INDEX IF NOT EXISTS idx_subject_history_subject ON subject_history(user_id, subject);
        """
    )


def _migrate_to_v25(conn) -> None:
    """Documents servis en blocs de texte, ancrage texte des surlignages.

    - `reader_highlights.anchor_json` : ancrage TEXTE {block_id, start, end}
      des surlignages sur contenu servi en blocs (les rects points PDF restent
      la référence des documents raster).
    - `documents.content_hash` : sha256 tronqué du fichier — clé des caches.
    - `ocr_pages`, `app_settings` : tables créées ici et laissées vides dans
      cette édition ; conservées pour que la base reste compatible avec les
      bases existantes et rejouable de bout en bout.
    """
    logger.info("Migration SQLite v25 démarrée")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ocr_pages (
            document_id      INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page             INTEGER NOT NULL,
            markdown         TEXT NOT NULL DEFAULT '',
            blocks_json      TEXT NOT NULL DEFAULT '[]',
            model            TEXT,
            pipeline_version INTEGER DEFAULT 1,
            created_at       DATETIME DEFAULT (datetime('now')),
            PRIMARY KEY (document_id, page)
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    _ensure_column(conn, "documents", "ocr_status", "TEXT DEFAULT 'none'")
    _ensure_column(conn, "documents", "ocr_pages_done", "INTEGER DEFAULT 0")
    _ensure_column(conn, "documents", "ocr_error", "TEXT")
    _ensure_column(conn, "documents", "content_hash", "TEXT")
    _ensure_column(conn, "reader_highlights", "anchor_json", "TEXT")
    logger.info("Migration SQLite v25 terminée")


def _migrate_to_v26(conn) -> None:
    """Bibliothèque : dossiers utilisateur (arbre) + fiche LLM des documents.

    - `library_folders` porte l'arbre par auto-référence `parent_id`. SQLite ne
      sait pas exprimer l'acyclicité : le garde-fou est dans `services/folders`,
      la base n'assure que l'intégrité référentielle.
    - Politique de suppression, volontairement asymétrique : `ON DELETE CASCADE`
      sur `parent_id` (supprimer un dossier emporte son sous-arbre de dossiers),
      mais `ON DELETE SET NULL` sur `documents.folder_id` — un document n'est
      JAMAIS supprimé avec son dossier, il redevient « non classé ». C'est la
      seule politique acceptable pour un rangement fait à la souris.
    - `documents.auto_summary` / `keywords` / `digest_status` : sortie de la
      tâche LLM `document_digest` jouée à l'import, qui remplace
      `subject_detection`. `keywords` est un tableau JSON en TEXT, exactement
      comme `flashcards.tags`, et passe par la même normalisation (`utils.tags`).
    - Les documents déjà importés ne sont pas repris : ils restent en
      `digest_status='none'`, sans résumé, et restent trouvables par leur nom.
    """
    logger.info("Migration SQLite v26 démarrée")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS library_folders (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL DEFAULT 1 REFERENCES user(id) ON DELETE CASCADE,
            parent_id  INTEGER REFERENCES library_folders(id) ON DELETE CASCADE,
            name       TEXT NOT NULL,
            position   INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_library_folders_parent
            ON library_folders(user_id, parent_id, position);
        """
    )
    # `ALTER TABLE ... ADD COLUMN` avec clause REFERENCES : SQLite l'accepte tant
    # que la valeur par défaut est NULL — c'est le cas de folder_id.
    _ensure_column(
        conn, "documents", "folder_id",
        "INTEGER REFERENCES library_folders(id) ON DELETE SET NULL",
    )
    _ensure_column(conn, "documents", "auto_summary", "TEXT")
    _ensure_column(conn, "documents", "keywords", "TEXT DEFAULT '[]'")
    _ensure_column(conn, "documents", "digest_status", "TEXT DEFAULT 'none'")
    # Index posé après l'ALTER : la colonne n'existe pas avant.
    conn.executescript(
        "CREATE INDEX IF NOT EXISTS idx_documents_folder ON documents(folder_id);"
    )
    logger.info("Migration SQLite v26 terminée")


def _migrate_to_v27(conn) -> None:
    """Série d'ÉTUDE (et non de connexion) : record + tolérance d'un jour.

    Trois défauts de la v1 corrigés ensemble, parce qu'ils ne sont qu'un :

    - la série s'incrémentait dans un `GET /api/streak` — ouvrir l'app suffisait
      à « étudier ». Elle s'incrémente désormais à la FIN d'une session
      (`services/session.finalize_session`), d'où le renommage de la colonne :
      `last_login` mentait sur ce qu'elle mesure ;
    - aucun record n'était conservé : casser sa série effaçait toute trace de
      l'avoir tenue. `longest_streak` la garde ;
    - un seul jour manqué remettait le compteur à 1. La tolérance d'un jour vit
      dans `db/user.record_study_day`, pas ici — la base ne stocke que la date.

    `RENAME COLUMN` (SQLite ≥ 3.25) sous garde de `PRAGMA table_info` : rejouer
    la migration sur une base déjà migrée ne fait rien."""
    logger.info("Migration SQLite v27 démarrée")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(login_streak)")}
    if "last_study_day" not in columns and "last_login" in columns:
        with conn:
            conn.execute("ALTER TABLE login_streak RENAME COLUMN last_login TO last_study_day")
    _ensure_column(conn, "login_streak", "longest_streak", "INTEGER DEFAULT 0")
    # Une base existante a déjà une série en cours : elle EST le record connu.
    conn.execute(
        "UPDATE login_streak SET longest_streak=streak "
        "WHERE longest_streak IS NULL OR longest_streak < streak"
    )
    logger.info("Migration SQLite v27 terminée")
