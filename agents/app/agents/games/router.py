from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any, Literal

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from app.shared import checkin as ck
from app.shared.agent_router import make_router, require_models
from app.shared.db import connect
from app.shared.student_auth import checkin_for_student, current_student

from . import editing
from . import package as pkg
from .agent import build_agent, runner
from .extract import NotEnoughMaterial

router = make_router("games")


# ---------------------------------------------------------------- teacher: unit package
class UnitPackageIn(BaseModel):
    class_id: int
    unit: str = Field(min_length=1)
    lesson_date: date
    due_date: str | None = Field(default=None, description="YYYY-MM-DD or ISO time; default: the day before, 23:59")
    # The teacher's own calendar day for the due date. An ISO due time is in UTC, so 11:59 PM
    # in Utah is already the next day; the calendar entry should be on the teacher's day.
    due_day: date | None = None
    title: str | None = Field(default=None, max_length=200)
    tutor_mode: Literal["hints_only", "answer_after_tries"] = "hints_only"
    tutor_reveal_after: int = Field(default=2, ge=1, le=10)
    mastery_threshold: float = Field(default=0.8, gt=0, le=1)
    mc_count: int = Field(default=4, ge=0, le=12)
    explain_count: int = Field(default=2, ge=0, le=6)
    card_count: int = Field(default=10, ge=4, le=30)
    offline: bool = False

    @field_validator("mastery_threshold", mode="before")
    @classmethod
    def percent_is_fine_too(cls, v):  # 80 -> 0.8
        return v / 100 if isinstance(v, (int, float)) and 1 < v <= 100 else v

    @model_validator(mode="after")
    def some_questions(self):
        if self.mc_count + self.explain_count < 1:
            raise ValueError("Ask for at least one check-in question.")
        try:
            self.due_date = pkg.normalize_due(self.due_date, self.lesson_date)
        except ValueError as exc:
            raise ValueError("due_date must be YYYY-MM-DD or an ISO date-time.") from exc
        return self


@router.post("/unit-package")
def create_unit_package(body: UnitPackageIn):
    """Build the games + check-in for one Library unit, save them as a draft and send ONE
    approval (publish_unit_package). Real models when the games agent has keys, else (or with
    offline=true) the deterministic no-AI generator."""
    with connect() as conn:
        if conn.execute("SELECT 1 FROM classes WHERE class_id = ?", (body.class_id,)).fetchone() is None:
            raise HTTPException(404, "Class not found")
    sources, waiting = pkg.unit_sources(body.class_id, body.unit)
    if not sources:
        hint = (f" {waiting} file(s) in this unit are waiting for review in the Library; confirm them first."
                if waiting else " File notes, slides or readings under this unit in the Library first.")
        raise HTTPException(409, f"\"{body.unit}\" has no filed text to build from.{hint}")
    settings = {
        "title": (body.title or "").strip() or f"{body.unit} practice + check-in",
        "lesson_date": body.lesson_date.isoformat(), "due_date": body.due_date,
        "due_day": (body.due_day.isoformat() if body.due_day else (body.due_date or "")[:10]),
        "tutor_mode": body.tutor_mode, "tutor_reveal_after": body.tutor_reveal_after,
        "mastery_threshold": body.mastery_threshold, "mc_count": body.mc_count,
        "explain_count": body.explain_count, "card_count": body.card_count, "offline": body.offline,
    }
    thread_id = f"games-{uuid.uuid4().hex[:12]}"
    graph = build_agent()
    try:
        out = runner.run({"class_id": body.class_id, "unit": body.unit, "settings": settings, "offline": body.offline},
                         class_id=body.class_id, thread_id=thread_id, graph=graph)
    except NotEnoughMaterial as exc:
        raise HTTPException(409, str(exc)) from exc
    package_id = graph.get_state({"configurable": {"thread_id": thread_id}}).values.get("package_id")
    p = pkg.get_package(package_id) if package_id else None
    return {**out, "package_id": package_id, "summary": pkg.summary(p) if p else None}


@router.get("/unit-package/by-assignment/{assignment_id}")
def get_unit_package_for_assignment(assignment_id: int):
    """The package a published check-in was built from (the teacher's check-in page shows it)."""
    with connect() as conn:
        row = conn.execute("SELECT package_id FROM unit_packages WHERE assignment_id = ? ORDER BY package_id DESC LIMIT 1",
                           (assignment_id,)).fetchone()
    p = pkg.get_package(row["package_id"]) if row else None
    if p is None:
        raise HTTPException(404, "No unit package for this assignment")
    return p


@router.get("/unit-package/{package_id}")
def get_unit_package(package_id: int):
    """Teacher preview: games (with sources), check-in questions with answers and rubrics."""
    p = pkg.get_package(package_id)
    if p is None:
        raise HTTPException(404, "Unit package not found")
    return p


# ---------------------------------------------------------------- teacher: edit a draft (editing.py)
# Loose types on purpose: the rules are checked in editing.py so the teacher gets one readable
# 422 message ("Question 2: mark which option is the right answer.") instead of a pydantic list.
class OptionEditIn(BaseModel):
    text: str | None = None
    correct: bool = False


class QuestionEditIn(BaseModel):
    text: str | None = None
    kind: str | None = None
    options: list[OptionEditIn] | None = None
    answer: str | None = None
    rubric: str | None = None
    source: str | None = None


