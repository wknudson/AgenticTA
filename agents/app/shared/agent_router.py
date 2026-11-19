"""Every agent's router starts from make_router(), which adds:

    GET /agents/<name>/info   what this agent is (from config.yaml) + whether its keys are set
    GET /agents/<name>/ping   a traced no-LLM call; proves the agent's LangSmith project works
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from langsmith import traceable

from .llm import MissingApiKey, model_spec
from .settings import agent_config, key_status
from .tracing import agent_trace, project_name


def agent_info(agent: str) -> dict[str, Any]:
    cfg = agent_config(agent)
    keys = key_status()
    models = {role: {**spec, "key_set": keys.get(spec["provider"], False)}
              for role, spec in cfg.get("models", {}).items()}
    return {
        "name": agent,
        "title": cfg.get("title", agent),
        "owner": cfg.get("owner"),
        "kind": cfg.get("kind"),
        "pattern": cfg.get("pattern"),
        "models": models,
        "ready": all(m["key_set"] for m in models.values()),
        "langsmith_project": project_name(agent),
    }


def make_router(agent: str) -> APIRouter:
    router = APIRouter(tags=[agent])

    @traceable(name=f"{agent}.ping")
    def _ping() -> dict[str, Any]:
        return {"agent": agent, "pong": True}

    @router.get("/info")
    def info() -> dict[str, Any]:
        return agent_info(agent)

    @router.get("/ping")
    def ping() -> dict[str, Any]:
        with agent_trace(agent):
            out = _ping()
        return {**out, "traced_to": project_name(agent) if key_status()["langsmith"] else None}

    return router


def require_models(agent: str, *roles: str) -> None:
    """Raise MissingApiKey early (-> HTTP 503) if a role's provider has no key."""
    keys = key_status()
    missing = [r for r in (roles or ("main",)) if not keys.get(model_spec(agent, r)["provider"], False)]
    if missing:
        raise MissingApiKey(f"{agent}: no API key for role(s) {missing}. Add the key to .env or use the offline demo.")
