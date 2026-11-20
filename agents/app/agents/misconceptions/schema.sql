-- Owned by the misconception finder.
CREATE TABLE IF NOT EXISTS misconception_insights (
    insight_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id       INTEGER NOT NULL REFERENCES classes(class_id) ON DELETE CASCADE,
    assignment_id  INTEGER REFERENCES assignments(assignment_id) ON DELETE SET NULL,
    topic          TEXT NOT NULL,          -- "Confuses mitosis with meiosis"
    evidence_count INTEGER NOT NULL,       -- how many (redacted) questions support it
    examples_json  TEXT NOT NULL,          -- a few REDACTED example questions
    suggestion     TEXT,                   -- JSON: explanation, material_update, reteaching_activity
    model_used     TEXT,                   -- ollama:phi3 vs anthropic:... (for the comparison)
    status         TEXT NOT NULL DEFAULT 'new', -- new | sent_to_games | sent_to_materials | dismissed
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_misconception_insights_class ON misconception_insights(class_id, status);
