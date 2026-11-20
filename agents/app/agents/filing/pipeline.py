"""Filing pipeline (Phase 1).  Owner: Will.  NOT an agent: a fixed sequence of steps.

    dedupe -> save -> extract (text, or Gemini vision for images/scans) -> chunk -> label -> index

Why not an agent: every upload needs the same steps in the same order, with no decisions
that need planning.  A fixed pipeline is cheaper, faster, and easier to audit (Module 7
"workflow", Module 6 intelligent document analysis).  The LLM is used for exactly two jobs it
is better at than rules: reading images/scans, and labeling messy documents.

Each step is @traceable, so one upload is one LangSmith run (project agentic-ta-filing)
with a child per step, its timing and (for model calls) its token cost.

Guardrails on the labels (deterministic, after the model):
  - doc_type must be one of DOC_TYPES (enforced by the Pydantic schema)
  - dates must parse as real YYYY-MM-DD dates near the current school year, else dropped
  - units are snapped to the class's existing unit names, so "unit 3 - cells" doesn't
    become a second folder next to "Unit 3: Cells"
  - low confidence, "other" type, no readable text, or an unknown unit -> needs_review,
    with the reason shown to the teacher
Without GOOGLE_API_KEY, labels come from file-name/text heuristics and go to review.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langsmith import traceable
from pydantic import BaseModel, Field

from app.shared import library, quota
from app.shared.db import connect
from app.shared.llm import MissingApiKey, get_model, model_spec
from app.shared.settings import FILES_DIR
from app.shared.tracing import agent_trace

REVIEW_THRESHOLD = 0.6
CHUNK_CHARS, CHUNK_OVERLAP = 1000, 150
MIN_CHARS_PER_PAGE = 40          # less than this on average -> treat a PDF as scanned
MAX_LABEL_CHARS = 15_000         # text sent to the labeler (start of document)
MAX_VISION_BYTES = 18 * 1024 * 1024

TEXT_EXT = {".txt", ".md", ".csv"}
IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
             ".gif": "image/gif", ".heic": "image/heic"}
SUPPORTED = {".pdf", ".docx", ".pptx", *TEXT_EXT, *IMAGE_EXT}

DocType = Literal["syllabus", "lecture", "worksheet", "quiz", "test", "lab", "rubric", "reading", "schedule", "other"]
DOC_TYPES: tuple[str, ...] = DocType.__args__  # type: ignore[attr-defined]


# ---------------------------------------------------------------- label contract (Module 6)
class DateMention(BaseModel):
    date: str = Field(description="YYYY-MM-DD")
    label: str = Field(description="what happens that day, e.g. 'Unit 2 test' or 'Lab report due'")


class FileLabels(BaseModel):
    """What the labeler must return.  Field descriptions are part of the prompt."""
    title: str = Field(description="short human title, e.g. 'Photosynthesis lecture slides'")
    doc_type: DocType = Field(description="what kind of class document this is")
    unit: str | None = Field(default=None, description="the unit it belongs to, formatted like 'Unit 3: Cell Energy'; reuse an existing unit name when it matches; null if none")
    summary: str = Field(description="one or two sentences for a teacher skimming their files")
    dates: list[DateMention] = Field(default_factory=list, description="dated events (due dates, tests, labs); empty if none")
    confidence: float = Field(ge=0, le=1, description="how sure you are of doc_type and unit, 0 to 1")


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


MODEL_TIMEOUT_S = 60  # hard cap per call: a slow or overloaded model can't hang an upload


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


def _with_fallback(step: str, call: Any) -> tuple[Any, str]:
    """Run call(model) down the chain, quota-aware (see app/shared/quota.py):
    per-minute limit -> wait and retry the same model once; daily limit -> skip that model
    until its quota resets; overload/timeout/other -> next model.
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


