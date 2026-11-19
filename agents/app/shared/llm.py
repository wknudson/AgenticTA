"""get_model(agent, role) -> a LangChain chat model, chosen in agents/config.yaml.

    from app.shared.llm import get_model
    model = get_model("scheduler")             # role "main"
    planner = get_model("materials", "planner")

Keys come from the agent's own .env first, then the project .env (see settings.py).
A teammate can try another model without touching the shared config.yaml by putting
MODEL_<ROLE>=provider:model in their agent's .env, e.g. MODEL_MAIN=anthropic:claude-sonnet-5-5.

Offline mode: pass a `script` (list of AIMessages) to get a scripted fake model instead
of a real one.  The demo endpoints use this so the whole loop (tools, HITL pause,
Approvals inbox, resume) can be clicked through with no API key, and tests use it too.
"""
from __future__ import annotations

from typing import Any, Sequence

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from .settings import PROVIDER_KEYS, agent_config, agent_setting, provider_key

# The keyword each LangChain provider class uses for its API key.
_KEY_KWARG = {"openai": "api_key", "anthropic": "api_key", "google_genai": "google_api_key"}


class MissingApiKey(RuntimeError):
    pass


def model_spec(agent: str, role: str = "main") -> dict[str, Any]:
    """{provider, model} for a role: the agent's MODEL_<ROLE> override, else config.yaml."""
    models = agent_config(agent).get("models", {})
    if role not in models:
        raise KeyError(f"Agent '{agent}' has no model role '{role}' in config.yaml (has: {list(models)})")
    override = agent_setting(agent, f"MODEL_{role.upper()}")
    if override and ":" in override:
        provider, model = override.split(":", 1)
        return {"provider": provider.strip(), "model": model.strip(), "overridden": True}
    return models[role]


def get_model(agent: str, role: str = "main", *, script: Sequence[AIMessage] | None = None, **kwargs: Any) -> BaseChatModel:
    if script is not None:
        return ScriptedChatModel(responses=list(script))
    spec = model_spec(agent, role)
    provider, model = spec["provider"], spec["model"]
    env_var = PROVIDER_KEYS.get(provider)
    if env_var:
        key = provider_key(agent, provider)
        if not key:
            raise MissingApiKey(
                f"{agent}/{role} uses {provider}:{model} but {env_var} is not set "
                f"(agents/app/agents/{agent}/.env or the project .env)"
            )
        kwargs.setdefault(_KEY_KWARG.get(provider, "api_key"), key)
    elif provider == "ollama":
        kwargs.setdefault("base_url", agent_setting(agent, "OLLAMA_BASE_URL", "http://localhost:11434"))
    return init_chat_model(model, model_provider=provider, **kwargs)


class ScriptedChatModel(FakeMessagesListChatModel):
    """Replays a fixed list of AIMessages (tool calls included).  For offline demos and tests."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":  # type: ignore[override]
        return self
