"""How the filing pipeline behaves when the AI is rate-limited, overloaded or missing."""
from __future__ import annotations

import pytest

from app.agents.filing import pipeline
from app.shared import library, quota

DAILY = ("429 RESOURCE_EXHAUSTED. {'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', "
         "'message': 'Generate content requests per day limit exceeded on Free Tier. Please retry in 8h18m11.05s.'}")
MINUTE = ("429 RESOURCE_EXHAUSTED. {'quotaId': 'EmbedContentRequestsPerMinutePerUserPerProjectPerModel-FreeTier', "
          "'retryDelay': '43s'}")
OVERLOAD = "503 UNAVAILABLE. This model is currently experiencing high demand."


@pytest.mark.parametrize("msg,kind,secs", [
    (DAILY, "daily", 8 * 3600 + 18 * 60 + 11.05),
    (MINUTE, "minute", 43.0),
    (OVERLOAD, "overload", None),
    ("ValidationError: field required", "other", None),
])
def test_quota_classify(msg, kind, secs):
    k, s = quota.classify(RuntimeError(msg))
    assert k == kind and (s == pytest.approx(secs) if secs else True)


class FakeModel:
    def __init__(self, errors):
        self.errors, self.calls = list(errors), 0

    def go(self):
        self.calls += 1
        if self.errors:
            raise RuntimeError(self.errors.pop(0))
        return "ok"


def _chain(monkeypatch, primary, backup):
    monkeypatch.setattr(pipeline, "_labeler_chain", lambda: [("labeler", "m-primary", primary),
                                                              ("labeler_fallback", "m-backup", backup)])
    monkeypatch.setattr(quota, "wait", lambda s: None)  # don't actually sleep in tests


def test_daily_limit_falls_back_and_stops_calling_that_model(monkeypatch):
    quota._blocked_until.clear()
    primary, backup = FakeModel([DAILY]), FakeModel([])
    _chain(monkeypatch, primary, backup)
    assert pipeline._with_fallback("label", lambda m: m.go()) == ("ok", "labeler_fallback")
    assert pipeline._with_fallback("label", lambda m: m.go()) == ("ok", "labeler_fallback")
    assert primary.calls == 1, "a model out of daily quota is not called again"
    quota._blocked_until.clear()


def test_minute_limit_waits_and_retries_same_model(monkeypatch):
    primary, backup = FakeModel([MINUTE]), FakeModel([])
    _chain(monkeypatch, primary, backup)
    assert pipeline._with_fallback("label", lambda m: m.go()) == ("ok", "labeler")
    assert primary.calls == 2 and backup.calls == 0


def test_everything_down_gives_a_teacher_readable_reason(monkeypatch):
    quota._blocked_until.clear()
    _chain(monkeypatch, FakeModel([DAILY]), FakeModel([OVERLOAD]))
    with pytest.raises(pipeline.AIUnavailable) as e:
        pipeline._with_fallback("label", lambda m: m.go())
    assert "daily free-tier limit" in e.value.reason and "overloaded" in e.value.reason
    quota._blocked_until.clear()


def test_course_outline_comes_from_the_syllabus(client):
    client.post("/agents/filing/demo", params={"class_id": 3})
    outline = pipeline.course_outline(3)
    assert outline and "Unit 1: Chemistry of Life" in outline


def test_reprocess_keeps_teacher_labels_and_rebuilds_chunks(client):
    client.post("/agents/filing/demo", params={"class_id": 3})
    f = next(x for x in library.list_files(3) if x.original_name == "Punnett_Square_Practice.docx")
    client.patch(f"/agents/filing/files/{f.file_id}", json={"unit": "Unit 4: Cell Division and Genetics"})
    before = len(library.get_file_text(f.file_id))
    out = client.post(f"/agents/filing/files/{f.file_id}/reprocess").json()
    assert out["unit"] == "Unit 4: Cell Division and Genetics" and out["label_source"] == "teacher"
    assert len(library.get_file_text(f.file_id)) == before, "chunks rebuilt, not duplicated"
    assert library.search("Punnett", 3, mode="keyword")


def test_reprocess_queue_endpoint(client):
    client.post("/agents/filing/demo", params={"class_id": 3})
    r = client.post("/agents/filing/reprocess", params={"class_id": 3}).json()
    assert r["checked"] >= 1 and "still_need_review" in r
