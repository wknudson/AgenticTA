"""AgenticTA agent service.

    npm run dev            (from the repo root: starts Vite + Express + this service)
    npm run dev:agents     (just this service, http://localhost:8000/docs for the API explorer)

All routes live under /agents so the Vite dev server can proxy them like /api.
"""
from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .shared import approvals
from .shared.agent_router import agent_info
from .shared.db import init_db
from .shared.llm import MissingApiKey
from .shared.settings import DB_PATH, config, key_status

AGENTS = list(config()["agents"].keys())  # filing, scheduler, materials, games, misconceptions, tutor

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()  # create agent tables (IF NOT EXISTS) in the shared SQLite file
    yield


app = FastAPI(title="AgenticTA agents", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(MissingApiKey)
def _missing_key(_, exc: MissingApiKey) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc), "hint": "Add the key to .env or run the offline demo."})


for _name in AGENTS:
    _module = importlib.import_module(f"app.agents.{_name}")
    app.include_router(_module.router, prefix=f"/agents/{_name}")


@app.get("/agents/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "db_path": str(DB_PATH),
        "keys": key_status(),
        "agents": [agent_info(a) for a in AGENTS],
    }


# ---------------------------------------------------------------- Approvals inbox
@app.get("/agents/approvals")
def list_approvals(class_id: int | None = None, status: str | None = "pending", agent: str | None = None):
    return {"approvals": approvals.list_approvals(class_id=class_id, status=status or None, agent=agent)}


class DecisionIn(BaseModel):
    type: Literal["approve", "edit", "reject"]
    edited_args: dict[str, Any] | None = None
    message: str | None = None
    decided_by: str = "teacher"
    role: Literal["teacher", "admin"] = "teacher"


@app.post("/agents/approvals/{approval_id}/decide")
def decide(approval_id: int, body: DecisionIn):
    try:
        return approvals.decide(approval_id, body.type, edited_args=body.edited_args, message=body.message,
                                decided_by=body.decided_by, role=body.role)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
