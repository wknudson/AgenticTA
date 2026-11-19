"""Paths, environment and config.yaml.

Two levels of .env (both gitignored, both created from their .env.example by `npm run setup`):

  AgenticTA/.env                          PROJECT-WIDE: LangSmith, database path, ports, the
                                          Express app's OpenAI key.  Loaded into os.environ.
  agents/app/agents/<agent>/.env          PER AGENT: that agent's provider keys and personal
                                          overrides.  NOT loaded into os.environ, so two agents
                                          can use different keys for the same provider.

Lookup order for an agent setting: the agent's .env, then the project .env / real environment.
So a single key in the project .env still works for every agent.

Per-agent overrides you can put in an agent's .env (handy for experiments, nothing to commit):
  MODEL_<ROLE>=provider:model      e.g. MODEL_MAIN=anthropic:claude-sonnet-5-5
  LANGSMITH_PROJECT=my-experiment  send this agent's traces to a different LangSmith project
  OLLAMA_BASE_URL=http://localhost:11434
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values, load_dotenv

AGENTS_DIR = Path(__file__).resolve().parents[2]  # .../AgenticTA/agents
REPO_ROOT = AGENTS_DIR.parent                     # .../AgenticTA

load_dotenv(REPO_ROOT / ".env")  # project-wide settings -> os.environ (real env vars win)

DB_PATH = (REPO_ROOT / os.getenv("SQLITE_DB_PATH", "data/agenticta.sqlite")).resolve()
CHECKPOINT_DB_PATH = DB_PATH.with_name("checkpoints.sqlite")  # LangGraph state for paused agents
FILES_DIR = DB_PATH.parent / "files"                          # uploaded originals + new versions

PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "ollama": None,  # local, no key
}


@lru_cache
def config() -> dict[str, Any]:
    with open(AGENTS_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def agent_config(agent: str) -> dict[str, Any]:
    try:
        return config()["agents"][agent]
    except KeyError as e:
        raise KeyError(f"Agent '{agent}' is not in agents/config.yaml") from e


def agent_env_path(agent: str) -> Path:
    # AGENTICTA_AGENT_ENV_DIR lets tests point at a scratch folder instead of real key files.
    base = Path(os.getenv("AGENTICTA_AGENT_ENV_DIR") or AGENTS_DIR / "app" / "agents")
    return base / agent / ".env"


@lru_cache
def agent_env(agent: str) -> dict[str, str]:
    """The agent's own .env as a dict (empty if it doesn't exist).  Restart the service after editing."""
    path = agent_env_path(agent)
    return {k: v for k, v in dotenv_values(path).items() if v} if path.is_file() else {}


def agent_setting(agent: str, name: str, default: str | None = None) -> str | None:
    """Agent .env first, then the project .env / environment."""
    return agent_env(agent).get(name) or os.getenv(name) or default


def provider_key(agent: str, provider: str) -> str | None:
    env_var = PROVIDER_KEYS.get(provider)
    return agent_setting(agent, env_var) if env_var else None


def has_provider_key(agent: str, provider: str) -> bool:
    return PROVIDER_KEYS.get(provider) is None or bool(provider_key(agent, provider))


def langsmith_enabled() -> bool:
    return bool(os.getenv("LANGSMITH_API_KEY")) and os.getenv("LANGSMITH_TRACING", "").lower() == "true"


def key_status(agent: str | None = None) -> dict[str, bool]:
    """Which providers have a key, for one agent (its .env + project .env) or the project only.
    Never returns the keys themselves."""
    if agent is None:
        status = {p: (bool(os.getenv(env)) if env else True) for p, env in PROVIDER_KEYS.items()}
    else:
        status = {p: has_provider_key(agent, p) for p in PROVIDER_KEYS}
    status["langsmith"] = langsmith_enabled()
    return status