@traceable(name="filing.vision_transcribe")
def vision_transcribe(data: bytes, mime_type: str) -> list[tuple[int | None, str]]:
    """Read an image or scanned PDF with the multimodal model.
    Raises MissingApiKey (no key) or AIUnavailable (quota/overload/too big) so the caller can say why."""
    if len(data) > MAX_VISION_BYTES:
        raise AIUnavailable(f"vision: file is over {MAX_VISION_BYTES // 2**20} MB")
    if not _labeler_chain():
        raise MissingApiKey("filing has no GOOGLE_API_KEY")
    block_type = "file" if mime_type == "application/pdf" else "image"
    msg = HumanMessage(content=[
        {"type": "text", "text": (
            "Transcribe all readable text in this class document exactly, keeping line breaks. "
            "Start each page with a line '=== Page N ==='. Write handwriting as best you can. "
            "For diagrams or pictures add one line '[Figure: short description]'. "
            "Output only the transcription.")},
        {"type": block_type, "base64": base64.b64encode(data).decode(), "mime_type": mime_type},
    ])
    # .text joins content blocks (Gemini returns a list, not a str)
    text, _ = _with_fallback("vision", lambda m: m.invoke([msg]).text)
    parts = re.split(r"^=== Page (\d+) ===\s*$", text, flags=re.MULTILINE)
    if len(parts) < 3:
        return [(None, text.strip())]
    return [(int(parts[i]), parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]


@traceable(name="filing.extract_text")
def extract_text(filename: str, data: bytes) -> tuple[list[tuple[int | None, str]], str, int | None, str | None]:
    """-> (pages [(page_number or None, text)], method 'text'|'vision'|'none', page_count, problem or None)"""
    ext = Path(filename).suffix.lower()

    def vision(mime: str, n: int | None):
        try:
            return vision_transcribe(data, mime), "vision", n, None
        except MissingApiKey:
            return [], "none", n, "images and scans need GOOGLE_API_KEY"
        except AIUnavailable as e:
            return [], "none", n, f"couldn't read it with AI ({e.reason})"

    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        pages = [(i + 1, (p.extract_text() or "").strip()) for i, p in enumerate(reader.pages)]
        n = len(pages)
        if n and sum(len(t) for _, t in pages) / n >= MIN_CHARS_PER_PAGE:
            return pages, "text", n, None
        return vision("application/pdf", n)
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
        return vision(IMAGE_EXT[ext], 1)
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


# ---------------------------------------------------------------- labeling
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _class_context(class_id: int) -> dict[str, Any]:
    with connect() as conn:
        r = conn.execute(
            """SELECT c.class_name, c.semester, s.subject_code, s.description AS subject
               FROM classes c JOIN subjects s ON s.subject_id = c.subject_id WHERE c.class_id = ?""",
            (class_id,),
        ).fetchone()
    return dict(r) if r else {}


def _clean_dates(dates: list[dict[str, Any]]) -> list[dict[str, str]]:
    today, out, seen = date.today(), [], set()
    for d in dates:
        try:
            parsed = date.fromisoformat(str(d.get("date", ""))[:10])
        except ValueError:
            continue
        if abs((parsed - today).days) > 550 or (parsed.isoformat(), d.get("label")) in seen:
            continue
        seen.add((parsed.isoformat(), d.get("label")))
        out.append({"date": parsed.isoformat(), "label": str(d.get("label") or "")[:120]})
    return sorted(out, key=lambda x: x["date"])


def _unit_number(u: str) -> str | None:
    m = re.search(r"\bunit\s*(\d+)", u, re.IGNORECASE)
    return m.group(1) if m else None


def _snap_unit(unit: str | None, existing: list[str]) -> str | None:
    if not unit:
        return None
    unit = re.sub(r"\s+", " ", unit).strip()
    for e in existing:
        if e.lower() == unit.lower():
            return e
    n = _unit_number(unit)
    if n:
        for e in existing:
            if _unit_number(e) == n:
                # Keep the existing name unless the new one is just more descriptive
                # ("Unit 2" -> "Unit 2: Cell Structure"); _upgrade_unit renames the folder then.
                return unit if (":" in unit and ":" not in e) else e
    return unit


def _upgrade_unit(class_id: int, new: str | None, existing: list[str]) -> None:
    """If a bare 'Unit 2' folder exists and a file names it 'Unit 2: Cell Structure',
    rename the folder for every file in the class so units don't split."""
    n = _unit_number(new) if new else None
    if not n or ":" not in new:
        return
    for e in existing:
        if e != new and _unit_number(e) == n and ":" not in e:
            with connect() as conn:
                conn.execute("UPDATE library_files SET unit = ? WHERE class_id = ? AND unit = ?", (new, class_id, e))


@traceable(name="filing.label_heuristic")
def label_heuristic(filename: str, text: str) -> FileLabels:
    """No-key fallback: file name and the first lines of text."""
    hay = f"{filename} {text[:400]}".lower()
    guesses = [("syllabus", "syllabus"), ("rubric", "rubric"), ("quiz", "quiz"), ("exam", "test"), ("test", "test"),
               ("lab", "lab"), ("worksheet", "worksheet"), ("practice", "worksheet"), ("slides", "lecture"),
               ("lecture", "lecture"), ("notes", "lecture"), ("reading", "reading"), ("article", "reading"),
               ("schedule", "schedule"), ("calendar", "schedule")]
    doc_type = next((t for k, t in guesses if re.search(rf"\b{k}", hay)), "other")
    # Only the number: guessing a unit *name* from text produced junk like "Unit 1: Notes".
    # _snap_unit then maps "Unit 1" onto the class's real "Unit 1: ..." folder if there is one.
    m = re.search(r"\bunit\s*(\d+)", f"{text[:400]} {filename}", re.IGNORECASE)
    unit = f"Unit {m.group(1)}" if m else None
    iso = [{"date": d, "label": "mentioned in document"} for d in re.findall(r"\b20\d\d-\d\d-\d\d\b", text)]
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), Path(filename).stem)
    return FileLabels(title=first_line[:80], doc_type=doc_type, unit=unit, summary=text[:200].replace("\n", " "),
                      dates=[DateMention(**d) for d in iso], confidence=0.5 if doc_type != "other" else 0.3)


