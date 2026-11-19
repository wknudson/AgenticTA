from __future__ import annotations

from fastapi import HTTPException, Query
from pydantic import BaseModel

from app.shared import library
from app.shared.agent_router import make_router, require_models

from .agent import build_agent, demo_script, runner

router = make_router("materials")


class RunIn(BaseModel):
    class_id: int
    instruction: str


@router.post("/run")
def run(body: RunIn):
    require_models("materials", "planner", "editor")
    return runner.run(
        {"messages": [("user", f"Class id: {body.class_id}. Instruction: {body.instruction}")]},
        class_id=body.class_id,
    )


@router.post("/demo")
def demo(class_id: int = Query(...)):
    """Offline: needs at least one filed document (run the Filing demo first)."""
    files = library.list_files(class_id)
    if not files:
        raise HTTPException(409, "The library is empty. Run the Filing demo or upload a file first.")
    script = demo_script(class_id, files[0].file_id)
    # The scripted model can't know the new draft's id ahead of time, so peek at the next id.
    from app.shared.db import connect
    with connect() as conn:
        next_id = conn.execute("SELECT COALESCE(MAX(file_id), 0) + 1 FROM library_files").fetchone()[0]
    script[2].tool_calls[0]["args"]["draft_file_id"] = next_id
    return runner.run({"messages": [("user", "Offline demo: move the Unit 3 quiz back a week")]},
                      class_id=class_id, graph=build_agent(script=script))
