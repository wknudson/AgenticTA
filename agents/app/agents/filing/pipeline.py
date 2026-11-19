"""Filing pipeline (Phase 1).  Owner: Will.  NOT an agent: a fixed sequence of steps.

    save -> extract text (vision OCR for images) -> chunk -> embed -> label -> index

Each step is a plain function decorated with @traceable, so one upload shows up in
LangSmith (project agentic-ta-filing) as a run with one child per step and its timing.

Skeleton status (TODO(Will) marks what's left):
  [x] save original under data/files/<class_id>/
  [x] extract text from PDF / DOCX / PPTX / TXT
  [ ] images + scanned PDFs -> vision model (config: filing.labeler)
  [x] chunking (baseline: fixed-size with overlap)
  [ ] embeddings with fastembed -> library_chunk_vec, then switch library.search() to vectors
  [ ] LLM labels with a Pydantic contract (type, unit, title, summary, dates, confidence)
  [x] confidence threshold -> status 'needs_review'
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path

from langsmith import traceable
from pydantic import BaseModel, Field

from app.shared.db import connect
from app.shared.settings import FILES_DIR
from app.shared.tracing import agent_trace

REVIEW_THRESHOLD = 0.6
CHUNK_CHARS, CHUNK_OVERLAP = 1200, 200


class FileLabels(BaseModel):
    """The labeling contract (Module 6: Pydantic as the contract with the LLM)."""
    title: str
    doc_type: str = Field(description="syllabus | lecture | worksheet | quiz | rubric | reading | other")
    unit: str | None = Field(default=None, description="e.g. 'Unit 3: Cells'")
    summary: str = ""
    dates: list[dict] = Field(default_factory=list, description="[{date: YYYY-MM-DD, label}]")
    confidence: float = Field(ge=0, le=1)


@traceable(name="filing.save")
def save_original(class_id: int, filename: str, data: bytes) -> tuple[str, str]:
    sha = hashlib.sha256(data).hexdigest()
    rel = Path(str(class_id)) / f"{sha[:12]}_{Path(filename).name}"
    dest = FILES_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return rel.as_posix(), sha


@traceable(name="filing.extract_text")
def extract_text(filename: str, data: bytes) -> list[tuple[int | None, str]]:
    """-> [(page_number or None, text)]"""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return [(i + 1, p.extract_text() or "") for i, p in enumerate(reader.pages)]
    if ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        return [(None, "\n".join(p.text for p in d.paragraphs))]
    if ext == ".pptx":
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        return [(i + 1, "\n".join(sh.text_frame.text for sh in s.shapes if sh.has_text_frame))
                for i, s in enumerate(prs.slides)]
    if ext in (".txt", ".md", ".csv"):
        return [(None, data.decode("utf-8", errors="replace"))]
    # TODO(Will): images (.png/.jpg/.heic) and scanned PDFs -> vision model via get_model("filing", "labeler")
    return []


@traceable(name="filing.chunk")
def chunk(pages: list[tuple[int | None, str]]) -> list[tuple[int | None, str]]:
    out = []
    for page, text in pages:
        text = re.sub(r"\s+", " ", text).strip()
        for start in range(0, len(text), CHUNK_CHARS - CHUNK_OVERLAP):
            piece = text[start:start + CHUNK_CHARS]
            if piece:
                out.append((page, piece))
    return out


@traceable(name="filing.label")
def label(filename: str, text: str) -> FileLabels:
    """TODO(Will): replace with get_model("filing", "labeler").with_structured_output(FileLabels).
    Baseline below: guess the type from the file name and send everything to review."""
    name = filename.lower()
    guesses = {"syllabus": "syllabus", "quiz": "quiz", "test": "quiz", "exam": "quiz", "rubric": "rubric",
               "worksheet": "worksheet", "lecture": "lecture", "slides": "lecture", "notes": "lecture"}
    doc_type = next((v for k, v in guesses.items() if k in name), "other")
    dates = [{"date": d, "label": "found in text"} for d in sorted(set(re.findall(r"\b20\d\d-\d\d-\d\d\b", text)))]
    return FileLabels(title=Path(filename).stem, doc_type=doc_type, dates=dates,
                      summary=text[:200], confidence=0.3 if doc_type == "other" else 0.5)


@traceable(name="filing.embed")
def embed(chunk_ids: list[int], texts: list[str]) -> None:
    """TODO(Will): fastembed (config: filing.embeddings.model) -> INSERT INTO library_chunk_vec(rowid, embedding)."""
    return None


def ingest(class_id: int, filename: str, data: bytes, mime_type: str | None = None) -> dict:
    """Run the whole pipeline for one upload.  Returns the library_files row as a dict."""
    with agent_trace("filing", class_id=class_id, filename=filename):
        return _ingest(class_id, filename, data, mime_type)


@traceable(name="filing.ingest")
def _ingest(class_id: int, filename: str, data: bytes, mime_type: str | None) -> dict:
    stored_path, sha = save_original(class_id, filename, data)
    pages = extract_text(filename, data)
    chunks = chunk(pages)
    labels = label(filename, " ".join(t for _, t in pages))
    status = "filed" if labels.confidence >= REVIEW_THRESHOLD and chunks else "needs_review"
    with connect() as conn:
        file_id = conn.execute(
            """INSERT INTO library_files (class_id, original_name, stored_path, mime_type, sha256, title, doc_type,
                                          unit, summary, dates_json, label_confidence, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (class_id, filename, stored_path, mime_type, sha, labels.title, labels.doc_type, labels.unit,
             labels.summary, json.dumps(labels.dates), labels.confidence, status),
        ).lastrowid
        chunk_ids = [
            conn.execute("INSERT INTO library_chunks (file_id, chunk_idx, page, text) VALUES (?, ?, ?, ?)",
                         (file_id, i, page, text)).lastrowid
            for i, (page, text) in enumerate(chunks)
        ]
        row = dict(conn.execute("SELECT * FROM library_files WHERE file_id = ?", (file_id,)).fetchone())
    embed(chunk_ids, [t for _, t in chunks])
    row["chunk_count"] = len(chunk_ids)
    return row
