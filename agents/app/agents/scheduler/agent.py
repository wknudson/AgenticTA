"""Scheduler agent: semi-autonomous single agent (create_agent) with deterministic tools.

Middleware stack (Module 10), outermost first:
  BlockedActionsMiddleware   hard blocks shared by every agent
  ToolCallLimitMiddleware    a runaway loop can't call tools forever
  HumanInTheLoopMiddleware   publish_calendar waits in the Approvals inbox
"""
from __future__ import annotations

from typing import Sequence
from datetime import date, timedelta
import json

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, ToolCallLimitMiddleware
from langchain_core.messages import AIMessage

from app.shared.guardrails import BlockedActionsMiddleware, assert_safe_toolset
from app.shared.hitl import HitlRunner, checkpointer
from app.shared.llm import get_model

from .prompts import SYSTEM_PROMPT
from .tools import TOOLS
from .tools import check_conflicts, propose_events
from .calendar import load_term, save_term, TermSettings


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
    term = load_term(class_id)
    if term is None:
        term = save_term(class_id, TermSettings(term_start="2026-08-24", term_end="2026-12-18"))
    events = []
    # Keep the demo useful when a teacher runs it partway through the term.
    day = max(date.fromisoformat(term["term_start"]), date.today())
    while len(events) < 2 and day <= date.fromisoformat(term["term_end"]):
        event = {"title": "Demo quiz" if not events else "Demo lab report",
                 "date": day.isoformat(), "kind": "assessment", "source": "offline demo (synthetic)"}
        if json.loads(check_conflicts.invoke({"class_id": class_id, "events": [event]}))["ok"]:
            events.append(event)
        day += timedelta(days=1)
    if len(events) < 2:
        raise ValueError("The demo needs two available school days in the configured term.")
    ids = json.loads(propose_events.invoke({"class_id": class_id, "events": events}))["proposed_event_ids"]
    return [
        AIMessage("", tool_calls=[{"name": "get_assignments", "args": {"class_id": class_id}, "id": "c1"}]),
        AIMessage("", tool_calls=[{"name": "check_conflicts", "args": {"class_id": class_id, "events": events}, "id": "c2"}]),
        AIMessage("", tool_calls=[{"name": "publish_calendar", "args": {"class_id": class_id, "event_ids": ids}, "id": "c4"}]),
        AIMessage("Offline demo finished: 2 events went through the approval step."),
    ]


def publish_script(class_id: int, events: list[dict], event_ids: list[int], summary: str) -> list[AIMessage]:
    """The no-AI "draft from documents" path: events were drafted by code (drafting.py) and
    already proposed; this replays the same check + publish tool calls so the teacher approves
    them in the Approvals inbox exactly like an AI-built calendar."""
    return [
        AIMessage("", tool_calls=[{"name": "check_conflicts", "args": {"class_id": class_id, "events": events}, "id": "d1"}]),
        AIMessage("", tool_calls=[{"name": "publish_calendar", "args": {"class_id": class_id, "event_ids": event_ids}, "id": "d2"}]),
        AIMessage(summary),
    ]
