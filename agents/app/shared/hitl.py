"""Run an agent graph and connect its human-in-the-loop pauses to the Approvals inbox.

Works for both kinds of graph used in this project:
  - create_agent(...) with HumanInTheLoopMiddleware (scheduler, materials)
  - a hand-built StateGraph whose node calls interrupt(hitl_request(...)) (games)

    runner = HitlRunner("scheduler", build_agent)
    out = runner.run({"messages": [("user", "Build the calendar for unit 3")]}, class_id=1)
    # out["status"] == "waiting_for_approval" -> rows appear in the inbox
    # the teacher decides in the UI -> approvals.decide(...) -> runner.resume(...) automatically
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Callable

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from . import approvals
from .db import connect, now_iso
from .llm import MissingApiKey
from .settings import CHECKPOINT_DB_PATH
from .tracing import agent_trace

_checkpointer: SqliteSaver | None = None


def checkpointer() -> SqliteSaver:
    """Durable LangGraph checkpoints (Module 10: never MemorySaver outside tests)."""
    global _checkpointer
    if _checkpointer is None:
        CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(CHECKPOINT_DB_PATH, check_same_thread=False)
        _checkpointer = SqliteSaver(conn)
    return _checkpointer


def hitl_request(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Build an interrupt payload in HumanInTheLoopMiddleware's format, for hand-built graphs.

    actions: [{name, args, description?, allowed_decisions?}]
    In the node:  decisions = interrupt(hitl_request([...]))["decisions"]
    """
    return {
        "action_requests": [
            {"name": a["name"], "args": a.get("args", {}), "description": a.get("description", "")} for a in actions
        ],
        "review_configs": [
            {"action_name": a["name"], "allowed_decisions": a.get("allowed_decisions", ["approve", "edit", "reject"])}
            for a in actions
        ],
    }


def _last_text(result: dict[str, Any]) -> str | None:
    msgs = result.get("messages") or []
    for m in reversed(msgs):
        content = getattr(m, "content", None)
        if getattr(m, "type", "") == "ai" and content:
            return content if isinstance(content, str) else json.dumps(content)
    return None


class HitlRunner:
    def __init__(self, agent: str, build_graph: Callable[..., Any]):
        self.agent = agent
        self.build_graph = build_graph
        # Graphs built from a scripted (offline) model must be reused to continue the script.
        self._live_graphs: dict[str, Any] = {}
        approvals.register_resumer(agent, self.resume)

    def run(self, graph_input: Any, *, class_id: int | None, thread_id: str | None = None,
            graph: Any = None, **build_kwargs: Any) -> dict[str, Any]:
        thread_id = thread_id or f"{self.agent}-{uuid.uuid4().hex[:12]}"
        graph = graph or self.build_graph(**build_kwargs)
        self._live_graphs[thread_id] = graph
        return self._invoke(graph, graph_input, thread_id, class_id)

    def resume(self, group_id: str, decisions: list[dict[str, Any]]) -> dict[str, Any]:
        with connect() as conn:
            r = conn.execute(
                "SELECT thread_id, class_id FROM approvals WHERE group_id = ? LIMIT 1", (group_id,)
            ).fetchone()
        thread_id, class_id = r["thread_id"], r["class_id"]
        graph = None
        try:
            graph = self._live_graphs.get(thread_id) or self._rebuild_for_resume()
            return self._invoke(graph, Command(resume={"decisions": decisions}), thread_id, class_id)
        except Exception as exc:
            raise approvals.ResumeFailed(str(exc), still_waiting=self._still_waiting(graph, thread_id)) from exc

    @staticmethod
    def _still_waiting(graph: Any, thread_id: str) -> bool:
        """Is the checkpoint still paused at an approval (so the approved action never ran)?"""
        if graph is None:
            return True
        try:
            snap = graph.get_state({"configurable": {"thread_id": thread_id}})
            return any(getattr(t, "interrupts", ()) for t in snap.tasks)
        except Exception:  # can't tell: assume nothing ran, so the teacher can retry
            return True

    def _rebuild_for_resume(self) -> Any:
        """The graph that paused is gone (the service restarted). Rebuild it from the checkpoint.

        A run drafted without a model (offline demo, the scheduler's no-AI draft) can still be
        approved when that agent has no API key: the approved tool call runs from the checkpoint,
        and only the closing message comes from a one-line scripted model.
        """
        try:
            return self.build_graph()
        except MissingApiKey:
            from langchain_core.messages import AIMessage  # noqa: PLC0415

            try:
                return self.build_graph(script=[AIMessage("Finished.")])
            except TypeError:  # this agent's graph doesn't take a script
                raise

    def _invoke(self, graph: Any, graph_input: Any, thread_id: str, class_id: int | None) -> dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id}, "run_name": f"{self.agent}",
                  "metadata": {"class_id": class_id, "thread_id": thread_id}}
        with connect() as conn:
            run_id = conn.execute(
                "INSERT INTO agent_runs (agent, class_id, thread_id, status) VALUES (?, ?, ?, 'running')",
                (self.agent, class_id, thread_id),
            ).lastrowid
        try:
            with agent_trace(self.agent, class_id=class_id):
                result = graph.invoke(graph_input, config=config)
        except Exception as e:
            self._finish(run_id, "error", str(e))
            raise

        interrupts = result.get("__interrupt__") or []
        if interrupts:
            group_ids = []
            for intr in interrupts:
                value = intr.value
                configs = {c["action_name"]: c for c in value.get("review_configs", [])}
                actions = [
                    {**a, "allowed_decisions": configs.get(a["name"], {}).get("allowed_decisions",
                                                                                ["approve", "edit", "reject"])}
                    for a in value.get("action_requests", [])
                ]
                group_ids.append(approvals.create_group(self.agent, class_id, thread_id, actions))
            self._finish(run_id, "waiting_for_approval", f"{len(group_ids)} approval group(s)")
            return {"status": "waiting_for_approval", "thread_id": thread_id, "approval_groups": group_ids}

        self._live_graphs.pop(thread_id, None)
        text = _last_text(result)
        self._finish(run_id, "done", text)
        return {"status": "done", "thread_id": thread_id, "output": text,
                "state": {k: v for k, v in result.items() if k != "messages" and _jsonable(v)}}

    @staticmethod
    def _finish(run_id: int, status: str, summary: str | None) -> None:
        with connect() as conn:
            conn.execute("UPDATE agent_runs SET status = ?, summary = ?, finished_at = ? WHERE run_id = ?",
                         (status, (summary or "")[:2000], now_iso(), run_id))


def _jsonable(v: Any) -> bool:
    try:
        json.dumps(v)
        return True
    except TypeError:
        return False
