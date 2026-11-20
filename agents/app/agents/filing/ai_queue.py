"""Batched AI double-check queue.

Files that rules + embeddings weren't sure about are marked ai_pending.  A background worker
waits a few seconds so a drag-and-drop of many files arrives together, then sends up to
BATCH_SIZE of them to the AI in ONE request (the free tier limits requests per day, not size).
Photos/scans that couldn't be read earlier (quota) are retried one per request, since each
needs its own image.

If the AI is out of quota, files stay pending with the reason shown to the teacher, and the
worker tries again once the quota resets.  Teachers can always label a file themselves.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langsmith import traceable
from pydantic import BaseModel, Field

from app.shared.db import connect, now_iso
from app.shared.tracing import agent_trace

from . import classify, pipeline
from .labels import DateMention, FileLabels, apply_guardrails

log = logging.getLogger("filing.ai_queue")

BATCH_SIZE = 6        # files per AI request
DOC_CHARS = 2500      # text per file inside a batch (the start of a doc is what identifies it)
DEBOUNCE_S = 4.0      # wait this long after the newest file was queued, to batch an upload
POLL_S = 3.0


class BatchItem(FileLabels):
    doc: int = Field(description="the number in the document's '=== Document N ===' header")


class BatchLabels(BaseModel):
    items: list[BatchItem]


def enqueue(file_ids: list[int]) -> None:
    if not file_ids:
        return
    with connect() as conn:
        conn.executemany(
            """UPDATE library_files SET ai_pending = 1, ai_queued_at = ?, status = 'needs_review',
                      review_reason = ? WHERE file_id = ? AND COALESCE(label_source, '') != 'teacher'""",
            [(now_iso(), pipeline.WAITING_FOR_AI, fid) for fid in file_ids],
        )


@traceable(name="filing.label_batch")
def label_batch(model: Any, docs: list[dict], aictx: dict) -> list[BatchItem]:
    """docs: [{doc, filename, text, guess}] -> one structured response labeling all of them."""
    parts = [pipeline._ai_header(aictx),
             f"Label each of the {len(docs)} documents below. Return exactly one item per document, "
             "with its document number.\n"]
    for d in docs:
        parts.append(f"\n=== Document {d['doc']} ===\nFile name: {d['filename']}\n"
                     f"(rules guessed: type {d['guess']['doc_type']}, unit {d['guess']['unit']})\n"
                     f"<<<\n{d['text'][:DOC_CHARS]}\n>>>")
    return model.with_structured_output(BatchLabels).invoke("".join(parts)).items


def _pending(class_id: int | None) -> list[dict]:
    sql = "SELECT * FROM library_files WHERE ai_pending = 1 AND status NOT IN ('archived', 'draft')"
    params: list[Any] = []
    if class_id is not None:
        sql += " AND class_id = ?"
        params.append(class_id)
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql + " ORDER BY class_id, ai_queued_at, file_id", params).fetchall()]


def _age_s(ts: str | None) -> float:
    if not ts:
        return 1e9
    return (datetime.now(timezone.utc) - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds()


def _set_waiting(file_ids: list[int], reason: str) -> None:
    with connect() as conn:
        conn.executemany("UPDATE library_files SET review_reason = ? WHERE file_id = ?",
                         [(f"waiting for AI: {reason}; you can also label it yourself", fid) for fid in file_ids])


def _save(row: dict, labels: FileLabels, role: str) -> None:
    reasons = apply_guardrails(row["class_id"], labels, exclude_file_id=row["file_id"])
    source = "llm-fallback" if role == "labeler_fallback" else "llm"
    with connect() as conn:
        conn.execute(
            """UPDATE library_files SET title = ?, doc_type = ?, unit = ?, summary = ?, dates_json = ?,
                      label_confidence = ?, label_source = ?, review_reason = ?, status = ?,
                      ai_pending = 0, ai_queued_at = NULL
               WHERE file_id = ? AND COALESCE(label_source, '') != 'teacher'""",
            (labels.title, labels.doc_type, labels.unit, labels.summary,
             json.dumps([d.model_dump() for d in labels.dates]), labels.confidence, source,
             "; ".join(reasons) or None, "needs_review" if reasons else "filed", row["file_id"]),
        )


@traceable(name="filing.process_batch")
def _process_class(class_id: int, rows: list[dict]) -> int:
    """Label one batch for one class.  Returns AI requests made.  Raises AIUnavailable."""
    from app.shared import library  # noqa: PLC0415

    vision = [r for r in rows if r["extract_method"] == "none" and Path(r["original_name"]).suffix.lower()
              in {*pipeline.IMAGE_EXT, ".pdf"}]
    text_rows = [r for r in rows if r not in vision]
    requests = 0
    for r in vision:  # each image needs its own request
        out = pipeline.reprocess(r["file_id"], force_ai=False)
        requests += 1
        if out.get("ai_pending"):  # still couldn't read it (quota/overload): stop this round
            raise pipeline.AIUnavailable(out.get("review_reason") or "couldn't read the image")
    if not text_rows:
        return requests
    aictx = classify.ai_context(class_id)
    docs = [{"doc": i + 1, "filename": r["original_name"], "text": library.get_file_text(r["file_id"]),
             "guess": {"doc_type": r["doc_type"], "unit": r["unit"]}, "row": r} for i, r in enumerate(text_rows)]
    items, role = pipeline._with_fallback("label batch", lambda m: label_batch(m, docs, aictx))
    requests += 1
    by_doc = {it.doc: it for it in items}
    for d in docs:
        it = by_doc.get(d["doc"])
        if it is None:  # the model skipped one: leave it for the next round
            continue
        labels = FileLabels(**it.model_dump(exclude={"doc"}))
        labels.dates = [DateMention(**x.model_dump()) for x in it.dates]
        _save(d["row"], labels, role)
    return requests


def process_pending(class_id: int | None = None, *, force: bool = False, until_empty: bool = False) -> dict:
    """Run one round (or until nothing is left) of the queue.  force=True skips the debounce."""
    done = requests = 0
    if not pipeline.ai_available():
        return {"labeled": 0, "requests": 0, "skipped": "AI not available (no key or quota used up)"}
    while True:
        rows = _pending(class_id)
        if not rows:
            break
        cls = rows[0]["class_id"]
        batch = [r for r in rows if r["class_id"] == cls][:BATCH_SIZE]
        youngest = min(_age_s(r["ai_queued_at"]) for r in batch)
        if not force and len(batch) < BATCH_SIZE and youngest < DEBOUNCE_S:
            break  # more files may still be arriving: wait for the next poll
        ids = [r["file_id"] for r in batch]
        try:
            with agent_trace("filing", class_id=cls, step="ai_queue"):
                requests += _process_class(cls, batch)
        except pipeline.AIUnavailable as e:
            _set_waiting(ids, e.reason)
            break
        still = {r["file_id"] for r in _pending(cls)} & set(ids)
        done += len(ids) - len(still)
        if still == set(ids) or not until_empty:
            break  # no progress this round (e.g. the model skipped them): try again on the next poll
    return {"labeled": done, "requests": requests}


# ---------------------------------------------------------------- background worker
_stop = threading.Event()
_thread: threading.Thread | None = None


def _loop() -> None:
    while not _stop.wait(POLL_S):
        try:
            process_pending(until_empty=True)
        except Exception:  # never let the worker die
            log.exception("AI queue round failed")


def start() -> None:
    global _thread
    if os.getenv("AGENTICTA_AI_QUEUE_WORKER") == "0" or (_thread and _thread.is_alive()):
        return  # tests turn the worker off and call process_pending() themselves
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="filing-ai-queue", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
