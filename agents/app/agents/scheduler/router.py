from __future__ import annotations

from fastapi import Query, HTTPException
from fastapi.responses import Response
from datetime import date, timedelta, datetime, timezone
from pydantic import BaseModel

from app.shared.agent_router import make_router, require_models
from app.shared.db import connect

from .agent import build_agent, demo_script, runner
from .calendar import TermSettings, load_term, save_term
from .tools import check_conflicts
import json

router = make_router("scheduler")


class RunIn(BaseModel):
    class_id: int
    instruction: str = "Build the calendar for the rest of the term."


@router.post("/run")
def run(body: RunIn):
    if load_term(body.class_id) is None:
        raise HTTPException(409, "Save term dates and holidays before building the calendar.")
    require_models("scheduler")
    return runner.run(
        {"messages": [("user", f"Class id: {body.class_id}. {body.instruction}")]},
        class_id=body.class_id,
    )


@router.post("/demo")
def demo(class_id: int = Query(...)):
    """Offline: scripted model, real tools, real approval step.  No API key needed."""
    try:
        graph = build_agent(script=demo_script(class_id))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return runner.run({"messages": [("user", "Offline demo")]}, class_id=class_id, graph=graph)


@router.get("/events")
def events(class_id: int, status: str | None = None):
    """Calendar events for the teacher preview (all) or the student calendar (status=published)."""
    sql, params = "SELECT * FROM calendar_events WHERE class_id = ?", [class_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    with connect() as conn:
        rows = conn.execute(sql + " ORDER BY date", params).fetchall()
    return {"events": [dict(r) for r in rows]}


@router.get("/term")
def get_term(class_id: int):
    return {"term": load_term(class_id)}


@router.put("/term")
def put_term(class_id: int, body: TermSettings):
    try:
        return {"term": save_term(class_id, body)}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/conflicts")
def conflicts(class_id: int):
    with connect() as conn:
        proposed = [dict(r) for r in conn.execute(
            "SELECT * FROM calendar_events WHERE class_id = ? AND status = 'proposed'", (class_id,))]
    return json.loads(check_conflicts.invoke({"class_id": class_id, "events": proposed}))


@router.get("/calendar.ics")
def calendar_download(class_id: int):
    """Export only approved events as all-day dates, without timezone shifts."""
    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")

    def fold(line: str) -> str:
        parts, current = [], ""
        for char in line:
            if len((current + char).encode("utf-8")) > 75:
                parts.append(current)
                current = " "
            current += char
        return "\r\n".join([*parts, current])

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AgenticTA//Class Calendar//EN", "CALSCALE:GREGORIAN"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for event in events(class_id, "published")["events"]:
        day = date.fromisoformat(event["date"])
        lines.extend(["BEGIN:VEVENT", f"UID:class-{class_id}-event-{event['event_id']}@agenticta",
                      f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
                      f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
                      f"SUMMARY:{escape(event['title'])}", "END:VEVENT"])
    lines.append("END:VCALENDAR")
    return Response("\r\n".join(map(fold, lines)) + "\r\n", media_type="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="class-{class_id}.ics"'})
