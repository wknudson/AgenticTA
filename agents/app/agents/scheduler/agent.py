"""Scheduler agent: semi-autonomous single agent (create_agent) with deterministic tools.

Middleware stack (Module 10), outermost first:
  BlockedActionsMiddleware   hard blocks shared by every agent
  ToolCallLimitMiddleware    a runaway loop can't call tools forever
  HumanInTheLoopMiddleware   publish_calendar waits in the Approvals inbox
"""
from __future__ import annotations

from typing import Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, ToolCallLimitMiddleware
from langchain_core.messages import AIMessage

from app.shared.guardrails import BlockedActionsMiddleware, assert_safe_toolset
from app.shared.hitl import HitlRunner, checkpointer
from app.shared.llm import get_model

from .prompts import SYSTEM_PROMPT
from .tools import TOOLS


def build_agent(script: Sequence[AIMessage] | None = None):
    assert_safe_toolset(TOOLS)
    return create_agent(
        model=get_model("scheduler", script=script),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            BlockedActionsMiddleware(),
            ToolCallLimitMiddleware(run_limit=15),
            HumanInTheLoopMiddleware(
                interrupt_on={
                    "publish_calendar": {
                        "allowed_decisions": ["approve", "edit", "reject"],
                        "description": "Publish these events to the student calendar?",
                    }
                }
            ),
        ],
        checkpointer=checkpointer(),
        name="scheduler",
    )


runner = HitlRunner("scheduler", build_agent)


def demo_script(class_id: int) -> list[AIMessage]:
    """What a real model would do, scripted, so the offline demo needs no API key."""
    events = [
        {"title": "Unit 3 quiz", "date": "2026-12-03", "kind": "assessment", "source": "demo"},
        {"title": "Lab report due", "date": "2026-12-05", "kind": "assignment_due", "source": "demo"},
    ]
    return [
        AIMessage("", tool_calls=[{"name": "get_assignments", "args": {"class_id": class_id}, "id": "c1"}]),
        AIMessage("", tool_calls=[{"name": "check_conflicts", "args": {"class_id": class_id, "events": events}, "id": "c2"}]),
        AIMessage("", tool_calls=[{"name": "propose_events", "args": {"class_id": class_id, "events": events}, "id": "c3"}]),
        AIMessage("", tool_calls=[{"name": "publish_calendar", "args": {"class_id": class_id, "event_ids": []}, "id": "c4"}]),
        AIMessage("Offline demo finished: 2 events went through the approval step."),
    ]
