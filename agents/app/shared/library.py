"""The library contract: how every agent reads the teacher's filed documents.

Owner: Will (filing pipeline).  Other agents only CALL these functions; they never query
library_* tables directly, so storage can change without breaking anyone.

    from app.shared import library
    hits = library.search("how do plants make food", class_id=3, k=5)        # hybrid (default)
    hits = library.search("Lab 3 rubric", class_id=3, mode="keyword")
    for h in hits: print(h.file_title, h.score, h.match, h.text[:80])

Search modes (Module 4, hybrid retrievers):
    keyword   SQLite FTS5, BM25 ranking: exact terms, names, vocabulary words
    semantic  sqlite-vec cosine KNN over Gemini embeddings: meaning ("make food" ~ photosynthesis)
    hybrid    both, merged with Reciprocal Rank Fusion: score = sum 1 / (60 + rank)
Without an embedding key, semantic/hybrid quietly fall back to keyword.

If you write chunks yourself (e.g. the materials agent's drafts), call index_file(file_id)
afterwards so they become semantically searchable too (keyword search updates automatically).
"""
from __future__ import annotations

import json
import re
import struct
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from langsmith import traceable

from .db import connect
from .embeddings import embedding_spec, get_embedder

RRF_K = 60
SearchMode = Literal["hybrid", "keyword", "semantic"]


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
    label_confidence: float | None = None
    label_source: str | None = None
    review_reason: str | None = None
    extract_method: str | None = None
    mime_type: str | None = None
    ai_pending: bool = False  # waiting in the batched AI queue

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
    match: str = "keyword"  # keyword | semantic | both

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _row_to_file(r: Any) -> LibraryFile:
    keys = r.keys()
    return LibraryFile(
        file_id=r["file_id"], class_id=r["class_id"], original_name=r["original_name"],
        title=r["title"], doc_type=r["doc_type"], unit=r["unit"], summary=r["summary"],
        dates=json.loads(r["dates_json"] or "[]"), status=r["status"], version=r["version"],
        version_of=r["version_of"], created_at=r["created_at"], label_confidence=r["label_confidence"],
        label_source=r["label_source"] if "label_source" in keys else None,
        review_reason=r["review_reason"] if "review_reason" in keys else None,
        extract_method=r["extract_method"] if "extract_method" in keys else None,
        mime_type=r["mime_type"],
        ai_pending=bool(r["ai_pending"]) if "ai_pending" in keys else False,
    )


# ---------------------------------------------------------------- reading
def list_files(class_id: int, *, doc_type: str | None = None, unit: str | None = None,
               status: str | None = None, include_archived: bool = False) -> list[LibraryFile]:
    sql = "SELECT * FROM library_files WHERE class_id = ?"
    params: list[Any] = [class_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    elif not include_archived:
        sql += " AND status NOT IN ('archived', 'draft')"
    if doc_type:
        sql += " AND doc_type = ?"
        params.append(doc_type)
    if unit:
        sql += " AND unit = ?"
        params.append(unit)
    sql += " ORDER BY unit IS NULL, unit, doc_type, title"
    with connect() as conn:
        return [_row_to_file(r) for r in conn.execute(sql, params).fetchall()]


def list_units(class_id: int) -> list[dict[str, Any]]:
    """Folder view: units with file counts per type (archived and drafts excluded)."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT COALESCE(unit, '') AS unit, doc_type, COUNT(*) AS n FROM library_files
               WHERE class_id = ? AND status NOT IN ('archived', 'draft')
               GROUP BY 1, 2 ORDER BY unit = '', 1, 2""",
            (class_id,),
        ).fetchall()
    units: dict[str, dict[str, Any]] = {}
    for r in rows:
        u = units.setdefault(r["unit"], {"unit": r["unit"] or None, "total": 0, "by_type": {}})
        u["by_type"][r["doc_type"] or "other"] = r["n"]
        u["total"] += r["n"]
    return list(units.values())


