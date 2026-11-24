-- Owned by the study-games agent.
CREATE TABLE IF NOT EXISTS study_activities (
    activity_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id     INTEGER NOT NULL REFERENCES classes(class_id) ON DELETE CASCADE,
    assignment_id INTEGER REFERENCES assignments(assignment_id) ON DELETE SET NULL, -- the assessment it prepares for
    unit         TEXT,
    kind         TEXT NOT NULL,                 -- flashcards | matching | fill_in
    title        TEXT NOT NULL,
    items_json   TEXT NOT NULL,                 -- [{front, back, source_chunk_id}] etc.
    review_json  TEXT,                          -- reviewer verdicts per item
    attempts     INTEGER NOT NULL DEFAULT 1,    -- generate/review rounds it took
    status       TEXT NOT NULL DEFAULT 'draft', -- draft | published | rejected
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    package_id   INTEGER                        -- the unit package it belongs to (check-ins)
);
CREATE INDEX IF NOT EXISTS idx_study_activities_class ON study_activities(class_id, status);
CREATE INDEX IF NOT EXISTS idx_study_activities_assignment ON study_activities(assignment_id, status);

-- A unit package = the games + the check-in questions for one unit, approved together.
-- Items inside items_json carry a stable item_id so student progress can point at them.
CREATE TABLE IF NOT EXISTS unit_packages (
    package_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id       INTEGER NOT NULL REFERENCES classes(class_id) ON DELETE CASCADE,
    unit           TEXT NOT NULL,
    settings_json  TEXT NOT NULL,                -- title, lesson_date, due_date, tutor_mode, ... as requested
    questions_json TEXT NOT NULL DEFAULT '[]',   -- check-in questions until published
    review_json    TEXT,
    assignment_id  INTEGER REFERENCES assignments(assignment_id) ON DELETE SET NULL, -- set on publish
    status         TEXT NOT NULL DEFAULT 'draft', -- draft | published | rejected
    generated_by   TEXT,                          -- model name, or 'offline' for the no-AI generator
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_unit_packages_class ON unit_packages(class_id, status);

-- Student practice. Written only through app/shared/checkin.py.
CREATE TABLE IF NOT EXISTS game_item_progress (
    student_id    INTEGER NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    activity_id   INTEGER NOT NULL REFERENCES study_activities(activity_id) ON DELETE CASCADE,
    item_id       TEXT NOT NULL,
    times_seen    INTEGER NOT NULL DEFAULT 0,
    times_correct INTEGER NOT NULL DEFAULT 0,
    last_correct  INTEGER NOT NULL DEFAULT 0,   -- mastered = the latest answer was right
    box           INTEGER NOT NULL DEFAULT 1,   -- 1..3 (Leitner): misses go back to 1 and come back sooner
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (student_id, activity_id, item_id)
);

CREATE TABLE IF NOT EXISTS game_scores (
    student_id     INTEGER NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    assignment_id  INTEGER NOT NULL REFERENCES assignments(assignment_id) ON DELETE CASCADE,
    points         INTEGER NOT NULL DEFAULT 0,
    current_streak INTEGER NOT NULL DEFAULT 0,
    best_streak    INTEGER NOT NULL DEFAULT 0,
    answers        INTEGER NOT NULL DEFAULT 0,
    unlocked_at    TEXT,                          -- first time mastery reached the threshold (unlock is permanent)
    started_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (student_id, assignment_id)
);
