from __future__ import annotations

from fastapi import Query
from pydantic import BaseModel

from app.shared.agent_router import make_router, require_models
from app.shared.db import connect

from .agent import build_agent, demo_script, runner

router = make_router("scheduler")


class RunIn(BaseModel):
    class_id: int
    instruction: str = "Build the calendar for the rest of the term."


@router.post("/run")
def run(body: RunIn):
    require_models("scheduler")
    return runner.run(
        {"messages": [("user", f"Class id: {body.class_id}. {body.instruction}")]},
        class_id=body.class_id,
    )


@router.post("/demo")
def demo(class_id: int = Query(...)):
    """Offline: scripted model, real tools, real approval step.  No API key needed."""
    graph = build_agent(script=demo_script(class_id))
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
