-- Tables shared by every agent.  Applied on agent-service startup (IF NOT EXISTS).
-- Timestamps: ISO-8601 UTC text, same as the Express app.

-- ============================================================
-- Library (written by the filing pipeline, read by everyone)
-- ============================================================
CREATE TABLE IF NOT EXISTS library_files (
    file_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id         INTEGER NOT NULL REFERENCES classes(class_id) ON DELETE CASCADE,
    original_name    TEXT NOT NULL,
    stored_path      TEXT NOT NULL,          -- relative to data/files/
    mime_type        TEXT,
    sha256           TEXT,
    -- labels from the filing pipeline
    title            TEXT,
    doc_type         TEXT,                   -- syllabus | lecture | worksheet | quiz | rubric | reading | other
    unit             TEXT,                   -- e.g. "Unit 3: Cells"
    summary          TEXT,
    dates_json       TEXT,                   -- JSON list of {date, label} found in the document
    label_confidence REAL,                   -- 0..1, below threshold -> status = needs_review
    label_source     TEXT,                   -- llm | heuristic | teacher
    review_reason    TEXT,                   -- why it needs review (shown to the teacher)
    extract_method   TEXT,                   -- text | vision | none
    page_count       INTEGER,
    embedded         INTEGER NOT NULL DEFAULT 0,  -- 1 once its chunks are in library_chunk_vec
    ai_pending       INTEGER NOT NULL DEFAULT 0,  -- 1 = queued for a (batched) AI double-check
    ai_queued_at     TEXT,
    status           TEXT NOT NULL DEFAULT 'filed',  -- filed | needs_review | draft | archived
    -- versioning (materials agent writes new versions, never overwrites)
    version          INTEGER NOT NULL DEFAULT 1,
    version_of       INTEGER REFERENCES library_files(file_id),
    created_by       TEXT NOT NULL DEFAULT 'teacher',  -- teacher | agent:<name>
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_library_files_class ON library_files(class_id, status);

CREATE TABLE IF NOT EXISTS library_chunks (
    chunk_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id    INTEGER NOT NULL REFERENCES library_files(file_id) ON DELETE CASCADE,
    chunk_idx  INTEGER NOT NULL,
    page       INTEGER,
    text       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_chunks_file ON library_chunks(file_id, chunk_idx);

-- Keyword index (SQLite FTS5, BM25 ranking), kept in sync with library_chunks by triggers,
-- so chunks written by any agent are keyword-searchable immediately.
CREATE VIRTUAL TABLE IF NOT EXISTS library_chunks_fts USING fts5(
    text, content='library_chunks', content_rowid='chunk_id', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS library_chunks_ai AFTER INSERT ON library_chunks BEGIN
    INSERT INTO library_chunks_fts(rowid, text) VALUES (new.chunk_id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS library_chunks_ad AFTER DELETE ON library_chunks BEGIN
    INSERT INTO library_chunks_fts(library_chunks_fts, rowid, text) VALUES ('delete', old.chunk_id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS library_chunks_au AFTER UPDATE OF text ON library_chunks BEGIN
    INSERT INTO library_chunks_fts(library_chunks_fts, rowid, text) VALUES ('delete', old.chunk_id, old.text);
    INSERT INTO library_chunks_fts(rowid, text) VALUES (new.chunk_id, new.text);
END;

-- The vector index (library_chunk_vec, sqlite-vec) is created by app/shared/library.py at
-- startup, because its size depends on the embedding model in config.yaml.
CREATE TABLE IF NOT EXISTS library_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ============================================================
-- Approvals inbox (HITL).  One row per action waiting on a person.
-- Rows that share a group_id came from the same agent pause and are resumed together.
-- ============================================================
CREATE TABLE IF NOT EXISTS approvals (
    approval_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id          TEXT NOT NULL,
    position          INTEGER NOT NULL,       -- order inside the group (= order of decisions on resume)
    agent             TEXT NOT NULL,
    class_id          INTEGER REFERENCES classes(class_id) ON DELETE CASCADE,
    thread_id         TEXT,                   -- LangGraph thread to resume (NULL for non-HITL approvals)
    action_name       TEXT NOT NULL,          -- tool name, e.g. publish_calendar
    action_args       TEXT NOT NULL,          -- JSON
    description       TEXT,
    allowed_decisions TEXT NOT NULL DEFAULT '["approve","edit","reject"]',
    required_role     TEXT NOT NULL DEFAULT 'teacher',  -- teacher | admin
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | edited | rejected
    decision          TEXT,                   -- JSON decision sent back to the agent
    decided_by        TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    decided_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, class_id);
CREATE INDEX IF NOT EXISTS idx_approvals_group ON approvals(group_id, position);

-- ============================================================
-- Run log: one row per agent run (handy for the evaluation section next to LangSmith)
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    agent       TEXT NOT NULL,
    class_id    INTEGER,
    thread_id   TEXT,
    status      TEXT NOT NULL,      -- done | waiting_for_approval | error
    summary     TEXT,
    started_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    finished_at TEXT
);
