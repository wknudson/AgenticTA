from __future__ import annotations

import json

from fastapi import Query
from pydantic import BaseModel

from app.shared.agent_router import make_router, require_models
from app.shared.db import connect

from .agent import runner

router = make_router("games")


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
    """Offline: canned items, keyword 'reviewer', real graph + real approval step."""
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
