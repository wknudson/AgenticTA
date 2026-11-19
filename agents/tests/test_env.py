"""Per-agent .env files: scoped keys, project fallback, personal overrides."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.shared import settings
from app.shared.llm import MissingApiKey, get_model, model_spec
from app.shared.tracing import project_name


@pytest.fixture
def agent_env(monkeypatch):
    """Write a .env for an agent in the test scratch folder; caches are cleared around it."""
    base = Path(os.environ["AGENTICTA_AGENT_ENV_DIR"])

    def write(agent: str, text: str) -> None:
        (base / agent).mkdir(parents=True, exist_ok=True)
        (base / agent / ".env").write_text(text, encoding="utf-8")
        settings.agent_env.cache_clear()

    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    settings.agent_env.cache_clear()
    yield write
    for p in base.glob("*/.env"):
        p.unlink()
    settings.agent_env.cache_clear()


def test_keys_are_scoped_to_their_agent(agent_env):
    agent_env("scheduler", "ANTHROPIC_API_KEY=sk-scheduler\n")
    assert settings.provider_key("scheduler", "anthropic") == "sk-scheduler"
    assert settings.provider_key("games", "anthropic") is None, "another agent's key must not leak"
    assert "sk-scheduler" not in os.environ.values(), "agent keys stay out of the process environment"


def test_project_env_is_the_fallback(agent_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-project")
    agent_env("scheduler", "ANTHROPIC_API_KEY=sk-scheduler\n")
    assert settings.provider_key("scheduler", "anthropic") == "sk-scheduler"  # agent wins
    assert settings.provider_key("games", "anthropic") == "sk-project"        # others fall back


def test_missing_key_names_the_agent_env_file(agent_env):
    with pytest.raises(MissingApiKey, match="agents/app/agents/scheduler/.env"):
        get_model("scheduler")


def test_personal_model_and_project_overrides(agent_env):
    agent_env("materials", "MODEL_PLANNER=openai:gpt-6.2-sol\nLANGSMITH_PROJECT=materials-experiments\n")
    assert model_spec("materials", "planner") == {"provider": "openai", "model": "gpt-6.2-sol", "overridden": True}
    assert model_spec("materials", "editor")["model"] == "gpt-6-luna"  # untouched role keeps config.yaml
    assert project_name("materials") == "materials-experiments"
    assert project_name("games") == "agentic-ta-games"


def test_agent_info_reports_per_agent_keys(client, agent_env):
    agent_env("tutor", "OPENAI_API_KEY=sk-tutor\n")
    agents = {a["name"]: a for a in client.get("/agents/health").json()["agents"]}
    assert agents["tutor"]["ready"] is True and agents["tutor"]["env_file"] is True
    assert agents["scheduler"]["ready"] is False
