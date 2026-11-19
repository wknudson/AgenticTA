from __future__ import annotations

from fastapi import File, Form, Query, UploadFile

from app.shared import library
from app.shared.agent_router import make_router

from .pipeline import ingest

router = make_router("filing")


@router.post("/upload")
async def upload(class_id: int = Form(...), files: list[UploadFile] = File(...)):
    """Drop zone: any number of files, any type.  Each one runs through the pipeline."""
    results = []
    for f in files:
        data = await f.read()
        results.append(ingest(class_id, f.filename or "upload", data, f.content_type))
    return {"files": results}


@router.get("/files")
def files(class_id: int, doc_type: str | None = None, unit: str | None = None, include_archived: bool = False):
    return {"files": [f.to_dict() for f in library.list_files(class_id, doc_type=doc_type, unit=unit,
                                                               include_archived=include_archived)]}


@router.get("/search")
def search(class_id: int, q: str = Query(..., min_length=1), k: int = 5):
    return {"results": [c.to_dict() for c in library.search(q, class_id, k)]}


@router.post("/demo")
def demo(class_id: int = Query(...)):
    """Offline: files a small generated syllabus so the library isn't empty."""
    text = (
        "Biology Unit 3: Cells. Syllabus.\n"
        "2026-12-03 Unit 3 quiz on cell structure and organelles.\n"
        "2026-12-05 Lab report due: microscopy of onion cells.\n"
        "Key ideas: the mitochondria makes ATP; the nucleus stores DNA; ribosomes build proteins."
    )
    return {"files": [ingest(class_id, "unit3_syllabus.txt", text.encode(), "text/plain")]}
