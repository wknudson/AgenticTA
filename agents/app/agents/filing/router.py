from __future__ import annotations

import mimetypes
from typing import Any, Literal

from fastapi import File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.shared import library
from app.shared.agent_router import make_router
from app.shared.embeddings import get_embedder
from app.shared.settings import AGENTS_DIR, FILES_DIR

from . import ai_queue
from .pipeline import AI_CALLS, DOC_TYPES, ai_available, ingest, reprocess, reprocess_class

router = make_router("filing")
SAMPLE_COURSE = AGENTS_DIR / "sample_data" / "biology_course"


@router.post("/upload")
async def upload(class_id: int = Form(...), files: list[UploadFile] = File(...)):
    """Drop zone.  Any number of files of any type; each runs through the pipeline.
    (The UI sends one file per request so it can show progress.)"""
    results = []
    for f in files:
        data = await f.read()
        results.append(ingest(class_id, f.filename or "upload", data, f.content_type))
    return {"files": results}


@router.get("/files")
def files(class_id: int, doc_type: str | None = None, unit: str | None = None,
          status: str | None = None, include_archived: bool = False):
    return {"files": [f.to_dict() for f in library.list_files(class_id, doc_type=doc_type, unit=unit, status=status,
                                                               include_archived=include_archived)]}


@router.get("/units")
def units(class_id: int):
    return {"units": library.list_units(class_id), "doc_types": list(DOC_TYPES)}


@router.get("/files/{file_id}")
def file_detail(file_id: int):
    f = library.get_file(file_id)
    if f is None:
        raise HTTPException(404, "file not found")
    text = library.get_file_text(file_id)
    return {**f.to_dict(), "text_preview": text[:3000], "text_chars": len(text)}


class LabelEdit(BaseModel):
    title: str | None = None
    doc_type: Literal[DOC_TYPES] | None = None  # type: ignore[valid-type]
    unit: str | None = None
    summary: str | None = None
    dates: list[dict[str, Any]] | None = None


@router.patch("/files/{file_id}")
def edit_labels(file_id: int, body: LabelEdit):
    """Teacher fixes labels (also how a file leaves the Needs-review queue)."""
    f = library.update_labels(file_id, body.model_dump(exclude_unset=True))
    if f is None:
        raise HTTPException(404, "file not found")
    return f.to_dict()


@router.post("/files/{file_id}/archive")
def archive(file_id: int):
    """Teacher-only 'delete': hidden from the library and search, kept on disk."""
    return library.set_status(file_id, "archived")


@router.post("/files/{file_id}/restore")
def restore(file_id: int):
    return library.set_status(file_id, "filed")


@router.post("/files/{file_id}/reprocess")
def reprocess_one(file_id: int):
    """Re-check one file with AI from its saved original (teacher-set labels are kept)."""
    try:
        return reprocess(file_id)
    except LookupError as e:
        raise HTTPException(404, str(e))


@router.post("/reprocess")
def reprocess_many(class_id: int, which: Literal["needs_review", "not_teacher"] = "needs_review"):
    """Re-check the Needs-review queue (default) or every file not labeled by the teacher.
    Uses the batched AI queue: several files per request."""
    return reprocess_class(class_id, which)


@router.post("/ai-queue/run")
def run_ai_queue(class_id: int | None = None):
    """Run the batched AI queue now instead of waiting for the background worker."""
    return ai_queue.process_pending(class_id, force=True, until_empty=True)


@router.get("/ai-queue")
def ai_queue_status(class_id: int | None = None):
    rows = ai_queue._pending(class_id)
    return {"pending": len(rows), "ai_available": ai_available(), "ai_requests_since_start": AI_CALLS["requests"],
            "files": [{"file_id": r["file_id"], "original_name": r["original_name"], "reason": r["review_reason"]}
                      for r in rows]}


@router.get("/files/{file_id}/download")
def download(file_id: int):
    f, rel = library.get_file(file_id), library.stored_path(file_id)
    if f is None or rel is None or not (FILES_DIR / rel).is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(FILES_DIR / rel, filename=f.original_name,
                        media_type=f.mime_type or mimetypes.guess_type(f.original_name)[0])


@router.get("/search")
def search(class_id: int, q: str = Query(..., min_length=1), k: int = 8,
           mode: Literal["hybrid", "keyword", "semantic"] = "hybrid"):
    effective = mode if get_embedder() else "keyword"
    return {"mode": effective, "results": [c.to_dict() for c in library.search(q, class_id, k, mode=effective)]}


@router.post("/reindex")
def reindex(class_id: int | None = None):
    """Embed files that aren't in the vector index yet (e.g. after adding GOOGLE_API_KEY)."""
    if get_embedder() is None:
        raise HTTPException(503, "No embedding key: set GOOGLE_API_KEY in .env")
    return library.reindex(class_id)


@router.post("/demo")
def demo(class_id: int = Query(...)):
    """Files the generated sample course (agents/sample_data/biology_course) into this class.
    Duplicates are skipped, so running it twice is safe."""
    if not SAMPLE_COURSE.is_dir():
        raise HTTPException(409, "Sample course missing. Run: npm run sample-course")
    results = []
    for path in sorted(p for p in SAMPLE_COURSE.iterdir() if p.is_file()):
        r = ingest(class_id, path.name, path.read_bytes(), mimetypes.guess_type(path.name)[0])
        results.append({k: r.get(k) for k in ("file_id", "original_name", "doc_type", "unit", "status",
                                               "review_reason", "duplicate", "chunk_count", "embedded_chunks")})
    return {"filed": sum(not r["duplicate"] for r in results), "files": results}
