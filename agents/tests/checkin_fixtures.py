"""Build a small published check-in straight in the test DB (no generation), for tests of
practice, the check-in tutor, grading and the briefing.

    from tests.checkin_fixtures import make_checkin
    c = make_checkin()   # Biology (class 3); students 2, 4, 7, 8 are enrolled
    c.assignment_id, c.mc_ids, c.explain_id, c.activity_ids, c.items
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.shared.db import connect

BIO = 3
ENROLLED = (2, 4, 7, 8)    # seed.sql: students in class 3
NOT_ENROLLED = 1


@dataclass
class Checkin:
    assignment_id: int
    mc_ids: list[int]
    mc_correct: dict[int, int]          # question_id -> correct option_id
    mc_wrong: dict[int, int]            # question_id -> a wrong option_id
    explain_id: int
    activity_ids: list[int]
    items: list[tuple[int, str]] = field(default_factory=list)  # (activity_id, item_id)


def make_checkin(*, class_id: int = BIO, tutor_mode: str = "hints_only", reveal_after: int = 2,
                 threshold: float = 0.8, due_date: str = "2099-01-01T23:59:00.000Z",
                 unit: str = "Unit 2: Cell Structure") -> Checkin:
    with connect() as conn:
        aid = conn.execute(
            """INSERT INTO assignments (class_id, assignment_name, type, max_points, due_date, mode, unit,
                   tutor_mode, tutor_reveal_after, mastery_threshold, lesson_date)
               VALUES (?, 'Unit 2 check-in', 'Homework', 10, ?, 'checkin', ?, ?, ?, ?, '2099-01-02')""",
            (class_id, due_date, unit, tutor_mode, reveal_after, threshold)).lastrowid
        mc_ids, right, wrong = [], {}, {}
        for i, (text, good, bad) in enumerate([
            ("Which organelle makes most of the cell's ATP?", "Mitochondria", "Ribosome"),
            ("What controls what enters and leaves the cell?", "Cell membrane", "Nucleus"),
        ]):
            qid = conn.execute("INSERT INTO assignment_questions (assignment_id, sort_order, question_text, "
                               "question_type, max_points) VALUES (?, ?, ?, 'multiple_choice', 1)",
                               (aid, i, text)).lastrowid
            right[qid] = conn.execute("INSERT INTO assignment_question_options (question_id, option_text, is_correct) "
                                      "VALUES (?, ?, 1)", (qid, good)).lastrowid
            wrong[qid] = conn.execute("INSERT INTO assignment_question_options (question_id, option_text, is_correct) "
                                      "VALUES (?, ?, 0)", (qid, bad)).lastrowid
            mc_ids.append(qid)
        eid = conn.execute(
            "INSERT INTO assignment_questions (assignment_id, sort_order, question_text, question_type, max_points, "
            "explain_rubric) VALUES (?, 2, 'Explain why a cell needs a membrane.', 'short_answer', 1, ?)",
            (aid, "The membrane controls what enters and leaves the cell, keeping the inside stable.")).lastrowid
        conn.execute("INSERT INTO assignment_question_options (question_id, option_text, is_correct) VALUES (?, ?, 1)",
                     (eid, "It controls what goes in and out, so the cell can keep its inside stable."))
        cards = [{"item_id": f"c{i}", "front": f, "back": b} for i, (f, b) in enumerate([
            ("Mitochondria", "Makes ATP"), ("Ribosome", "Makes proteins"), ("Nucleus", "Holds the DNA"),
            ("Cell membrane", "Controls what enters and leaves"), ("Chloroplast", "Does photosynthesis")])]
        pairs = [{"item_id": f"m{i}", "term": c["front"], "definition": c["back"]} for i, c in enumerate(cards[:4])]
        blanks = [{"item_id": "f0", "sentence": "The ____ makes most of the cell's ATP.", "answer": "mitochondria",
                   "alternates": ["mitochondrion"]}]
        acts = []
        for kind, items in (("flashcards", cards), ("matching", pairs), ("fill_in", blanks)):
            acts.append(conn.execute(
                "INSERT INTO study_activities (class_id, assignment_id, unit, kind, title, items_json, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'published')",
                (class_id, aid, unit, kind, f"Unit 2 {kind}", json.dumps(items))).lastrowid)
    items = [(acts[0], c["item_id"]) for c in cards] + [(acts[1], p["item_id"]) for p in pairs] + [(acts[2], "f0")]
    return Checkin(aid, mc_ids, right, wrong, eid, acts, items)
