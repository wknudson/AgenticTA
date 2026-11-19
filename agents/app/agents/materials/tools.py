"""Materials-update tools.  Owner: Teammate C.

Revisions are NEW VERSIONS (library_files.version_of -> original); originals are never
modified, so every change is reversible.  apply_revision and update_assignment are the
consequential tools and pause for teacher approval (see agent.py).
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

from app.shared import library
from app.shared.db import connect


@tool
def search_library(class_id: int, query: str, k: int = 5) -> str:
    """Find passages in the class's filed documents related to the query."""
    return json.dumps([c.to_dict() for c in library.search(query, class_id, k)])


@tool
def read_file(file_id: int) -> str:
    """Full text and labels of one filed document."""
    f = library.get_file(file_id)
    if f is None:
        return json.dumps({"error": f"file {file_id} not found"})
    return json.dumps({**f.to_dict(), "text": library.get_file_text(file_id)})


@tool
def draft_revision(file_id: int, new_text: str, change_summary: str) -> str:
    """Save a revised copy of a document as a DRAFT version (students can't see drafts).
    TODO(Teammate C): have the cheap 'editor' model write new_text from the planner's
    instruction (planner/worker split) instead of the planner writing it directly."""
    original = library.get_file(file_id)
    if original is None:
        return json.dumps({"error": f"file {file_id} not found"})
    with connect() as conn:
        root = original.version_of or original.file_id
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 1) + 1 FROM library_files WHERE file_id = ? OR version_of = ?", (root, root)
        ).fetchone()[0]
        new_id = conn.execute(
            """INSERT INTO library_files (class_id, original_name, stored_path, title, doc_type, unit, summary,
                                          dates_json, label_confidence, status, version, version_of, created_by)
               SELECT class_id, original_name, stored_path, title, doc_type, unit, ?, dates_json, label_confidence,
                      'draft', ?, ?, 'agent:materials'
               FROM library_files WHERE file_id = ?""",
            (change_summary, version, root, file_id),
        ).lastrowid
        conn.execute("INSERT INTO library_chunks (file_id, chunk_idx, text) VALUES (?, 0, ?)", (new_id, new_text))
    # TODO(Teammate C): also write a .docx of the new version under data/files/ for download
    return json.dumps({"draft_file_id": new_id, "version": version, "replaces": file_id})


@tool
def apply_revision(draft_file_id: int) -> str:
    """Make a draft the current version and archive the one it replaces.
    CONSEQUENTIAL: pauses for teacher approval (HITL)."""
    with connect() as conn:
        d = conn.execute("SELECT * FROM library_files WHERE file_id = ? AND status = 'draft'", (draft_file_id,)).fetchone()
        if d is None:
            return json.dumps({"error": "no such draft"})
        root = d["version_of"]
        conn.execute("UPDATE library_files SET status = 'archived' WHERE (file_id = ? OR version_of = ?) AND status IN ('filed','needs_review')", (root, root))
        conn.execute("UPDATE library_files SET status = 'filed' WHERE file_id = ?", (draft_file_id,))
    return json.dumps({"applied": draft_file_id})


@tool
def update_assignment(assignment_id: int, due_date: str | None = None, description: str | None = None) -> str:
    """Change an assignment's due date (ISO 8601) and/or description.  Points and grades are
    out of scope for agents.  CONSEQUENTIAL: pauses for teacher approval (HITL)."""
    sets, params = [], []
    if due_date:
        sets.append("due_date = ?")
        params.append(due_date)
    if description is not None:
        sets.append("description = ?")
        params.append(description)
    if not sets:
        return json.dumps({"error": "nothing to update"})
    with connect() as conn:
        n = conn.execute(f"UPDATE assignments SET {', '.join(sets)} WHERE assignment_id = ?",
                         (*params, assignment_id)).rowcount
    return json.dumps({"updated": n})


TOOLS = [search_library, read_file, draft_revision, apply_revision, update_assignment]
