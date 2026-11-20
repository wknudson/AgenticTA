"""Scheduler tools.  Owner: Teammate B.

Design rule for this agent: the LLM decides WHAT to schedule; deterministic code does
all date math and rule checks, so dates are never hallucinated (and the checks show
up as tool calls in LangSmith).
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

from app.shared import library
from app.shared.db import connect
from .calendar import load_term, validate_events


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
    settings = load_term(class_id)
    if settings is None:
        raise ValueError("Save term dates and holidays before scheduling.")
    return settings


@tool
def check_conflicts(class_id: int, events: list[dict]) -> str:
    """Check dates against teacher settings and already published assessments."""
    with connect() as conn:
        published = [dict(r) for r in conn.execute(
            "SELECT * FROM calendar_events WHERE class_id = ? AND status = 'published'", (class_id,))]
    return json.dumps(validate_events(load_term(class_id), events, published))


@tool
def propose_events(class_id: int, events: list[dict]) -> str:
    """Save events as PROPOSED (students can't see them yet).  events: [{title, date, kind, source?}]"""
    checks = json.loads(check_conflicts.invoke({"class_id": class_id, "events": events}))
    if not checks["ok"]:
        return json.dumps({"proposed_event_ids": [], **checks})
    with connect() as conn:
        ids = [
            conn.execute(
                "INSERT INTO calendar_events (class_id, title, kind, date, source, assignment_id) VALUES (?, ?, ?, ?, ?, ?)",
                (class_id, e["title"], e.get("kind", "event"), e["date"], e.get("source"), e.get("assignment_id")),
            ).lastrowid
            for e in events
        ]
    return json.dumps({"proposed_event_ids": ids})


@tool
def publish_calendar(class_id: int, event_ids: list[int]) -> str:
    """Publish ONLY the specified proposed events after teacher approval.
    Revalidates current rules so stale or edited approvals cannot bypass them."""
    if not event_ids:
        return json.dumps({"published": 0, "ok": False, "problems": [{"problem": "Explicit event ids are required."}]})
    marks = ','.join('?' for _ in event_ids)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        events = [dict(r) for r in conn.execute(
            f"SELECT * FROM calendar_events WHERE class_id = ? AND status = 'proposed' AND event_id IN ({marks})",
            [class_id, *event_ids])]
        if len(events) != len(set(event_ids)):
            return json.dumps({"published": 0, "ok": False, "problems": [{"problem": "Some events are missing or no longer proposed."}]})
        published = [dict(r) for r in conn.execute(
            "SELECT * FROM calendar_events WHERE class_id = ? AND status = 'published'", (class_id,))]
        checks = validate_events(load_term(class_id), events, published)
        if not checks["ok"]:
            return json.dumps({"published": 0, **checks})
        conn.execute(f"UPDATE calendar_events SET status = 'published' WHERE class_id = ? AND event_id IN ({marks})",
                     [class_id, *event_ids])
    return json.dumps({"published": len(events), "ok": True})


TOOLS = [get_assignments, get_library_dates, check_conflicts, propose_events, publish_calendar]
