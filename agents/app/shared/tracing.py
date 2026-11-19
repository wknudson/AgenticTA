"""One LangSmith project per agent: agentic-ta-filing, agentic-ta-scheduler, ...

    from app.shared.tracing import agent_trace
    with agent_trace("scheduler"):
        graph.invoke(...)          # every LLM call, tool call and middleware step is traced

Tracing turns on when .env has LANGSMITH_TRACING=true and LANGSMITH_API_KEY.  Without
them the code runs the same and simply sends nothing.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import langsmith

from .settings import config, key_status


def project_name(agent: str) -> str:
    return f"{config().get('langsmith_project_prefix', 'agentic-ta')}-{agent}"


@contextmanager
def agent_trace(agent: str, **metadata: object) -> Iterator[None]:
    enabled = key_status()["langsmith"]
    with langsmith.tracing_context(
        project_name=project_name(agent),
        enabled=enabled,
        tags=[f"agent:{agent}"],
        metadata={"agent": agent, **metadata},
    ):
        yield
