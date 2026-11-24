"""Check-in questions as the tutor sees them: the student-safe question object (Q) and the
server-only answer key.

Q never carries the right answer (no is_correct, no model answer, no rubric). The AnswerKey
stays on the server: the judge, the answer guard and (only once may_reveal() is true) the
tutor's prompt read it.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from app.shared import checkin as ck

CHOICE_TYPES = {"multiple_choice", "true_false", "select_all_that_apply", "select_all"}
MULTI_TYPES = {"select_all_that_apply", "select_all"}


def seeded_shuffle(items: list[Any], seed: int) -> list[Any]:
    """Same order as seededShuffle in backend/routes/student.ts (JS int32 LCG), so a student sees
    the options in the same order everywhere. Stable per student and question."""
    out = list(items)
    s = seed
    for i in range(len(out) - 1, 0, -1):
        s = (s * 1664525 + 1013904223) & 0xFFFFFFFF
        if s >= 0x80000000:  # JS `& 0xffffffff` yields a signed 32-bit int
            s -= 0x100000000
        j = (s & 0xFFFFFFFF) % (i + 1)
        out[i], out[j] = out[j], out[i]
    return out


@dataclass
class AnswerKey:
    """Server-only. Never put any of this in a response."""
    question_type: str
    question_text: str
    correct_ids: set[int] = field(default_factory=set)
    correct_texts: list[str] = field(default_factory=list)   # choice: the right option(s)
    wrong_texts: list[str] = field(default_factory=list)
    model_answer: str | None = None                          # explain: the is_correct option / correct_answer
    rubric: str | None = None                                # assignment_questions.explain_rubric

    @property
    def kind(self) -> str:
        return "choice" if self.question_type in CHOICE_TYPES else "explain"

    def judge_target(self) -> str:
        """What a good explanation must show: the rubric, else the model answer / right option."""
        return (self.rubric or self.model_answer or "; ".join(self.correct_texts) or "").strip()

    def answer_text(self) -> str:
        """The answer, for the reveal turn only."""
        if self.kind == "choice":
            return ", ".join(self.correct_texts)
        return (self.model_answer or self.rubric or "").strip()

    def secrets(self) -> list[str]:
        out = [*self.correct_texts, self.model_answer or "", self.rubric or ""]
        return [s.strip() for s in out if s and s.strip()]


@dataclass
class Question:
    question_id: int
    number: int
    text: str
    question_type: str
    options: list[dict[str, Any]]  # option_id, option_text, is_correct (server-side only)
    key: AnswerKey

    @property
    def kind(self) -> str:
        return self.key.kind

    def option(self, option_id: int) -> dict[str, Any] | None:
        return next((o for o in self.options if o["option_id"] == option_id), None)


def load_questions(conn: sqlite3.Connection, assignment_id: int) -> list[Question]:
    rows = conn.execute("SELECT * FROM assignment_questions WHERE assignment_id = ? ORDER BY sort_order, question_id",
                        (assignment_id,)).fetchall()
    out = []
    for n, r in enumerate(rows, start=1):
        opts = [dict(o) for o in conn.execute(
            "SELECT option_id, option_text, is_correct FROM assignment_question_options WHERE question_id = ? "
            "ORDER BY option_id", (r["question_id"],))]
        qtype = r["question_type"] or "multiple_choice"
        right = [o for o in opts if o["is_correct"]]
        key = AnswerKey(question_type=qtype, question_text=r["question_text"], rubric=r["explain_rubric"])
        if qtype in CHOICE_TYPES:
            key.correct_ids = {o["option_id"] for o in right}
            key.correct_texts = [o["option_text"] for o in right]
            key.wrong_texts = [o["option_text"] for o in opts if not o["is_correct"]]
        else:
            key.model_answer = (right[0]["option_text"] if right else None) or r["correct_answer"]
        out.append(Question(r["question_id"], n, r["question_text"], qtype, opts, key))
    return out


def get_question(conn: sqlite3.Connection, assignment_id: int, question_id: int) -> Question:
    for q in load_questions(conn, assignment_id):
        if q.question_id == question_id:
            return q
    raise ValueError("That question isn't part of this check-in.")


def public_question(q: Question, status: dict[str, Any], *, student_id: int, assignment: dict[str, Any]) -> dict[str, Any]:
    """Q from the contract. Never includes the right answer."""
    out: dict[str, Any] = {
        "question_id": q.question_id, "number": q.number, "text": q.text, "kind": q.kind,
    }
    if q.kind == "choice":
        out["options"] = [{"option_id": o["option_id"], "text": o["option_text"]}
                          for o in seeded_shuffle(q.options, student_id * 1000 + q.question_id)]
        if q.question_type in MULTI_TYPES:
            out["multi"] = True  # select-all: send option_ids instead of option_id
    out.update({
        "status": status["status"], "first_answer": status["first_answer"], "tries": status["tries"],
        "help_level": status["help_level"], "last_feedback": status["last_feedback"],
        "can_reveal": ck.may_reveal(assignment, status),
    })
    return out


def public_questions(conn: sqlite3.Connection, student_id: int, assignment: dict[str, Any]) -> list[dict[str, Any]]:
    statuses = {r["question_id"]: r for r in ck.status_rows(conn, student_id, assignment["assignment_id"])}
    return [public_question(q, statuses[q.question_id], student_id=student_id, assignment=assignment)
            for q in load_questions(conn, assignment["assignment_id"]) if q.question_id in statuses]