def known_units(class_id: int) -> list[str]:
    with connect() as conn:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT unit FROM library_files WHERE class_id = ? AND unit IS NOT NULL AND status != 'archived' ORDER BY unit",
            (class_id,),
        ).fetchall()]


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


def stored_path(file_id: int) -> str | None:
    with connect() as conn:
        r = conn.execute("SELECT stored_path FROM library_files WHERE file_id = ?", (file_id,)).fetchone()
    return r["stored_path"] if r else None


# ---------------------------------------------------------------- teacher actions (not agents)
EDITABLE = ("title", "doc_type", "unit", "summary", "dates")


def update_labels(file_id: int, changes: dict[str, Any]) -> LibraryFile | None:
    """Teacher corrections.  Marks the labels as teacher-made and files it (out of review).
    These corrections double as ground truth for evaluating the labeler."""
    sets, params = [], []
    for k, v in changes.items():
        if k not in EDITABLE:
            continue
        if k == "dates":
            sets.append("dates_json = ?")
            params.append(json.dumps(v or []))
        else:
            sets.append(f"{k} = ?")
            params.append(v)
    sets += ["label_source = 'teacher'", "label_confidence = 1.0", "review_reason = NULL",
             "status = CASE WHEN status = 'needs_review' THEN 'filed' ELSE status END"]
    with connect() as conn:
        conn.execute(f"UPDATE library_files SET {', '.join(sets)} WHERE file_id = ?", (*params, file_id))
    return get_file(file_id)


def set_status(file_id: int, status: Literal["filed", "archived"]) -> LibraryFile | None:
    with connect() as conn:
        conn.execute("UPDATE library_files SET status = ? WHERE file_id = ?", (status, file_id))
    return get_file(file_id)