OUTLINE_CHARS = 3000


def course_outline(class_id: int, exclude_file_id: int | None = None) -> str | None:
    """Start of the class's latest syllabus/schedule.  Lets the labeler place a file in a unit
    from its TOPIC ("toothpickase lab" -> enzymes -> Unit 1) when the file never names its unit."""
    with connect() as conn:
        r = conn.execute(
            """SELECT file_id FROM library_files
               WHERE class_id = ? AND doc_type IN ('syllabus', 'schedule') AND status IN ('filed', 'needs_review')
                     AND file_id != COALESCE(?, -1)
               ORDER BY doc_type = 'syllabus' DESC, file_id DESC LIMIT 1""",
            (class_id, exclude_file_id),
        ).fetchone()
    return library.get_file_text(r["file_id"])[:OUTLINE_CHARS] if r else None


@traceable(name="filing.label_llm")
def label_llm(model: Any, filename: str, text: str, ctx: dict[str, Any], existing_units: list[str],
              outline: str | None = None) -> FileLabels:
    prompt = (
        "You are filing a teacher's class documents.\n"
        f"Class: {ctx.get('class_name', '?')} ({ctx.get('subject', '?')}), term: {ctx.get('semester', '?')}. "
        f"Today is {date.today().isoformat()}; resolve dates without a year to this school year.\n"
        f"Existing units in this class (reuse one of these names exactly when it fits): {existing_units or 'none yet'}\n"
        + (f"Course outline from the syllabus (use it to pick the unit from the document's TOPIC, even when the "
           f"document doesn't name its unit; course-wide documents get no unit):\n<<<\n{outline}\n>>>\n" if outline else "")
        + f"File name: {filename}\n\n"
        f"Document text:\n<<<\n{text[:MAX_LABEL_CHARS]}\n>>>"
    )
    return model.with_structured_output(FileLabels).invoke(prompt)


@traceable(name="filing.label")
def label(class_id: int, filename: str, text: str, exclude_file_id: int | None = None) -> tuple[FileLabels, str, list[str]]:
    """-> (labels after guardrails, label_source, review reasons)"""
    reasons: list[str] = []
    existing = library.known_units(class_id)
    source = "llm"
    if not _labeler_chain():
        labels, source = label_heuristic(filename, text), "heuristic"
        reasons.append("labeled without AI (no GOOGLE_API_KEY)")
    else:
        ctx, outline = _class_context(class_id), course_outline(class_id, exclude_file_id)
        try:
            labels, role = _with_fallback("label", lambda m: label_llm(m, filename, text, ctx, existing, outline))
            if role == "labeler_fallback":
                source = "llm-fallback"
        except AIUnavailable as e:  # every model failed: never lose the upload
            labels, source = label_heuristic(filename, text), "heuristic"
            reasons.append(e.reason)
    labels.dates = [DateMention(**d) for d in _clean_dates([d.model_dump() for d in labels.dates])]
    labels.unit = _snap_unit(labels.unit, existing)
    _upgrade_unit(class_id, labels.unit, existing)
    if labels.confidence < REVIEW_THRESHOLD:
        reasons.append(f"low confidence ({labels.confidence:.2f})")
    if labels.doc_type == "other":
        reasons.append("couldn't tell what kind of document this is")
    if (existing and labels.unit and labels.unit not in existing and not _unit_number(labels.unit)
            and any(_unit_number(e) for e in existing)):
        reasons.append(f"'{labels.unit}' doesn't match this class's units")
    return labels, source, reasons


# ---------------------------------------------------------------- the pipeline
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
                                          extract_method, page_count, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (class_id, filename, stored_path, mime_type, sha, *a["label_values"], a["review_reason"],
             a["method"], a["page_count"], a["status"]),
        ).lastrowid
        _write_chunks(conn, file_id, a["chunks"])
    return _finish(file_id, len(a["chunks"]))


