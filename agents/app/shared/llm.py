"""get_model(agent, role) -> a LangChain chat model, chosen in agents/config.yaml.

    from app.shared.llm import get_model
    model = get_model("scheduler")             # role "main"
    planner = get_model("materials", "planner")

Offline mode: pass a `script` (list of AIMessages) to get a scripted fake model instead
of a real one.  The demo endpoints use this so the whole loop (tools, HITL pause,
Approvals inbox, resume) can be clicked through with no API key, and tests use it too.
"""
from __future__ import annotations

import os
from typing import Any, Sequence

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from .settings import PROVIDER_KEYS, agent_config


class MissingApiKey(RuntimeError):
    pass


def model_spec(agent: str, role: str = "main") -> dict[str, Any]:
    models = agent_config(agent).get("models", {})
    if role not in models:
        raise KeyError(f"Agent '{agent}' has no model role '{role}' in config.yaml (has: {list(models)})")
    return models[role]


def get_model(agent: str, role: str = "main", *, script: Sequence[AIMessage] | None = None, **kwargs: Any) -> BaseChatModel:
    if script is not None:
        return ScriptedChatModel(responses=list(script))
    spec = model_spec(agent, role)
    provider, model = spec["provider"], spec["model"]
    env_var = PROVIDER_KEYS.get(provider)
    if env_var and not os.getenv(env_var):
        raise MissingApiKey(f"{agent}/{role} uses {provider}:{model} but {env_var} is not set in .env")
    return init_chat_model(model, model_provider=provider, **kwargs)


class ScriptedChatModel(FakeMessagesListChatModel):
    """Replays a fixed list of AIMessages (tool calls included).  For offline demos and tests."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":  # type: ignore[override]
        return self
