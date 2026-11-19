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
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_study_activities_class ON study_activities(class_id, status);