@traceable(name="filing.analyze")
def analyze(class_id: int, filename: str, data: bytes, exclude_file_id: int | None = None) -> dict[str, Any]:
    """extract -> chunk -> label, without writing anything.  Shared by ingest and reprocess."""
    ext = Path(filename).suffix.lower()
    reasons: list[str] = []
    if ext not in SUPPORTED:
        pages, method, page_count, problem = [], "none", None, f"can't read {ext or 'this'} files yet"
    else:
        pages, method, page_count, problem = extract_text(filename, data)
    if problem:
        reasons.append(problem)
    full_text = "\n".join(t for _, t in pages).strip()
    if not full_text and not problem:
        reasons.append("no readable text")
    labels, source, label_reasons = label(class_id, filename, full_text, exclude_file_id)
    reasons += [r for r in label_reasons if r not in reasons]
    return {
        "chunks": chunk(pages), "method": method, "page_count": page_count,
        "labels": labels, "label_source": source,
        "label_values": (labels.title, labels.doc_type, labels.unit, labels.summary,
                         json.dumps([d.model_dump() for d in labels.dates]), labels.confidence, source),
        "review_reason": "; ".join(reasons) or None,
        "status": "needs_review" if reasons else "filed",
    }


def _write_chunks(conn: Any, file_id: int, chunks: list[tuple[int | None, str]]) -> None:
    conn.executemany(
        "INSERT INTO library_chunks (file_id, chunk_idx, page, text) VALUES (?, ?, ?, ?)",
        [(file_id, i, page, text) for i, (page, text) in enumerate(chunks)],
    )


def _finish(file_id: int, chunk_count: int) -> dict:
    embedded = library.index_file(file_id)
    with connect() as conn:
        row = dict(conn.execute("SELECT * FROM library_files WHERE file_id = ?", (file_id,)).fetchone())
    return {**row, "duplicate": False, "chunk_count": chunk_count, "embedded_chunks": embedded}


# ---------------------------------------------------------------- re-check with AI
def reprocess(file_id: int) -> dict:
    """Run a filed document through the pipeline again from its saved original (e.g. after the
    AI quota resets, a key is added, or a syllabus arrives that explains the units).
    Labels the teacher set are kept; only the text/chunks are refreshed for those."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM library_files WHERE file_id = ?", (file_id,)).fetchone()
    if row is None:
        raise LookupError(f"file {file_id} not found")
    with agent_trace("filing", class_id=row["class_id"], filename=row["original_name"], reprocess=True):
        return _reprocess(dict(row))


@traceable(name="filing.reprocess")
def _reprocess(row: dict) -> dict:
    data = (FILES_DIR / row["stored_path"]).read_bytes()
    a = analyze(row["class_id"], row["original_name"], data, exclude_file_id=row["file_id"])
    teacher = row["label_source"] == "teacher"
    with connect() as conn:
        if teacher:  # keep the teacher's labels, refresh everything else
            conn.execute("UPDATE library_files SET extract_method = ?, page_count = ?, embedded = 0 WHERE file_id = ?",
                         (a["method"], a["page_count"], row["file_id"]))
        else:
            conn.execute(
                """UPDATE library_files SET title = ?, doc_type = ?, unit = ?, summary = ?, dates_json = ?,
                          label_confidence = ?, label_source = ?, review_reason = ?, extract_method = ?,
                          page_count = ?, status = ?, embedded = 0
                   WHERE file_id = ?""",
                (*a["label_values"], a["review_reason"], a["method"], a["page_count"], a["status"], row["file_id"]),
            )
        library.delete_chunks(row["file_id"], conn)
        _write_chunks(conn, row["file_id"], a["chunks"])
    return _finish(row["file_id"], len(a["chunks"]))


def reprocess_class(class_id: int, which: Literal["needs_review", "not_teacher"] = "needs_review") -> dict:
    """Re-check many files, one at a time (the AI quotas are per minute/day)."""
    sql = "SELECT file_id FROM library_files WHERE class_id = ? AND status != 'archived' AND status != 'draft'"
    sql += " AND status = 'needs_review'" if which == "needs_review" else " AND COALESCE(label_source, '') != 'teacher'"
    with connect() as conn:
        ids = [r[0] for r in conn.execute(sql, (class_id,)).fetchall()]
    results = [reprocess(i) for i in ids]
    return {"checked": len(results), "still_need_review": sum(r["status"] == "needs_review" for r in results),
            "files": [{k: r.get(k) for k in ("file_id", "original_name", "doc_type", "unit", "status", "review_reason",
                                              "label_source")} for r in results]}