# ---------------------------------------------------------------- vector index
def _vec_bytes(v: list[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


def ensure_vector_index() -> None:
    """Create library_chunk_vec for the configured model/dims; rebuild it if they changed."""
    spec = embedding_spec()
    want = f"{spec['provider']}:{spec['model']}:{spec['dims']}"
    with connect() as conn:
        have = conn.execute("SELECT value FROM library_meta WHERE key = 'embedding'").fetchone()
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'library_chunk_vec'").fetchone()
        if exists and have and have["value"] == want:
            return
        if exists:
            conn.execute("DROP TABLE library_chunk_vec")
            conn.execute("UPDATE library_files SET embedded = 0")
        conn.execute(
            f"""CREATE VIRTUAL TABLE library_chunk_vec USING vec0(
                    class_id INTEGER PARTITION KEY,
                    embedding float[{int(spec['dims'])}] distance_metric=cosine)"""
        )
        conn.execute("INSERT OR REPLACE INTO library_meta (key, value) VALUES ('embedding', ?)", (want,))


def embed_texts(title: str, texts: list[str]) -> list[list[float]] | None:
    """Document embeddings for chunks, or None without a key / during an outage."""
    emb = get_embedder()
    if emb is None or not texts:
        return None
    try:
        return emb.embed_documents([(title, t) for t in texts])
    except Exception:
        return None


def store_vectors(file_id: int, vectors: list[list[float]]) -> int:
    """Save already-computed chunk vectors (same order as chunk_idx) into the vector index."""
    with connect() as conn:
        f = conn.execute("SELECT class_id FROM library_files WHERE file_id = ?", (file_id,)).fetchone()
        ids = [r[0] for r in conn.execute(
            "SELECT chunk_id FROM library_chunks WHERE file_id = ? ORDER BY chunk_idx", (file_id,)).fetchall()]
        if f is None or len(ids) != len(vectors):
            return 0
        conn.execute(f"DELETE FROM library_chunk_vec WHERE rowid IN ({','.join('?' * len(ids))})", ids)
        conn.executemany("INSERT INTO library_chunk_vec (rowid, class_id, embedding) VALUES (?, ?, ?)",
                         [(cid, f["class_id"], _vec_bytes(v)) for cid, v in zip(ids, vectors)])
        conn.execute("UPDATE library_files SET embedded = 1 WHERE file_id = ?", (file_id,))
    return len(ids)


def file_vectors(file_id: int) -> list[list[float]]:
    """The stored chunk vectors of a file (empty if it was never embedded)."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT v.embedding FROM library_chunks c JOIN library_chunk_vec v ON v.rowid = c.chunk_id
               WHERE c.file_id = ? ORDER BY c.chunk_idx""", (file_id,)).fetchall()
    return [list(struct.unpack(f"{len(r[0]) // 4}f", r[0])) for r in rows]


def delete_chunks(file_id: int, conn: Any) -> None:
    """Remove a file's chunks from all three places (chunks, keyword index via trigger, vectors)."""
    ids = [r[0] for r in conn.execute("SELECT chunk_id FROM library_chunks WHERE file_id = ?", (file_id,)).fetchall()]
    if ids:
        conn.execute(f"DELETE FROM library_chunk_vec WHERE rowid IN ({','.join('?' * len(ids))})", ids)
        conn.execute("DELETE FROM library_chunks WHERE file_id = ?", (file_id,))


@traceable(name="library.index_file")
def index_file(file_id: int) -> int:
    """Embed a file's chunks into the vector index.  Returns chunks embedded (0 without a key)."""
    emb = get_embedder()
    if emb is None:
        return 0
    with connect() as conn:
        f = conn.execute("SELECT class_id, title, original_name FROM library_files WHERE file_id = ?", (file_id,)).fetchone()
        chunks = conn.execute("SELECT chunk_id, text FROM library_chunks WHERE file_id = ? ORDER BY chunk_idx", (file_id,)).fetchall()
    if f is None or not chunks:
        return 0
    title = f["title"] or f["original_name"]
    try:
        vectors = emb.embed_documents([(title, c["text"]) for c in chunks])
    except Exception:  # quota/outage: keep the file (keyword search still works); reindex() later
        return 0
    with connect() as conn:
        ids = [c["chunk_id"] for c in chunks]
        conn.execute(f"DELETE FROM library_chunk_vec WHERE rowid IN ({','.join('?' * len(ids))})", ids)
        conn.executemany(
            "INSERT INTO library_chunk_vec (rowid, class_id, embedding) VALUES (?, ?, ?)",
            [(cid, f["class_id"], _vec_bytes(v)) for cid, v in zip(ids, vectors)],
        )
        conn.execute("UPDATE library_files SET embedded = 1 WHERE file_id = ?", (file_id,))
    return len(chunks)


def reindex(class_id: int | None = None) -> dict[str, int]:
    """Embed every file that isn't embedded yet (after adding a key or changing the model)."""
    sql = "SELECT file_id FROM library_files WHERE embedded = 0"
    params: list[Any] = []
    if class_id is not None:
        sql += " AND class_id = ?"
        params.append(class_id)
    with connect() as conn:
        ids = [r[0] for r in conn.execute(sql, params).fetchall()]
    chunks = sum(index_file(i) for i in ids)
    return {"files": len(ids), "chunks": chunks}


# ---------------------------------------------------------------- search
_FILE_COLS = "f.file_id, f.title, f.original_name, f.doc_type, f.unit, f.status"


def _filters(doc_type: str | None, unit: str | None) -> tuple[str, list[Any]]:
    sql, params = " AND f.status NOT IN ('archived', 'draft')", []
    if doc_type:
        sql += " AND f.doc_type = ?"
        params.append(doc_type)
    if unit:
        sql += " AND f.unit = ?"
        params.append(unit)
    return sql, params


def _fts_query(q: str) -> str | None:
    terms = [t for t in re.findall(r"[A-Za-z0-9]+", q) if len(t) > 1]
    return " OR ".join(f'"{t}"' for t in terms) or None


@traceable(name="library.keyword_search", run_type="retriever")
def _keyword(q: str, class_id: int, n: int, doc_type: str | None, unit: str | None) -> list[dict[str, Any]]:
    match = _fts_query(q)
    if not match:
        return []
    extra, params = _filters(doc_type, unit)
    with connect() as conn:
        rows = conn.execute(
            f"""SELECT c.chunk_id, c.page, c.text, {_FILE_COLS}, bm25(library_chunks_fts) AS rank
                FROM library_chunks_fts JOIN library_chunks c ON c.chunk_id = library_chunks_fts.rowid
                JOIN library_files f ON f.file_id = c.file_id
                WHERE library_chunks_fts MATCH ? AND f.class_id = ? {extra}
                ORDER BY rank LIMIT ?""",
            (match, class_id, *params, n),
        ).fetchall()
    return [dict(r) for r in rows]


@traceable(name="library.semantic_search", run_type="retriever")
def _semantic(q: str, class_id: int, n: int, doc_type: str | None, unit: str | None) -> list[dict[str, Any]]:
    emb = get_embedder()
    if emb is None:
        return []
    qv = _vec_bytes(emb.embed_query(q))
    extra, params = _filters(doc_type, unit)
    with connect() as conn:
        rows = conn.execute(
            f"""WITH knn AS (
                    SELECT rowid, distance FROM library_chunk_vec
                    WHERE embedding MATCH ? AND k = ? AND class_id = ?)
                SELECT c.chunk_id, c.page, c.text, {_FILE_COLS}, knn.distance
                FROM knn JOIN library_chunks c ON c.chunk_id = knn.rowid
                JOIN library_files f ON f.file_id = c.file_id
                WHERE 1 = 1 {extra}
                ORDER BY knn.distance LIMIT ?""",
            (qv, n * 3, class_id, *params, n),  # over-fetch: some hits are archived/drafts
        ).fetchall()
    return [dict(r) for r in rows]


def _to_chunk(r: dict[str, Any], score: float, match: str) -> Chunk:
    return Chunk(chunk_id=r["chunk_id"], file_id=r["file_id"], file_title=r["title"] or r["original_name"],
                 doc_type=r["doc_type"], unit=r["unit"], page=r["page"], text=r["text"],
                 score=round(score, 4), match=match)


@traceable(name="library.search", run_type="retriever")
def search(query: str, class_id: int, k: int = 5, *, doc_type: str | None = None,
           unit: str | None = None, mode: SearchMode = "hybrid") -> list[Chunk]:
    """Top-k chunks for a query within one class."""
    pool = max(k * 4, 20)
    kw = _keyword(query, class_id, pool, doc_type, unit) if mode in ("hybrid", "keyword") else []
    sem = _semantic(query, class_id, pool, doc_type, unit) if mode in ("hybrid", "semantic") else []

    if mode == "keyword" or (mode == "hybrid" and not sem):
        return [_to_chunk(r, 1.0 / (RRF_K + i + 1), "keyword") for i, r in enumerate(kw[:k])]
    if mode == "semantic":
        return [_to_chunk(r, 1.0 - r["distance"], "semantic") for r in sem[:k]]

    fused: dict[int, dict[str, Any]] = {}
    for source, rows in (("keyword", kw), ("semantic", sem)):
        for rank, r in enumerate(rows, start=1):
            e = fused.setdefault(r["chunk_id"], {"row": r, "score": 0.0, "via": set()})
            e["score"] += 1.0 / (RRF_K + rank)
            e["via"].add(source)
    best = sorted(fused.values(), key=lambda e: e["score"], reverse=True)[:k]
    return [_to_chunk(e["row"], e["score"], "both" if len(e["via"]) == 2 else next(iter(e["via"]))) for e in best]
