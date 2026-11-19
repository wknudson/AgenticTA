"""One LangSmith project per agent: agentic-ta-filing, agentic-ta-scheduler, ...

    from app.shared.tracing import agent_trace
    with agent_trace("scheduler"):
        graph.invoke(...)          # every LLM call, tool call and middleware step is traced

LangSmith is configured once for the whole project, in the project .env
(LANGSMITH_TRACING=true, LANGSMITH_API_KEY, LANGSMITH_ENDPOINT).  Without them the code
runs the same and simply sends nothing.  An agent's own .env may set LANGSMITH_PROJECT to
send just that agent's traces somewhere else (e.g. while experimenting).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import langsmith

from .settings import agent_env, config, langsmith_enabled


def project_name(agent: str) -> str:
    return agent_env(agent).get("LANGSMITH_PROJECT") or f"{config().get('langsmith_project_prefix', 'agentic-ta')}-{agent}"


@contextmanager
def agent_trace(agent: str, **metadata: object) -> Iterator[None]:
    with langsmith.tracing_context(
        project_name=project_name(agent),
        enabled=langsmith_enabled(),
        tags=[f"agent:{agent}"],
        metadata={"agent": agent, **metadata},
    ):
        yield
