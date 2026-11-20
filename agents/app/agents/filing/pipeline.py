"""Filing pipeline (Phase 1).  Owner: Will.  NOT an agent: a fixed sequence of steps.

    dedupe -> save -> extract -> chunk -> embed -> FAST labels (rules + embeddings, no model)
           -> guardrails -> index -> (only if unsure) queue for a BATCHED AI double-check

Why not an agent: every upload needs the same steps in the same order, with no planning.
Why "embeddings first": the free Gemini tier allows ~20 labeling calls a day, and the course
requirements say to prefer embeddings when they solve the problem.  Rules + embeddings label
most files; the AI only sees what they can't settle:
  - photos and scans: ONE call reads AND labels them (it used to be two)
  - unsure text files: queued and labeled several at a time in ONE request (ai_queue.py)
  - "Re-check with AI": the teacher forces an AI label on one file

Each step is @traceable: one upload = one LangSmith run in project agentic-ta-filing.
Guardrails (labels.py) run on every label, whoever made it.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import threading
from datetime import date
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langsmith import traceable
from pydantic import BaseModel, Field

from app.shared import library, quota
from app.shared.db import connect, now_iso
from app.shared.llm import MissingApiKey, get_model, model_spec
from app.shared.settings import FILES_DIR
from app.shared.tracing import agent_trace

from . import classify
from .labels import (  # re-exported: tests and other modules import these from pipeline
    COURSE_WIDE, DOC_TYPES, REVIEW_THRESHOLD, DateMention, DocType, FileLabels, _clean_dates, _snap_unit,
    _unit_number, _upgrade_unit, apply_guardrails, course_outline,
)

__all__ = ["DOC_TYPES", "DocType", "FileLabels", "DateMention", "REVIEW_THRESHOLD", "COURSE_WIDE", "_clean_dates",
           "_snap_unit", "_unit_number", "_upgrade_unit", "course_outline"]

CHUNK_CHARS, CHUNK_OVERLAP = 1000, 150
MIN_CHARS_PER_PAGE = 40          # less than this on average -> treat a PDF as scanned
MAX_LABEL_CHARS = 15_000         # text sent to the AI for a single file
MAX_VISION_BYTES = 18 * 1024 * 1024
MODEL_TIMEOUT_S = 60             # hard cap per call: a slow or overloaded model can't hang an upload
WAITING_FOR_AI = "AI is double-checking this file"

TEXT_EXT = {".txt", ".md", ".csv", ".py", ".js", ".java", ".html"}  # plain text, incl. code a CS teacher hands out
IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
             ".gif": "image/gif", ".heic": "image/heic"}
SUPPORTED = {".pdf", ".docx", ".pptx", *TEXT_EXT, *IMAGE_EXT}

# How many labeling requests went to the AI in this process (the eval reports it).
_ai_lock = threading.Lock()
AI_CALLS = {"requests": 0}


def count_ai_call() -> None:
    with _ai_lock:
        AI_CALLS["requests"] += 1


# ---------------------------------------------------------------- AI plumbing (quota-aware)
class AIUnavailable(RuntimeError):
    """Every model in the chain failed; .reason is shown to the teacher."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _labeler_chain() -> list[tuple[str, str, Any]]:
    """[(role, model name, model)] to try in order: labeler, then labeler_fallback.  [] without a key.
    LangChain's own retries are off (max_retries=0) because quota.classify decides how to retry."""
    chain = []
    for role in ("labeler", "labeler_fallback"):
        try:
            name = model_spec("filing", role)["model"]
            chain.append((role, name, get_model("filing", role, timeout=MODEL_TIMEOUT_S, max_retries=0)))
        except (MissingApiKey, KeyError):
            pass
    return chain


def ai_available() -> bool:
    """A key exists and at least one model isn't out of its daily quota."""
    chain = _labeler_chain()
    return bool(chain) and any(not quota.blocked(name) for _, name, _ in chain)


