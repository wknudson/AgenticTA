"""Materials-update agent: planner + workers (Hierarchical task decomposition).

Skeleton: one create_agent planner (strong model) with TodoListMiddleware so the plan is
visible, and HITL on every write.  TODO(Teammate C): split execution into worker calls on
the cheap 'editor' model (e.g. a sub-agent per file, run in parallel) and compare cost
and latency against planner-does-everything in LangSmith.
"""
from __future__ import annotations

from typing import Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    SummarizationMiddleware,
    TodoListMiddleware,
)
from langchain_core.messages import AIMessage

from app.shared.guardrails import BlockedActionsMiddleware, assert_safe_toolset
from app.shared.hitl import HitlRunner, checkpointer
from app.shared.llm import get_model

from .prompts import SYSTEM_PROMPT
from .tools import TOOLS


def build_agent(script: Sequence[AIMessage] | None = None):
    assert_safe_toolset(TOOLS)
    middleware = [
        BlockedActionsMiddleware(),
        TodoListMiddleware(),
        ModelCallLimitMiddleware(run_limit=25),
        HumanInTheLoopMiddleware(
            interrupt_on={
                "apply_revision": {"allowed_decisions": ["approve", "reject"],
                                   "description": "Replace the current version with this revision?"},
                "update_assignment": {"allowed_decisions": ["approve", "edit", "reject"],
                                      "description": "Change this assignment?"},
            }
        ),
    ]
    if script is None:  # long documents: summarize old context with the cheap editor model
        middleware.insert(2, SummarizationMiddleware(model=get_model("materials", "editor"),
                                                     trigger=("tokens", 60_000)))
    return create_agent(
        model=get_model("materials", "planner", script=script),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=middleware,
        checkpointer=checkpointer(),
        name="materials",
    )


runner = HitlRunner("materials", build_agent)


def demo_script(class_id: int, file_id: int) -> list[AIMessage]:
    return [
        AIMessage("", tool_calls=[{"name": "search_library", "args": {"class_id": class_id, "query": "unit 3 quiz"}, "id": "m1"}]),
        AIMessage("", tool_calls=[{"name": "draft_revision", "args": {
            "file_id": file_id,
            "new_text": "Biology Unit 3: Cells. Syllabus (revised).\n2026-12-10 Unit 3 quiz (moved back one week).",
            "change_summary": "Moved the Unit 3 quiz back one week."}, "id": "m2"}]),
        AIMessage("Draft created; asking the teacher to apply it.", tool_calls=[
            {"name": "apply_revision", "args": {"draft_file_id": 0}, "id": "m3"}]),  # id patched at runtime
        AIMessage("Offline demo finished."),
    ]
