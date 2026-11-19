"""Every test session gets a throwaway copy of the database (Express schema + seed)."""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_tmp = Path(tempfile.mkdtemp(prefix="agenticta-test-"))
os.environ["SQLITE_DB_PATH"] = str(_tmp / "test.sqlite")
os.environ["LANGSMITH_TRACING"] = "false"  # tests never send traces
# Ignore everyone's real agents/app/agents/<agent>/.env files; tests write their own here.
os.environ["AGENTICTA_AGENT_ENV_DIR"] = str(_tmp / "agent-env")
# ...and never fall back to real keys from the project .env (empty string = "not set").
for _var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
    os.environ[_var] = ""
# Offline, deterministic embeddings (hashing, not semantic) so search plumbing is testable.
os.environ["AGENTICTA_EMBEDDINGS"] = "fake"

_conn = sqlite3.connect(os.environ["SQLITE_DB_PATH"])
for name in ("schema.sql", "seed.sql"):
    _conn.executescript((REPO_ROOT / "backend" / "db" / name).read_text(encoding="utf-8"))
_conn.commit()
_conn.close()


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
