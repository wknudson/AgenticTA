"""The Approvals inbox: every consequential agent action waits here for a person.

Agents rarely call this directly: hitl.HitlRunner turns a HumanInTheLoopMiddleware
pause into inbox rows and resumes the agent once every row in the group is decided.

Decision types (same as LangChain's HITL middleware):
    approve                    run the action as proposed
    edit    + edited_args      run it with the teacher's changes
    reject  + message          don't run it; the message goes back to the agent
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Callable

from .db import connect, now_iso
from .guardrails import required_role

# agent name -> fn(group_id, decisions) that resumes that agent.  Filled by HitlRunner.
_resumers: dict[str, Callable[[str, list[dict[str, Any]]], dict[str, Any]]] = {}


def register_resumer(agent: str, fn: Callable[[str, list[dict[str, Any]]], dict[str, Any]]) -> None:
    _resumers[agent] = fn


def create_group(agent: str, class_id: int | None, thread_id: str | None,
                 actions: list[dict[str, Any]]) -> str:
    """actions: [{name, args, description?, allowed_decisions?}] -> group_id"""
    group_id = f"{agent}-{uuid.uuid4().hex[:12]}"
    with connect() as conn:
        for pos, a in enumerate(actions):
            conn.execute(
                """INSERT INTO approvals (group_id, position, agent, class_id, thread_id, action_name,
                                          action_args, description, allowed_decisions, required_role)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (group_id, pos, agent, class_id, thread_id, a["name"], json.dumps(a.get("args", {})),
                 a.get("description"), json.dumps(a.get("allowed_decisions", ["approve", "edit", "reject"])),
                 required_role(a["name"])),
            )
    return group_id


def _row(r: Any) -> dict[str, Any]:
    d = dict(r)
    d["action_args"] = json.loads(d["action_args"])
    d["allowed_decisions"] = json.loads(d["allowed_decisions"])
    d["decision"] = json.loads(d["decision"]) if d["decision"] else None
    return d


def list_approvals(*, class_id: int | None = None, status: str | None = "pending",
                   agent: str | None = None) -> list[dict[str, Any]]:
    sql, params = "SELECT * FROM approvals WHERE 1 = 1", []
    if class_id is not None:
        sql += " AND (class_id = ? OR class_id IS NULL)"
        params.append(class_id)
    if status:
        sql += " AND status = ?"
        params.append(status)
    if agent:
        sql += " AND agent = ?"
        params.append(agent)
    sql += " ORDER BY created_at DESC, group_id, position"
    with connect() as conn:
        return [_row(r) for r in conn.execute(sql, params).fetchall()]


def get(approval_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        r = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
    return _row(r) if r else None


def _to_hitl_decision(row: dict[str, Any]) -> dict[str, Any]:
    return row["decision"]


class ResumeFailed(RuntimeError):
    """Resuming the agent after a decision failed. still_waiting: the graph is still paused at
    the approval (the decided action never ran), so the decision can safely be undone."""

    def __init__(self, message: str, *, still_waiting: bool):
        super().__init__(message)
        self.still_waiting = still_waiting


def decide(approval_id: int, decision_type: str, *, edited_args: dict[str, Any] | None = None,
           message: str | None = None, decided_by: str = "teacher", role: str = "teacher") -> dict[str, Any]:
    """Record one decision.  When the whole group is decided, resume the agent."""
    row = get(approval_id)
    if row is None:
        raise LookupError(f"Approval {approval_id} not found")
    if row["status"] != "pending":
        raise ValueError(f"Approval {approval_id} is already {row['status']}")
    if decision_type not in row["allowed_decisions"]:
        raise ValueError(f"'{decision_type}' is not allowed here (allowed: {row['allowed_decisions']})")
    if row["required_role"] == "admin" and role != "admin":
        raise PermissionError(f"'{row['action_name']}' needs admin approval")

    if decision_type == "approve":
        decision, status = {"type": "approve"}, "approved"
    elif decision_type == "edit":
        if edited_args is None:
            raise ValueError("edit needs edited_args")
        decision = {"type": "edit", "edited_action": {"name": row["action_name"], "args": edited_args}}
        status = "edited"
    elif decision_type == "reject":
        decision = {"type": "reject", "message": message or "Rejected by the teacher."}
        status = "rejected"
    else:
        raise ValueError(f"Unknown decision type '{decision_type}'")

    with connect() as conn:
        conn.execute(
            "UPDATE approvals SET status = ?, decision = ?, decided_by = ?, decided_at = ? WHERE approval_id = ?",
            (status, json.dumps(decision), decided_by, now_iso(), approval_id),
        )
        remaining = conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE group_id = ? AND status = 'pending'", (row["group_id"],)
        ).fetchone()[0]

    if remaining:
        return {"status": "recorded", "group_id": row["group_id"], "pending_in_group": remaining}

    with connect() as conn:
        rows = [_row(r) for r in conn.execute(
            "SELECT * FROM approvals WHERE group_id = ? ORDER BY position", (row["group_id"],)
        ).fetchall()]
    resumer = _resumers.get(row["agent"])
    if resumer is None:
        return {"status": "recorded", "group_id": row["group_id"], "note": f"no resumer registered for {row['agent']}"}
    try:
        result = resumer(row["group_id"], [_to_hitl_decision(r) for r in rows])
    except Exception as exc:
        # Undo the decision only if its action never ran (e.g. the agent's model key is missing
        # and the graph is still paused), so the teacher can try again. If the action already ran
        # and only a later step failed, the decision stands: reverting would let a "reject"
        # be recorded for something that was already published.
        if getattr(exc, "still_waiting", True):
            with connect() as conn:
                conn.execute("UPDATE approvals SET status = 'pending', decision = NULL, decided_by = NULL, "
                             "decided_at = NULL WHERE group_id = ?", (row["group_id"],))
        raise
    return {"status": "resumed", "group_id": row["group_id"], "result": result}
