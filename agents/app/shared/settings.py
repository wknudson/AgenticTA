"""Paths, environment and config.yaml.  Everything reads the ONE repo-root .env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

AGENTS_DIR = Path(__file__).resolve().parents[2]  # .../AgenticTA/agents
REPO_ROOT = AGENTS_DIR.parent                     # .../AgenticTA

load_dotenv(REPO_ROOT / ".env")

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


def key_status() -> dict[str, bool]:
    """Which providers have a key configured (never returns the keys themselves)."""
    status = {p: (bool(os.getenv(env)) if env else True) for p, env in PROVIDER_KEYS.items()}
    status["langsmith"] = bool(os.getenv("LANGSMITH_API_KEY")) and os.getenv("LANGSMITH_TRACING", "").lower() == "true"
    return status