class ActivityEditIn(BaseModel):
    activity_id: int
    items: list[dict[str, Any]]


class SettingsEditIn(BaseModel):
    title: str | None = None
    lesson_date: str | None = None
    due_date: str | None = None
    due_day: str | None = None
    tutor_mode: str | None = None
    tutor_reveal_after: int | None = None
    mastery_threshold: float | None = None


class PackageEditIn(BaseModel):
    questions: list[QuestionEditIn] | None = Field(default=None, description="the full list, in order")
    activities: list[ActivityEditIn] | None = Field(default=None, description="per game: its full item list")
    settings: SettingsEditIn | None = None


def _edit_errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except editing.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except editing.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except editing.EditError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.patch("/unit-package/{package_id}")
def edit_unit_package(package_id: int, body: PackageEditIn):
    """Edit a draft before approving it: questions, game items (existing item_ids are kept, new
    items get fresh ids) and/or settings. 422 on a broken rule, 409 once it isn't a draft.
    Returns {package, warnings} (warnings = the deterministic draft checks)."""
    return _edit_errors(
        editing.apply_edits, package_id,
        questions=[q.model_dump() for q in body.questions] if body.questions is not None else None,
        activities=[a.model_dump() for a in body.activities] if body.activities is not None else None,
        settings=body.settings.model_dump(exclude_unset=True) if body.settings is not None else None)


class RegenerateIn(BaseModel):
    kind: Literal["question", "item"]
    index: int | None = Field(default=None, description="kind=question: 0-based question index")
    activity_id: int | None = None
    item_id: str | None = None
    offline: bool | None = Field(default=None, description="default: the package's own offline setting")


@router.post("/unit-package/{package_id}/regenerate")
def regenerate_unit_package_part(package_id: int, body: RegenerateIn):
    """Replace one question or one game item with a new one of the same kind (model when the
    games agent has keys, else / on any model error the next unused no-AI candidate; 409 when
    there's none left). Returns {package, warnings, replaced, generated_by, note}."""
    return _edit_errors(editing.regenerate, package_id, kind=body.kind, index=body.index,
                        activity_id=body.activity_id, item_id=body.item_id, offline=body.offline)


# ---------------------------------------------------------------- teacher: single activity
class RunIn(BaseModel):
    class_id: int
    topic: str
    kind: str = "flashcards"


@router.post("/run")
def run(body: RunIn):
    require_models("games", "generator", "reviewer")
    return runner.run({"class_id": body.class_id, "topic": body.topic, "kind": body.kind}, class_id=body.class_id)


@router.post("/demo")
def demo(class_id: int = Query(...), topic: str = "Unit 3 cells"):
    """Offline: canned items, keyword 'reviewer', real graph + real approval step.
    (For the flipped-classroom package without keys: POST /unit-package with offline=true.)"""
    return runner.run({"class_id": class_id, "topic": topic, "kind": "flashcards", "offline": True}, class_id=class_id)


@router.get("/activities")
def activities(class_id: int, status: str | None = None):
    """Teacher preview (all) or the student game list (status=published)."""
    sql, params = "SELECT * FROM study_activities WHERE class_id = ?", [class_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(sql + " ORDER BY created_at DESC", params).fetchall()]
    for r in rows:
        r["items"] = json.loads(r.pop("items_json"))
        r["review"] = json.loads(r.pop("review_json") or "[]")
    return {"activities": rows}


# ---------------------------------------------------------------- student: practice
@router.get("/practice/{assignment_id}")
def practice(assignment_id: int, student_id: int = Depends(current_student)):
    """The check-in's published games (student fields only), this student's progress and stats."""
    a = checkin_for_student(student_id, assignment_id)
    with connect() as conn:
        rows = conn.execute("SELECT activity_id, kind, title, items_json FROM study_activities "
                            "WHERE assignment_id = ? AND status = 'published' ORDER BY activity_id",
                            (assignment_id,)).fetchall()
        progress = ck.item_progress(conn, student_id, assignment_id)
        stats = ck.practice_stats(conn, student_id, assignment_id)
    acts = [{"activity_id": r["activity_id"], "kind": r["kind"], "title": r["title"],
             "items": pkg.student_items(r["kind"], json.loads(r["items_json"] or "[]"))} for r in rows]
    return {
        "assignment": {"assignment_id": a["assignment_id"], "title": a["assignment_name"], "unit": a["unit"],
                       "lesson_date": a["lesson_date"], "due_date": a["due_date"]},
        "activities": [x for x in acts if x["items"]],
        "progress": progress,
        "stats": stats,
        "replay_gap": ck.REPLAY_GAP,
    }


class PracticeAnswerIn(BaseModel):
    activity_id: int
    item_id: str = Field(min_length=1, max_length=64)
    correct: bool


@router.post("/practice/{assignment_id}/answer")
def practice_answer(assignment_id: int, body: PracticeAnswerIn, student_id: int = Depends(current_student)):
    """One game answer (the browser decides right/wrong: it's practice, not a test)."""
    checkin_for_student(student_id, assignment_id, writing=True)
    try:
        with connect() as conn:
            return ck.record_practice_answer(conn, student_id, assignment_id, body.activity_id, body.item_id,
                                             body.correct)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
