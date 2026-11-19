from __future__ import annotations

from fastapi import Query

from app.shared.agent_router import make_router, require_models
from app.shared.db import connect

from .pipeline import run as run_pipeline

router = make_router("misconceptions")


@router.post("/run")
def run(class_id: int = Query(...), assignment_id: int | None = None):
    require_models("misconceptions", "local")
    return run_pipeline(class_id, assignment_id)


@router.post("/demo")
def demo(class_id: int = Query(...)):
    """Offline: loads + redacts the real chat logs, skips the model step."""
    return run_pipeline(class_id, offline=True)


@router.get("/insights")
def insights(class_id: int, status: str | None = None):
    sql, params = "SELECT * FROM misconception_insights WHERE class_id = ?", [class_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    with connect() as conn:
        return {"insights": [dict(r) for r in conn.execute(sql + " ORDER BY created_at DESC", params).fetchall()]}
