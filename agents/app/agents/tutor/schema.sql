-- Owned by the tutor agent (check-ins). Written only through app/shared/checkin.py.

-- One row per student per check-in question.
CREATE TABLE IF NOT EXISTS checkin_item_status (
    student_id    INTEGER NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    assignment_id INTEGER NOT NULL REFERENCES assignments(assignment_id) ON DELETE CASCADE,
    question_id   INTEGER NOT NULL REFERENCES assignment_questions(question_id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'unanswered', -- unanswered | correct | needs_fix | fixed
    first_answer  TEXT,
    first_correct INTEGER,                           -- 1 = right the first time
    tries         INTEGER NOT NULL DEFAULT 0,        -- honest fix attempts after a miss
    tutor_turns   INTEGER NOT NULL DEFAULT 0,        -- student messages to the tutor on this question
    help_level    TEXT NOT NULL DEFAULT 'none',      -- none | hint | explained
    explain_back  TEXT,                              -- the explanation that resolved it
    last_feedback TEXT,                              -- what the judge said was missing
    resolved_at   TEXT,
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (student_id, assignment_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_checkin_status_assignment ON checkin_item_status(assignment_id, status);
