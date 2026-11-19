"""Scheduler tools.  Owner: Teammate B.

Design rule for this agent: the LLM decides WHAT to schedule; deterministic code does
all date math and rule checks, so dates are never hallucinated (and the checks show
up as tool calls in LangSmith).
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date

from langchain_core.tools import tool

from app.shared import library
from app.shared.db import connect
from app.shared.guardrails import is_weekend, within_range


@tool
def get_assignments(class_id: int) -> str:
    """List this class's assignments with their due dates (read-only)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT assignment_id, assignment_name, type, due_date FROM assignments WHERE class_id = ? ORDER BY due_date",
            (class_id,),
        ).fetchall()
    return json.dumps([dict(r) for r in rows])


@tool
def get_library_dates(class_id: int) -> str:
    """Dates the filing pipeline found inside the class's documents (syllabi, handouts...)."""
    out = [{"file": f.title or f.original_name, "dates": f.dates} for f in library.list_files(class_id) if f.dates]
    return json.dumps(out)


def _term(class_id: int) -> dict:
    with connect() as conn:
        r = conn.execute("SELECT * FROM term_calendar WHERE class_id = ?", (class_id,)).fetchone()
    if r is None:  # TODO(Teammate B): require the teacher to fill this in from the panel
        return {"term_start": "2026-08-24", "term_end": "2026-12-18", "holidays": [], "max_per_day": 2}
    return {"term_start": r["term_start"], "term_end": r["term_end"],
            "holidays": json.loads(r["holidays_json"]), "max_per_day": r["max_assessments_per_day"]}


@tool
def check_conflicts(class_id: int, events: list[dict]) -> str:
    """Deterministic checks on proposed events [{title, date: YYYY-MM-DD, kind}].
    Flags: outside the term, weekend, holiday, too many assessments on one day."""
    t = _term(class_id)
    start, end = date.fromisoformat(t["term_start"]), date.fromisoformat(t["term_end"])
    holidays = {h["date"]: h.get("label", "holiday") for h in t["holidays"]}
    per_day = Counter(e["date"] for e in events if e.get("kind") in ("assessment", "assignment_due"))
    problems = []
    for e in events:
        d = date.fromisoformat(e["date"])
        if not within_range(d, start, end):
            problems.append({"event": e["title"], "date": e["date"], "problem": "outside the term"})
        if is_weekend(d):
            problems.append({"event": e["title"], "date": e["date"], "problem": "weekend"})
        if e["date"] in holidays:
            problems.append({"event": e["title"], "date": e["date"], "problem": f"holiday: {holidays[e['date']]}"})
    for day, n in per_day.items():
        if n > t["max_per_day"]:
            problems.append({"date": day, "problem": f"{n} assessments/due dates (max {t['max_per_day']})"})
    return json.dumps({"ok": not problems, "problems": problems})


@tool
def propose_events(class_id: int, events: list[dict]) -> str:
    """Save events as PROPOSED (students can't see them yet).  events: [{title, date, kind, source?}]"""
    with connect() as conn:
        ids = [
            conn.execute(
                "INSERT INTO calendar_events (class_id, title, kind, date, source) VALUES (?, ?, ?, ?, ?)",
                (class_id, e["title"], e.get("kind", "event"), e["date"], e.get("source")),
            ).lastrowid
            for e in events
        ]
    return json.dumps({"proposed_event_ids": ids})


@tool
def publish_calendar(class_id: int, event_ids: list[int] | None = None) -> str:
    """Publish proposed events to the student calendar (all proposed events if event_ids is empty).
    CONSEQUENTIAL: pauses for teacher approval (HITL)."""
    sql, params = "UPDATE calendar_events SET status = 'published' WHERE class_id = ? AND status = 'proposed'", [class_id]
    if event_ids:
        sql += f" AND event_id IN ({','.join('?' * len(event_ids))})"
        params += event_ids
    with connect() as conn:
        n = conn.execute(sql, params).rowcount
    return json.dumps({"published": n})


TOOLS = [get_assignments, get_library_dates, check_conflicts, propose_events, publish_calendar]
