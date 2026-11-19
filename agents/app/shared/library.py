"""The library contract: how every agent reads the teacher's filed documents.

Owner: Will (filing pipeline).  Other agents only CALL these functions; they never
query library_* tables directly, so the filing owner can change storage freely.

    from app.shared import library
    hits = library.search("photosynthesis lab", class_id=1, k=5)
    for h in hits: print(h.file_title, h.score, h.text[:80])

Current state (skeleton): search() is a simple keyword search so teammates can build
against it today.  TODO(Will): switch to vector search over library_chunk_vec (fastembed
+ sqlite-vec) once the filing pipeline writes embeddings; keep the same signature.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .db import connect


@dataclass
class LibraryFile:
    file_id: int
    class_id: int
    original_name: str
    title: str | None
    doc_type: str | None
    unit: str | None
    summary: str | None
    dates: list[dict[str, Any]] = field(default_factory=list)
    status: str = "filed"
    version: int = 1
    version_of: int | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Chunk:
    chunk_id: int
    file_id: int
    file_title: str
    doc_type: str | None
    unit: str | None
    page: int | None
    text: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _row_to_file(r: Any) -> LibraryFile:
    return LibraryFile(
        file_id=r["file_id"], class_id=r["class_id"], original_name=r["original_name"],
        title=r["title"], doc_type=r["doc_type"], unit=r["unit"], summary=r["summary"],
        dates=json.loads(r["dates_json"] or "[]"), status=r["status"], version=r["version"],
        version_of=r["version_of"], created_at=r["created_at"],
    )


def list_files(class_id: int, *, doc_type: str | None = None, unit: str | None = None,
               include_archived: bool = False) -> list[LibraryFile]:
    sql = "SELECT * FROM library_files WHERE class_id = ?"
    params: list[Any] = [class_id]
    if not include_archived:
        sql += " AND status != 'archived'"
    if doc_type:
        sql += " AND doc_type = ?"
        params.append(doc_type)
    if unit:
        sql += " AND unit = ?"
        params.append(unit)
    sql += " ORDER BY unit, doc_type, title"
    with connect() as conn:
        return [_row_to_file(r) for r in conn.execute(sql, params).fetchall()]


def get_file(file_id: int) -> LibraryFile | None:
    with connect() as conn:
        r = conn.execute("SELECT * FROM library_files WHERE file_id = ?", (file_id,)).fetchone()
    return _row_to_file(r) if r else None


def get_file_text(file_id: int) -> str:
    """Full extracted text of a file (all chunks in order)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT text FROM library_chunks WHERE file_id = ? ORDER BY chunk_idx", (file_id,)
        ).fetchall()
    return "\n".join(r["text"] for r in rows)


def search(query: str, class_id: int, k: int = 5, *, doc_type: str | None = None,
           unit: str | None = None) -> list[Chunk]:
    """Top-k chunks for a query within one class.  SKELETON: keyword match, see module docstring."""
    terms = [t for t in query.lower().split() if len(t) > 2] or [query.lower()]
    score_sql = " + ".join("(instr(lower(c.text), ?) > 0)" for _ in terms)
    sql = f"""
        SELECT c.chunk_id, c.file_id, c.page, c.text, f.title, f.original_name, f.doc_type, f.unit,
               ({score_sql}) * 1.0 / {len(terms)} AS score
        FROM library_chunks c JOIN library_files f ON f.file_id = c.file_id
        WHERE f.class_id = ? AND f.status != 'archived'
    """
    params: list[Any] = [*terms, class_id]
    if doc_type:
        sql += " AND f.doc_type = ?"
        params.append(doc_type)
    if unit:
        sql += " AND f.unit = ?"
        params.append(unit)
    sql += " AND score > 0 ORDER BY score DESC, c.chunk_id LIMIT ?"
    params.append(k)
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        Chunk(chunk_id=r["chunk_id"], file_id=r["file_id"], file_title=r["title"] or r["original_name"],
              doc_type=r["doc_type"], unit=r["unit"], page=r["page"], text=r["text"], score=r["score"])
        for r in rows
    ]
