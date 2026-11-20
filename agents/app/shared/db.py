"""The shared SQLite file.

Express owns the app tables (students, classes, assignments, ...: backend/db/schema.sql).
This service owns the agent tables: app/shared/schema.sql plus each agent's own
app/agents/<name>/schema.sql.  All of them are applied with CREATE TABLE IF NOT EXISTS
on startup, so a teammate adds a table by editing their agent's schema.sql.

Usage:
    from app.shared.db import connect
    with connect() as conn:
        rows = conn.execute("SELECT * FROM assignments WHERE class_id = ?", (class_id,)).fetchall()
        # rows are sqlite3.Row: row["assignment_name"]; dict(row) for JSON
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import sqlite_vec

from .settings import AGENTS_DIR, DB_PATH


def now_iso() -> str:
    """Same timestamp format the Express app uses: 2026-11-19T21:02:17.123Z"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _open() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)  # vector search: vec0 virtual tables, vec_distance_cosine(), ...
    conn.enable_load_extension(False)
    return conn


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """One connection per unit of work; commits on success, rolls back on error."""
    conn = _open()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def schema_files() -> list[Path]:
    shared = AGENTS_DIR / "app" / "shared" / "schema.sql"
    per_agent = sorted((AGENTS_DIR / "app" / "agents").glob("*/schema.sql"))
    return [shared, *per_agent]


# Columns added after a table first shipped.  CREATE TABLE IF NOT EXISTS won't add them to a
# teammate's existing database, so init_db adds any that are missing.  Append, never edit.
ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "library_files": {
        "label_source": "TEXT",
        "review_reason": "TEXT",
        "extract_method": "TEXT",
        "page_count": "INTEGER",
        "embedded": "INTEGER NOT NULL DEFAULT 0",
        "ai_pending": "INTEGER NOT NULL DEFAULT 0",
        "ai_queued_at": "TEXT",
    },
}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    for table, cols in ADDED_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in cols.items():
            if have and name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db() -> None:
    """Create agent tables.  Requires the Express tables to exist (`npm run db:init`)."""
    with connect() as conn:
        has_app = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'classes'"
        ).fetchone()
        if not has_app:
            raise RuntimeError(f"{DB_PATH} has no app tables yet. Run `npm run db:init` from the repo root first.")
        for table in ADDED_COLUMNS:  # existing tables first, so indexes in schema.sql can use new columns
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone():
                _add_missing_columns(conn)
                break
        for path in schema_files():
            conn.executescript(path.read_text(encoding="utf-8"))
        _add_missing_columns(conn)
        # Old databases had chunks before the keyword index existed: build it once.
        fts_rows = conn.execute("SELECT COUNT(*) FROM library_chunks_fts").fetchone()[0]
        chunk_rows = conn.execute("SELECT COUNT(*) FROM library_chunks").fetchone()[0]
        if chunk_rows and not fts_rows:
            conn.execute("INSERT INTO library_chunks_fts(library_chunks_fts) VALUES ('rebuild')")
    from .library import ensure_vector_index  # noqa: PLC0415 (avoid import cycle)

    ensure_vector_index()
