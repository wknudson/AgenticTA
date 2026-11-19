"""Guardrails shared by every agent (Module 10).

1. HARD BLOCKS: actions no agent may ever take, whatever the prompt says.
   - Enforced twice: at build time (assert_safe_toolset) and at run time
     (BlockedActionsMiddleware), so a renamed or dynamically added tool is still caught.
2. Deterministic checks: small pure functions agents call before acting.
   They are fast and predictable and they show up in LangSmith as tool results.
3. Approval authority: who must approve what (used by the Approvals inbox).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Callable, Iterable

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

# ---------------------------------------------------------------- 1. hard blocks
BLOCKED_ACTION_PATTERNS = [
    # change_grade, update_grades, override_grade ... (grades stay teacher-only; check_grade_level is fine)
    r"(change|update|set|edit|override|modify)_\w*grades?\b|\bgrades?_(change|update|override|edit)",
    # delete_file, drop_table ... (archive instead)
    r"(^|_)(delete|drop|purge)(_|$)",
    # nothing leaves the app
    r"send_(email|sms|text|message)|(^|_)email_|notify_parent",
]
_BLOCKED = re.compile("|".join(BLOCKED_ACTION_PATTERNS), re.IGNORECASE)


def is_blocked(action_name: str) -> bool:
    return bool(_BLOCKED.search(action_name))


def assert_safe_toolset(tools: Iterable[Any]) -> None:
    """Call when building an agent.  Fails loudly if a forbidden tool is registered."""
    for t in tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", str(t))
        if is_blocked(name):
            raise ValueError(f"Tool '{name}' matches a hard-blocked action (grades, deletes, outbound messages).")


class BlockedActionsMiddleware(AgentMiddleware):
    """Runtime backstop: refuses any blocked tool call and tells the model why."""

    def wrap_tool_call(self, request, handler: Callable):  # type: ignore[override]
        name = request.tool_call["name"]
        if is_blocked(name):
            return ToolMessage(
                content=f"BLOCKED by guardrail: agents may not perform '{name}'. Suggest it to the teacher instead.",
                tool_call_id=request.tool_call["id"],
                name=name,
                status="error",
            )
        return handler(request)


# ---------------------------------------------------------------- 2. deterministic checks
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")


def contains_pii(text: str) -> bool:
    return bool(EMAIL_RE.search(text) or PHONE_RE.search(text))


def within_range(d: date, start: date, end: date) -> bool:
    return start <= d <= end


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


# ---------------------------------------------------------------- 3. approval authority
# Who must approve which action.  Anything not listed defaults to the teacher.
APPROVAL_AUTHORITY: dict[str, str] = {
    "publish_calendar": "teacher",
    "apply_revision": "teacher",
    "update_assignment": "teacher",
    "publish_activity": "teacher",
    "apply_to_all_classes": "admin",
}


def required_role(action_name: str) -> str:
    return APPROVAL_AUTHORITY.get(action_name, "teacher")
