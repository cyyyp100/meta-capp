-- Schéma de référence de Meta-Capp — GÉNÉRÉ, ne pas éditer à la main.
--
-- Forme réelle d'une base neuve après application des migrations
-- (config.settings.DB_SCHEMA_VERSION = 27).
-- Régénérer avec :  python scripts/dump_schema.py
--
-- Tables créées par une migration mais sans code lecteur ni écrivain
-- dans cette édition : llm_pdf_cache, ocr_pages.

CREATE TABLE answers (
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
CREATE INDEX idx_answers_question ON answers(question_id);
CREATE INDEX idx_answers_session ON answers(session_id);
CREATE TABLE app_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
CREATE TABLE asset_cache (
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
CREATE INDEX idx_asset_cache_doc_page ON asset_cache(doc_id, page_number);
CREATE TABLE brainstorm_discussions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    summary             TEXT DEFAULT '',
    summary_upto_msg_id INTEGER DEFAULT 0,
    message_count       INTEGER DEFAULT 0,
    created_at          DATETIME DEFAULT (datetime('now')),
    updated_at          DATETIME DEFAULT (datetime('now'))
);
CREATE TABLE brainstorm_messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    discussion_id INTEGER NOT NULL REFERENCES brainstorm_discussions(id) ON DELETE CASCADE,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    sources_json  TEXT,
    created_at    DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX idx_bm_discussion ON brainstorm_messages(discussion_id);
CREATE TABLE chapters (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    page_start   INTEGER NOT NULL,
    page_end     INTEGER,
    toc_level    INTEGER DEFAULT 1
);
CREATE INDEX idx_chapters_doc ON chapters(document_id);
CREATE TABLE document_index (
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
CREATE INDEX idx_document_index_hash ON document_index(pdf_hash);
CREATE TABLE documents (
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
, subject TEXT, ocr_status TEXT DEFAULT 'none', ocr_pages_done INTEGER DEFAULT 0, ocr_error TEXT, content_hash TEXT, folder_id INTEGER REFERENCES library_folders(id) ON DELETE SET NULL, auto_summary TEXT, keywords TEXT DEFAULT '[]', digest_status TEXT DEFAULT 'none');
CREATE INDEX idx_documents_folder ON documents(folder_id);
CREATE TABLE flashcards (
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
, language TEXT);
CREATE INDEX idx_flashcards_due ON flashcards(user_id, due_at);
CREATE INDEX idx_flashcards_lang ON flashcards(user_id, language);
CREATE INDEX idx_flashcards_user ON flashcards(user_id);
CREATE TABLE lang_curriculum (
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
CREATE INDEX idx_lang_curriculum_lang  ON lang_curriculum(language);
CREATE TABLE lang_errors (
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
CREATE INDEX idx_lang_errors_profile   ON lang_errors(profile_id);
CREATE TABLE lang_exercises_cache (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id     INTEGER NOT NULL REFERENCES lang_profiles(id) ON DELETE CASCADE,
            lesson_n       INTEGER NOT NULL,
            exercise_type  TEXT NOT NULL,
            content_json   TEXT,
            generated_at   DATETIME DEFAULT (datetime('now')),
            UNIQUE(profile_id, lesson_n, exercise_type)
        );
CREATE INDEX idx_lang_exercises_profile ON lang_exercises_cache(profile_id);
CREATE TABLE lang_lesson_cache (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id      INTEGER NOT NULL REFERENCES lang_profiles(id) ON DELETE CASCADE,
            lesson_n        INTEGER NOT NULL,
            dialogue_json   TEXT,
            notes_json      TEXT,
            vocabulary_json TEXT,
            generated_at    DATETIME DEFAULT (datetime('now')),
            UNIQUE(profile_id, lesson_n)
        );
CREATE INDEX idx_lang_lesson_profile   ON lang_lesson_cache(profile_id);
CREATE TABLE lang_lessons (
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
CREATE INDEX idx_lang_lessons_profile ON lang_lessons(profile_id);
CREATE TABLE lang_profiles (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
            language       TEXT NOT NULL,
            current_lesson INTEGER DEFAULT 1,
            phase          TEXT DEFAULT 'passive',
            created_at     DATETIME DEFAULT (datetime('now')),
            last_session   DATETIME, level TEXT DEFAULT 'A1', placement_done INTEGER DEFAULT 0,
            UNIQUE(user_id, language)
        );
CREATE INDEX idx_lang_profiles_user    ON lang_profiles(user_id);
CREATE TABLE lang_sequencer_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id  INTEGER REFERENCES lang_profiles(id) ON DELETE CASCADE,
            session_n   INTEGER,
            chosen_type TEXT,
            reason      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );
CREATE INDEX idx_lang_sequencer_profile ON lang_sequencer_log(profile_id);
CREATE TABLE lang_session_types (
            code         TEXT PRIMARY KEY,
            phase        TEXT NOT NULL,
            skill        TEXT NOT NULL,
            label        TEXT NOT NULL,
            description  TEXT,
            render_kind  TEXT NOT NULL
        );
CREATE TABLE lang_sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id  INTEGER NOT NULL REFERENCES lang_profiles(id) ON DELETE CASCADE,
            lesson_n    INTEGER NOT NULL,
            date        DATETIME DEFAULT (datetime('now')),
            duration_s  INTEGER,
            score       REAL
        , session_type TEXT DEFAULT 'dialogue_ecoute', lesson_id INTEGER REFERENCES lang_lessons(id) ON DELETE CASCADE, slot_index INTEGER, temps TEXT);
CREATE INDEX idx_lang_sessions_profile ON lang_sessions(profile_id);
CREATE TABLE library_folders (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL DEFAULT 1 REFERENCES user(id) ON DELETE CASCADE,
            parent_id  INTEGER REFERENCES library_folders(id) ON DELETE CASCADE,
            name       TEXT NOT NULL,
            position   INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT (datetime('now'))
        );
CREATE INDEX idx_library_folders_parent
            ON library_folders(user_id, parent_id, position);
CREATE TABLE llm_pdf_cache (
    cache_key    TEXT NOT NULL,
    task_type    TEXT NOT NULL,
    input_hash   TEXT NOT NULL,
    output_json  TEXT NOT NULL,
    confidence   REAL,
    model        TEXT,
    created_at   DATETIME DEFAULT (datetime('now')),
    PRIMARY KEY (cache_key, task_type)
);
CREATE INDEX idx_llm_pdf_cache_task ON llm_pdf_cache(task_type);
CREATE TABLE login_streak (
    user_id        INTEGER PRIMARY KEY REFERENCES user(id) ON DELETE CASCADE,
    streak         INTEGER DEFAULT 1,
    longest_streak INTEGER DEFAULT 0,
    -- Jour de la dernière SESSION terminée, pas de la dernière ouverture de
    -- l'app : c'est une série d'étude (cf. migration v27).
    last_study_day TEXT NOT NULL
);
CREATE TABLE metacog_history (
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
CREATE INDEX idx_metacog_history_user ON metacog_history(user_id);
CREATE TABLE metacog_profile (
    user_id             INTEGER PRIMARY KEY REFERENCES user(id) ON DELETE CASCADE,
    context_comprehension REAL DEFAULT 50.0,
    creativity          REAL DEFAULT 50.0,
    retention           REAL DEFAULT 50.0,
    curiosity           REAL DEFAULT 50.0,
    meta_cognition      REAL DEFAULT 50.0,
    attention           REAL DEFAULT 50.0,
    sessions_count      INTEGER DEFAULT 0,
    updated_at          DATETIME DEFAULT (datetime('now'))
, general_analysis TEXT, general_analysis_updated_at DATETIME);
CREATE TABLE ocr_pages (
            document_id      INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page             INTEGER NOT NULL,
            markdown         TEXT NOT NULL DEFAULT '',
            blocks_json      TEXT NOT NULL DEFAULT '[]',
            model            TEXT,
            pipeline_version INTEGER DEFAULT 1,
            created_at       DATETIME DEFAULT (datetime('now')),
            PRIMARY KEY (document_id, page)
        );
CREATE TABLE page_dwell (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES reading_sessions(id) ON DELETE CASCADE,
    page        INTEGER NOT NULL,
    dwell_s     REAL DEFAULT 0.0,
    visits      INTEGER DEFAULT 0
);
CREATE INDEX idx_page_dwell_session ON page_dwell(session_id);
CREATE TABLE pages_cache (
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
CREATE INDEX idx_pages_cache_doc ON pages_cache(document_id, page_number);
CREATE TABLE questions (
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
CREATE INDEX idx_questions_doc ON questions(document_id);
CREATE INDEX idx_questions_scope ON questions(scope_type);
CREATE INDEX idx_questions_session ON questions(session_id);
CREATE TABLE quiz_static_questions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question     TEXT NOT NULL,
    choices_json TEXT,
    answer       TEXT NOT NULL,
    category     TEXT DEFAULT 'culture',
    difficulty   INTEGER DEFAULT 2
);
CREATE TABLE reader_highlights (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
            document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page         INTEGER NOT NULL,
            quote        TEXT NOT NULL,
            rects_json   TEXT NOT NULL,
            color        TEXT DEFAULT 'key',
            created_at   DATETIME DEFAULT (datetime('now'))
        , anchor_json TEXT);
CREATE INDEX idx_reader_highlights_doc ON reader_highlights(document_id);
CREATE INDEX idx_reader_highlights_user_doc ON reader_highlights(user_id, document_id);
CREATE TABLE reading_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id      INTEGER DEFAULT 1 REFERENCES user(id) ON DELETE SET DEFAULT,
    started_at   DATETIME DEFAULT (datetime('now')),
    ended_at     DATETIME,
    pages_read   INTEGER DEFAULT 0,
    duration_s   INTEGER,
    chapters_completed TEXT
);
CREATE TABLE rephrasing (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id       INTEGER REFERENCES questions(id) ON DELETE SET NULL,
    session_id        INTEGER REFERENCES reading_sessions(id) ON DELETE SET NULL,
    angle             TEXT,
    rephrased_text    TEXT NOT NULL,
    note              TEXT,
    created_at        DATETIME DEFAULT (datetime('now'))
);
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY
);
CREATE TABLE session_gauges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES reading_sessions(id) ON DELETE CASCADE,
    t           REAL NOT NULL,
    gauge_name  TEXT NOT NULL,
    value       REAL NOT NULL
);
CREATE INDEX idx_session_gauges_session ON session_gauges(session_id);
CREATE TABLE session_reflections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER REFERENCES reading_sessions(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    question_text   TEXT NOT NULL,
    answer_text     TEXT NOT NULL,
    question_order  INTEGER DEFAULT 0,
    created_at      DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX idx_session_reflections_session ON session_reflections(session_id);
CREATE TABLE subject_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    session_id     INTEGER REFERENCES reading_sessions(id) ON DELETE SET NULL,
    subject        TEXT NOT NULL,
    value_before   REAL NOT NULL,
    value_after    REAL NOT NULL,
    source         TEXT DEFAULT 'session',
    recorded_at    DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX idx_subject_history_subject ON subject_history(user_id, subject);
CREATE INDEX idx_subject_history_user ON subject_history(user_id);
CREATE TABLE subject_profile (
    user_id         INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    subject         TEXT NOT NULL,
    level           REAL DEFAULT 50.0,
    questions_count INTEGER DEFAULT 0,
    correct_count   INTEGER DEFAULT 0,
    updated_at      DATETIME DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, subject)
);
CREATE INDEX idx_subject_profile_user ON subject_profile(user_id);
CREATE TABLE user (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    speed_ms       INTEGER DEFAULT 500,
    assistant_mode TEXT NOT NULL DEFAULT 'normal',
    bubble_rel_x   REAL,
    bubble_rel_y   REAL,
    created_at     DATETIME DEFAULT (datetime('now'))
, lang TEXT NOT NULL DEFAULT 'fr');