def _with_fallback(step: str, call: Any) -> tuple[Any, str]:
    """Run call(model) down the chain, quota-aware (app/shared/quota.py): per-minute limit -> wait
    and retry once; daily limit -> skip that model until it resets; overload/other -> next model.
    -> (result, role used).  Raises AIUnavailable with a teacher-readable reason."""
    chain = _labeler_chain()
    if not chain:
        raise MissingApiKey("filing has no GOOGLE_API_KEY")
    reasons = []
    for role, name, model in chain:
        if quota.blocked(name):
            reasons.append(quota.friendly("daily", name))
            continue
        for attempt in range(2):
            try:
                count_ai_call()
                return call(model), role
            except Exception as e:
                kind, delay = quota.classify(e)
                if kind == "minute" and attempt == 0:
                    quota.wait(delay)
                    continue
                if kind == "daily":
                    quota.block(name, delay)
                reasons.append(quota.friendly(kind, name))
                break
    raise AIUnavailable(f"{step}: " + "; ".join(reasons))


def _ai_header(aictx: dict) -> str:
    ctx = aictx["ctx"]
    head = (
        "You are filing a teacher's class documents.\n"
        f"Class: {ctx.get('class_name', '?')} ({ctx.get('subject', '?')}), term: {ctx.get('semester', '?')}. "
        f"Today is {date.today().isoformat()}; resolve dates without a year to this school year.\n"
        f"Units (use one of these names EXACTLY, or null for course-wide documents): {aictx['units'] or 'none known yet'}\n"
    )
    if aictx["outline"]:
        head += ("Course outline from the syllabus (pick the unit from the document's TOPIC even when it "
                 f"doesn't name its unit):\n<<<\n{aictx['outline']}\n>>>\n")
    return head


@traceable(name="filing.label_llm")
def label_llm(model: Any, filename: str, text: str, aictx: dict) -> FileLabels:
    """One file -> labels (used by 'Re-check with AI')."""
    prompt = _ai_header(aictx) + f"File name: {filename}\n\nDocument text:\n<<<\n{text[:MAX_LABEL_CHARS]}\n>>>"
    return model.with_structured_output(FileLabels).invoke(prompt)


class VisionResult(BaseModel):
    transcription: str = Field(description="all readable text, exactly; start each page with a line '=== Page N ==='; "
                                           "one '[Figure: ...]' line per diagram or picture")
    labels: FileLabels


