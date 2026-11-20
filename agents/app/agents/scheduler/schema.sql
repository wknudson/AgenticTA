-- Owned by the scheduler agent.

-- Term dates and holidays, entered once by the teacher (settings form on the Scheduler panel).
CREATE TABLE IF NOT EXISTS term_calendar (
    class_id                 INTEGER PRIMARY KEY REFERENCES classes(class_id) ON DELETE CASCADE,
    term_start               TEXT NOT NULL,              -- YYYY-MM-DD
    term_end                 TEXT NOT NULL,
    holidays_json            TEXT NOT NULL DEFAULT '[]', -- [{"date": "2026-11-26", "label": "Thanksgiving"}]
    max_assessments_per_day  INTEGER NOT NULL DEFAULT 2
);

-- Events the agent proposes; students only see status = 'published'.
CREATE TABLE IF NOT EXISTS calendar_events (
    event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id      INTEGER NOT NULL REFERENCES classes(class_id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'event',  -- assignment_due | assessment | reading | event
    date          TEXT NOT NULL,                  -- YYYY-MM-DD
    assignment_id INTEGER REFERENCES assignments(assignment_id) ON DELETE SET NULL,
    source        TEXT,                           -- where the date came from (file title, assignment)
    status        TEXT NOT NULL DEFAULT 'proposed', -- proposed | published | rejected | removed (teacher)
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_calendar_events_class ON calendar_events(class_id, status, date);
