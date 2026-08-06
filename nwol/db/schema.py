# db/schema.py — Création des tables SQLite
import logging
from db import get_connection
from db.migrations import run_migrations

logger = logging.getLogger("DB.schema")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS documents (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    path             TEXT UNIQUE NOT NULL,
    filename         TEXT NOT NULL,
    page_count       INTEGER,
    doc_type         TEXT DEFAULT 'book',
    last_page        INTEGER DEFAULT 1,
    last_opened      DATETIME,
    extraction_engine TEXT,
    has_toc          BOOLEAN DEFAULT 0,
    created_at       DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pages_cache (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number  INTEGER NOT NULL,
    engine       TEXT NOT NULL,
    blocks_json  TEXT NOT NULL,
    enrich_assets INTEGER DEFAULT 1,
    page_plan_json TEXT,
    layout_risk_json TEXT,
    quality_score REAL,
    warnings_json TEXT,
    extracted_at DATETIME DEFAULT (datetime('now')),
    UNIQUE(document_id, page_number, engine)
);

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

CREATE TABLE IF NOT EXISTS chapters (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    page_start   INTEGER NOT NULL,
    page_end     INTEGER,
    toc_level    INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    session_id    INTEGER REFERENCES reading_sessions(id) ON DELETE SET NULL,
    chapter_id    INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
    scope_type    TEXT NOT NULL,
    scope_label   TEXT,
    page_start    INTEGER,
    page_end      INTEGER,
    question_type TEXT,
    question      TEXT NOT NULL,
    source_context TEXT,
    source_block_id TEXT,
    choices_json  TEXT,
    answer        TEXT NOT NULL,
    llm_model     TEXT,
    created_at    DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reading_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id      INTEGER DEFAULT 1 REFERENCES user(id) ON DELETE SET DEFAULT,
    started_at   DATETIME DEFAULT (datetime('now')),
    ended_at     DATETIME,
    pages_read   INTEGER DEFAULT 0,
    duration_s   INTEGER,
    chapters_completed TEXT
);

CREATE TABLE IF NOT EXISTS user (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    speed_ms       INTEGER DEFAULT 500,
    assistant_mode TEXT NOT NULL DEFAULT 'normal',
    bubble_rel_x   REAL,
    bubble_rel_y   REAL,
    created_at     DATETIME DEFAULT (datetime('now'))
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
    session_id     INTEGER REFERENCES reading_sessions(id) ON DELETE SET NULL,
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
    due_at         DATETIME,
    interval_days  REAL DEFAULT 1.0,
    created_at     DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS page_dwell (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES reading_sessions(id) ON DELETE CASCADE,
    page        INTEGER NOT NULL,
    dwell_s     REAL DEFAULT 0.0,
    visits      INTEGER DEFAULT 0
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

CREATE INDEX IF NOT EXISTS idx_pages_cache_doc ON pages_cache(document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_document_index_hash ON document_index(pdf_hash);
CREATE INDEX IF NOT EXISTS idx_llm_pdf_cache_task ON llm_pdf_cache(task_type);
CREATE INDEX IF NOT EXISTS idx_asset_cache_doc_page ON asset_cache(doc_id, page_number);
CREATE INDEX IF NOT EXISTS idx_chapters_doc ON chapters(document_id);
CREATE INDEX IF NOT EXISTS idx_questions_doc ON questions(document_id);
CREATE INDEX IF NOT EXISTS idx_questions_session ON questions(session_id);
CREATE INDEX IF NOT EXISTS idx_questions_scope ON questions(scope_type);
CREATE INDEX IF NOT EXISTS idx_answers_session ON answers(session_id);
CREATE INDEX IF NOT EXISTS idx_answers_question ON answers(question_id);
CREATE INDEX IF NOT EXISTS idx_session_gauges_session ON session_gauges(session_id);
CREATE INDEX IF NOT EXISTS idx_flashcards_user ON flashcards(user_id);
CREATE INDEX IF NOT EXISTS idx_metacog_history_user ON metacog_history(user_id);
CREATE INDEX IF NOT EXISTS idx_session_reflections_session ON session_reflections(session_id);
-- idx_flashcards_due est créé par la migration v19 : sur une base existante,
-- la colonne due_at n'existe pas encore au moment où ce script s'exécute.
CREATE INDEX IF NOT EXISTS idx_page_dwell_session ON page_dwell(session_id);

CREATE TABLE IF NOT EXISTS quiz_static_questions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question     TEXT NOT NULL,
    choices_json TEXT,
    answer       TEXT NOT NULL,
    category     TEXT DEFAULT 'culture',
    difficulty   INTEGER DEFAULT 2
);

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

CREATE TABLE IF NOT EXISTS login_streak (
    user_id    INTEGER PRIMARY KEY REFERENCES user(id) ON DELETE CASCADE,
    streak     INTEGER DEFAULT 1,
    last_login TEXT NOT NULL
);

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


def initialize_schema() -> None:
    conn = get_connection()
    with conn:
        conn.executescript(SCHEMA_SQL)
        run_migrations(conn)
        _ensure_default_user(conn)
    from db.quiz_questions import seed_static_questions
    seed_static_questions()
    from db.lang_db import seed_session_types
    seed_session_types()
    logger.info("Schéma SQLite initialisé.")


def _ensure_default_user(conn) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO user (id, name) VALUES (1, ?)",
        ("Utilisateur",),
    )
    conn.execute(
        """INSERT OR IGNORE INTO metacog_profile
           (user_id, attention, context_comprehension, creativity, retention, curiosity, meta_cognition)
           VALUES (1, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0)"""
    )