@traceable(name="filing.vision_read_and_label")
def vision_read_and_label(data: bytes, mime_type: str, filename: str,
                          aictx: dict) -> tuple[list[tuple[int | None, str]], FileLabels, str]:
    """ONE call reads an image/scanned PDF and labels it.  -> (pages, labels, role used).
    Raises MissingApiKey (no key) or AIUnavailable (quota/overload/too big)."""
    if len(data) > MAX_VISION_BYTES:
        raise AIUnavailable(f"vision: file is over {MAX_VISION_BYTES // 2**20} MB")
    if not _labeler_chain():
        raise MissingApiKey("filing has no GOOGLE_API_KEY")
    block_type = "file" if mime_type == "application/pdf" else "image"
    msg = HumanMessage(content=[
        {"type": "text", "text": _ai_header(aictx) + f"File name: {filename}\n\n"
            "First transcribe this document (handwriting as best you can), then label it."},
        {"type": block_type, "base64": base64.b64encode(data).decode(), "mime_type": mime_type},
    ])
    result, role = _with_fallback("vision", lambda m: m.with_structured_output(VisionResult).invoke([msg]))
    text = result.transcription
    parts = re.split(r"^=== Page (\d+) ===\s*$", text, flags=re.MULTILINE)
    pages = [(None, text.strip())] if len(parts) < 3 else \
        [(int(parts[i]), parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]
    return pages, result.labels, role


# ---------------------------------------------------------------- steps
@traceable(name="filing.find_duplicate")
def find_duplicate(class_id: int, sha: str) -> dict[str, Any] | None:
    with connect() as conn:
        r = conn.execute(
            "SELECT * FROM library_files WHERE class_id = ? AND sha256 = ? AND status != 'archived' ORDER BY file_id LIMIT 1",
            (class_id, sha),
        ).fetchone()
    return dict(r) if r else None


@traceable(name="filing.save")
def save_original(class_id: int, filename: str, data: bytes, sha: str) -> str:
    rel = Path(str(class_id)) / f"{sha[:12]}_{Path(filename).name}"
    dest = FILES_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return rel.as_posix()


@traceable(name="filing.extract_text")
def extract_text(filename: str, data: bytes) -> tuple[list[tuple[int | None, str]], str, int | None, str | None]:
    """-> (pages [(page_number or None, text)], method 'text'|'vision'|'none', page_count, mime if it needs vision)"""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        pages = [(i + 1, (p.extract_text() or "").strip()) for i, p in enumerate(reader.pages)]
        n = len(pages)
        if n and sum(len(t) for _, t in pages) / n >= MIN_CHARS_PER_PAGE:
            return pages, "text", n, None
        return [], "none", n, "application/pdf"
    if ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        lines = [p.text for p in d.paragraphs]
        for table in d.tables:
            for row in table.rows:
                lines.append(" | ".join(c.text.strip() for c in row.cells))
        return [(None, "\n".join(lines).strip())], "text", None, None
    if ext == ".pptx":
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        pages = []
        for i, s in enumerate(prs.slides, start=1):
            texts = [sh.text_frame.text for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
            if s.has_notes_slide and s.notes_slide.notes_text_frame.text.strip():
                texts.append("Speaker notes: " + s.notes_slide.notes_text_frame.text.strip())
            pages.append((i, "\n".join(texts)))
        return pages, "text", len(pages), None
    if ext in TEXT_EXT:
        return [(None, data.decode("utf-8", errors="replace").strip())], "text", None, None
    if ext in IMAGE_EXT:
        return [], "none", 1, IMAGE_EXT[ext]
    return [], "none", None, None


def split_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP,
               seps: tuple[str, ...] = ("\n\n", "\n", ". ", " ")) -> list[str]:
    """Recursive chunking (Module 4): split on paragraphs, then lines, sentences, words, and
    pack pieces up to `size` characters, carrying `overlap` characters into the next chunk."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    sep = next((s for s in seps if s in text), "")
    pieces = text.split(sep) if sep else [text[i:i + size] for i in range(0, len(text), size)]
    out, cur = [], ""
    for p in pieces:
        if len(p) > size:
            if cur:
                out.append(cur)
                cur = ""
            out.extend(split_text(p, size, overlap, seps[seps.index(sep) + 1:] if sep in seps else ()))
            continue
        candidate = f"{cur}{sep}{p}" if cur else p
        if len(candidate) <= size:
            cur = candidate
        else:
            out.append(cur)
            tail = cur[-overlap:] if overlap else ""
            cur = f"{tail}{sep}{p}" if tail and len(tail) + len(sep) + len(p) <= size else p
    if cur:
        out.append(cur)
    return [c.strip() for c in out if c.strip()]


@traceable(name="filing.chunk")
def chunk(pages: list[tuple[int | None, str]]) -> list[tuple[int | None, str]]:
    """Chunks never cross a page/slide boundary, so every hit can say which page it's on."""
    return [(page, piece) for page, text in pages for piece in split_text(text)]


# ---------------------------------------------------------------- analyze (no DB writes)
@traceable(name="filing.analyze")
def analyze(class_id: int, filename: str, data: bytes, exclude_file_id: int | None = None,
            force_ai: bool = False) -> dict[str, Any]:
    """extract -> chunk -> embed -> label (fast, or AI for scans / when forced).  Writes nothing."""
    ext = Path(filename).suffix.lower()
    reasons: list[str] = []
    labels: FileLabels | None = None
    source, pending = "auto", False
    aictx = classify.ai_context(class_id, exclude_file_id)

    if ext not in SUPPORTED:
        pages, method, page_count, vision_mime = [], "none", None, None
        reasons.append(f"can't read {ext or 'this'} files yet")
    else:
        pages, method, page_count, vision_mime = extract_text(filename, data)

    if vision_mime:  # photos & scans: one AI call reads AND labels
        try:
            pages, labels, role = vision_read_and_label(data, vision_mime, filename, aictx)
            method, source = "vision", ("llm-fallback" if role == "labeler_fallback" else "llm")
        except MissingApiKey:
            reasons.append("images and scans need GOOGLE_API_KEY")
        except AIUnavailable as e:
            reasons.append(f"waiting for AI to read it ({e.reason})")
            pending = True

    full_text = "\n".join(t for _, t in pages).strip()
    if not full_text and not reasons:
        reasons.append("no readable text")
    chunks = chunk(pages)
    vectors = library.embed_texts(filename, [t for _, t in chunks])

    if labels is None and force_ai and full_text:
        try:
            labels, role = _with_fallback("label", lambda m: label_llm(m, filename, full_text, aictx))
            source = "llm-fallback" if role == "labeler_fallback" else "llm"
        except (AIUnavailable, MissingApiKey) as e:
            reasons.append(getattr(e, "reason", "no GOOGLE_API_KEY"))
    if labels is None:
        fast = classify.fast_labels(class_id, filename, full_text, vectors, exclude_file_id)
        labels = fast.labels
        if fast.unsure and full_text:
            if _labeler_chain():
                pending = True  # the background queue will batch it with others
            else:
                reasons.append("not sure: " + ", ".join(fast.unsure) + " (no AI key to double-check)")

    reasons += [r for r in apply_guardrails(class_id, labels, exclude_file_id=exclude_file_id)
                if r not in reasons and not (pending and r.startswith("low confidence"))]
    if pending:
        reasons.insert(0, WAITING_FOR_AI)
    return {
        "chunks": chunks, "vectors": vectors, "method": method, "page_count": page_count,
        "labels": labels, "label_source": source, "pending": pending,
        "label_values": (labels.title, labels.doc_type, labels.unit, labels.summary,
                         json.dumps([d.model_dump() for d in labels.dates]), labels.confidence, source),
        "review_reason": "; ".join(reasons) or None,
        "status": "needs_review" if reasons else "filed",
    }


# ---------------------------------------------------------------- ingest
def ingest(class_id: int, filename: str, data: bytes, mime_type: str | None = None) -> dict:
    """Run the whole pipeline for one upload.  Returns the library_files row as a dict
    (+ chunk_count, embedded_chunks, duplicate)."""
    with agent_trace("filing", class_id=class_id, filename=filename):
        return _ingest(class_id, filename, data, mime_type)


@traceable(name="filing.ingest")
def _ingest(class_id: int, filename: str, data: bytes, mime_type: str | None) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    dup = find_duplicate(class_id, sha)
    if dup:
        return {**dup, "duplicate": True, "chunk_count": 0, "embedded_chunks": 0}

    stored_path = save_original(class_id, filename, data, sha)
    a = analyze(class_id, filename, data)
    with connect() as conn:
        file_id = conn.execute(
            """INSERT INTO library_files (class_id, original_name, stored_path, mime_type, sha256, title, doc_type,
                                          unit, summary, dates_json, label_confidence, label_source, review_reason,
                                          extract_method, page_count, status, ai_pending, ai_queued_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (class_id, filename, stored_path, mime_type, sha, *a["label_values"], a["review_reason"],
             a["method"], a["page_count"], a["status"], int(a["pending"]), now_iso() if a["pending"] else None),
        ).lastrowid
        _write_chunks(conn, file_id, a["chunks"])
    return _finish(file_id, a)


def _write_chunks(conn: Any, file_id: int, chunks: list[tuple[int | None, str]]) -> None:
    conn.executemany(
        "INSERT INTO library_chunks (file_id, chunk_idx, page, text) VALUES (?, ?, ?, ?)",
        [(file_id, i, page, text) for i, (page, text) in enumerate(chunks)],
    )


def _finish(file_id: int, a: dict) -> dict:
    embedded = library.store_vectors(file_id, a["vectors"]) if a["vectors"] else library.index_file(file_id)
    if a["labels"].doc_type in COURSE_WIDE:  # a syllabus defines the units: re-sort earlier files (free)
        with connect() as conn:
            class_id = conn.execute("SELECT class_id FROM library_files WHERE file_id = ?", (file_id,)).fetchone()[0]
        classify.resort_units(class_id)
    with connect() as conn:
        row = dict(conn.execute("SELECT * FROM library_files WHERE file_id = ?", (file_id,)).fetchone())
    return {**row, "duplicate": False, "chunk_count": len(a["chunks"]), "embedded_chunks": embedded}


# ---------------------------------------------------------------- re-check with AI
def reprocess(file_id: int, force_ai: bool = True) -> dict:
    """Run a filed document through the pipeline again from its saved original.  By default the
    AI labels it right away ('Re-check with AI').  Teacher-set labels are kept."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM library_files WHERE file_id = ?", (file_id,)).fetchone()
    if row is None:
        raise LookupError(f"file {file_id} not found")
    with agent_trace("filing", class_id=row["class_id"], filename=row["original_name"], reprocess=True):
        return _reprocess(dict(row), force_ai)


@traceable(name="filing.reprocess")
def _reprocess(row: dict, force_ai: bool) -> dict:
    data = (FILES_DIR / row["stored_path"]).read_bytes()
    a = analyze(row["class_id"], row["original_name"], data, exclude_file_id=row["file_id"], force_ai=force_ai)
    teacher = row["label_source"] == "teacher"
    with connect() as conn:
        if teacher:  # keep the teacher's labels, refresh everything else
            conn.execute("UPDATE library_files SET extract_method = ?, page_count = ?, embedded = 0, ai_pending = 0 "
                         "WHERE file_id = ?", (a["method"], a["page_count"], row["file_id"]))
        else:
            conn.execute(
                """UPDATE library_files SET title = ?, doc_type = ?, unit = ?, summary = ?, dates_json = ?,
                          label_confidence = ?, label_source = ?, review_reason = ?, extract_method = ?,
                          page_count = ?, status = ?, embedded = 0, ai_pending = ?, ai_queued_at = ?
                   WHERE file_id = ?""",
                (*a["label_values"], a["review_reason"], a["method"], a["page_count"], a["status"],
                 int(a["pending"]), now_iso() if a["pending"] else None, row["file_id"]),
            )
        library.delete_chunks(row["file_id"], conn)
        _write_chunks(conn, row["file_id"], a["chunks"])
    return _finish(row["file_id"], a)


def reprocess_class(class_id: int, which: Literal["needs_review", "not_teacher"] = "needs_review") -> dict:
    """'Re-check all with AI': queue the files and run the batched AI queue now (several files
    per request), instead of one request per file."""
    from . import ai_queue  # noqa: PLC0415 (ai_queue imports this module)

    sql = "SELECT file_id FROM library_files WHERE class_id = ? AND status NOT IN ('archived', 'draft')"
    sql += " AND status = 'needs_review'" if which == "needs_review" else " AND COALESCE(label_source, '') != 'teacher'"
    with connect() as conn:
        ids = [r[0] for r in conn.execute(sql, (class_id,)).fetchall()]
    ai_queue.enqueue(ids)
    before = AI_CALLS["requests"]
    ai_queue.process_pending(class_id, force=True, until_empty=True)
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM library_files WHERE file_id IN ({','.join('?' * len(ids)) or 'NULL'})", ids).fetchall()]
    return {"checked": len(rows), "still_need_review": sum(r["status"] == "needs_review" for r in rows),
            "ai_requests": AI_CALLS["requests"] - before,
            "files": [{k: r.get(k) for k in ("file_id", "original_name", "doc_type", "unit", "status", "review_reason",
                                              "label_source")} for r in rows]}
