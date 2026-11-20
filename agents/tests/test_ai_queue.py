"""Embeddings-first labeling: the batched AI queue, one-call vision, catalog + date parsing.
A fake model stands in for Gemini, so these spend no quota."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.filing import ai_queue, classify, pipeline
from app.agents.filing.labels import FileLabels, unit_catalog
from app.shared import library, quota
from app.shared.db import connect

MATERIALS = Path(__file__).resolve().parents[2] / "test_materials"
ALG = 1  # Algebra II in the seed data
DAILY = "429 RESOURCE_EXHAUSTED quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier retry in 3h"


class FakeLLM:
    """Answers with_structured_output(...).invoke(...) like Gemini would, and counts requests."""

    def __init__(self, fail: str | None = None):
        self.requests, self.fail = 0, fail

    def with_structured_output(self, schema):
        outer = self

        class Runner:
            def invoke(self, inp):
                outer.requests += 1
                if outer.fail:
                    raise RuntimeError(outer.fail)
                if schema is ai_queue.BatchLabels:
                    n = str(inp).count("=== Document ")
                    return ai_queue.BatchLabels(items=[
                        ai_queue.BatchItem(doc=i + 1, title=f"AI title {i + 1}", doc_type="lecture",
                                           unit="Unit 3: Quadratic Functions", summary="s", confidence=0.9)
                        for i in range(n)])
                if schema is pipeline.VisionResult:
                    return pipeline.VisionResult(
                        transcription="=== Page 1 ===\nVERTEX FORM y = a(x - h)^2 + k",
                        labels=FileLabels(title="Vertex form whiteboard", doc_type="lecture",
                                          unit="Unit 3: Quadratic Functions", summary="s", confidence=0.95))
                return FileLabels(title="AI", doc_type="worksheet", unit=None, summary="s", confidence=0.9)
        return Runner()


@pytest.fixture
def fake_ai(monkeypatch):
    quota._blocked_until.clear()
    llm = FakeLLM()
    monkeypatch.setattr(pipeline, "_labeler_chain", lambda: [("labeler", "fake-flash", llm)])
    yield llm
    quota._blocked_until.clear()


@pytest.fixture(scope="module")
def algebra(client):
    """Algebra II syllabus + a few files, filed with no AI key (fast labels only)."""
    names = ["Algebra2_Syllabus_Fall2026.docx", "slope_intercept_notes.txt", "Factoring_Practice_Worksheet.docx",
             "Exponential_Growth_Notes.md", "Unit2_Test_Systems.pdf", "Quadratics_Slides.pptx",
             "Systems_Substitution_Elimination_Notes.docx", "Graphing_Lines_Worksheet.docx"]
    out = {}
    for n in names:
        out[n] = pipeline.ingest(ALG, n, (MATERIALS / "algebra2" / n).read_bytes())
    return out


def test_unit_catalog_comes_from_the_syllabus(algebra):
    assert list(unit_catalog(ALG)) == ["Unit 1: Linear Functions", "Unit 2: Systems of Equations",
                                       "Unit 3: Quadratic Functions", "Unit 4: Exponential Functions"]


def test_no_ai_calls_without_a_key(algebra):
    before = pipeline.AI_CALLS["requests"]
    pipeline.ingest(ALG, "x.txt", b"Unit 4: exponential growth notes 2026-12-01 quiz review")
    assert pipeline.AI_CALLS["requests"] == before


def test_unsure_files_are_queued_when_ai_is_available(fake_ai, algebra):
    r = pipeline.ingest(ALG, "mystery.txt", b"Some words about the class that match nothing in particular.")
    assert r["ai_pending"] == 1 and r["review_reason"].startswith(pipeline.WAITING_FOR_AI)
    assert fake_ai.requests == 0, "nothing is sent until the queue runs"


def test_queue_labels_many_files_in_one_request(fake_ai, algebra):
    ids = [r["file_id"] for r in algebra.values()][1:6]  # 5 files
    ai_queue.enqueue(ids)
    out = ai_queue.process_pending(ALG, force=True, until_empty=True)
    assert fake_ai.requests == 1, "5 queued + the mystery file = 6 files -> ONE request"
    assert out["labeled"] == 6
    for fid in ids:
        f = library.get_file(fid)
        assert not f.ai_pending and f.label_source == "llm" and f.unit == "Unit 3: Quadratic Functions"


def test_batch_size_bounds_requests(fake_ai, algebra):
    ids = [r["file_id"] for r in algebra.values()]  # 8 files -> 2 requests of <= 6
    ai_queue.enqueue(ids)
    ai_queue.process_pending(ALG, force=True, until_empty=True)
    assert fake_ai.requests == 2


def test_debounce_waits_for_more_files(fake_ai, algebra):
    ai_queue.enqueue([algebra["Quadratics_Slides.pptx"]["file_id"]])
    assert ai_queue.process_pending(ALG)["labeled"] == 0 and fake_ai.requests == 0
    assert ai_queue.process_pending(ALG, force=True)["labeled"] == 1


def test_daily_quota_leaves_files_waiting_with_a_reason(monkeypatch, algebra):
    quota._blocked_until.clear()
    llm = FakeLLM(fail=DAILY)
    monkeypatch.setattr(pipeline, "_labeler_chain", lambda: [("labeler", "fake-flash", llm)])
    fid = algebra["Exponential_Growth_Notes.md"]["file_id"]
    ai_queue.enqueue([fid])
    ai_queue.process_pending(ALG, force=True, until_empty=True)
    f = library.get_file(fid)
    assert f.ai_pending and "waiting for AI" in f.review_reason and "daily" in f.review_reason
    assert llm.requests == 1 and not pipeline.ai_available(), "the model is skipped until its quota resets"
    quota._blocked_until.clear()
    with connect() as conn:
        conn.execute("UPDATE library_files SET ai_pending = 0 WHERE file_id = ?", (fid,))


def test_photo_is_read_and_labeled_in_one_call(fake_ai, algebra):
    data = (MATERIALS / "algebra2" / "whiteboard_vertex_form.jpg").read_bytes()
    r = pipeline.ingest(ALG, "whiteboard_vertex_form.jpg", data)
    assert fake_ai.requests == 1, "one request reads AND labels"
    assert (r["extract_method"], r["label_source"], r["unit"]) == ("vision", "llm", "Unit 3: Quadratic Functions")
    assert "VERTEX FORM" in library.get_file_text(r["file_id"])


def test_teacher_labels_are_never_overwritten_by_the_queue(fake_ai, client, algebra):
    fid = algebra["Graphing_Lines_Worksheet.docx"]["file_id"]
    client.patch(f"/agents/filing/files/{fid}", json={"unit": "Unit 1: Linear Functions"})
    ai_queue.enqueue([fid])
    ai_queue.process_pending(ALG, force=True, until_empty=True)
    f = library.get_file(fid)
    assert f.label_source == "teacher" and f.unit == "Unit 1: Linear Functions"


def test_paperwork_is_course_wide_even_with_lab_in_the_name(algebra):
    r = classify.fast_labels(ALG, "Lab_Safety_Contract.pdf", "LAB SAFETY CONTRACT\nWear goggles. Sign and return.", None)
    assert (r.labels.doc_type, r.labels.unit, r.unsure) == ("other", None, [])


@pytest.mark.parametrize("line,want", [
    ("2026-09-16 | Unit 1 quiz", [("2026-09-16", "Unit 1 quiz")]),
    ("Field trip permission slips due Friday 2026-12-04", [("2026-12-04", "Field trip permission slips due Friday")]),
    ("Unit 1: Linear Functions (Aug 24 to Sep 18). Slope", []),  # a span, not an event
    ("Project due December 9, 2026", [("2026-12-09", "Project due")]),
    ("2026-11-25 to 2026-11-27  Thanksgiving break", [("2026-11-25", "Thanksgiving break"), ("2026-11-27", "Thanksgiving break")]),
])
def test_extract_dates(line, want):
    assert [(d["date"], d["label"]) for d in classify.extract_dates(line)] == want
