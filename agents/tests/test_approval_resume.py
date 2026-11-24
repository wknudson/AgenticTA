"""Approving after a restart: a no-AI draft must still publish, and a failed action must not
leave the approval marked as decided. (Found in hand testing: the scheduler's no-AI draft
couldn't be approved after the agents service restarted, because resuming built the real
model and its key was missing; the approval stayed "approved" with nothing published.)"""
from __future__ import annotations

import pytest

from app.agents.scheduler.agent import runner as scheduler_runner
from app.shared import approvals
from app.shared.db import connect

CLASS = 5
TERM = {"term_start": "2026-08-24", "term_end": "2026-12-18", "holidays": [], "max_per_day": 2}


@pytest.fixture
def history_calendar(client):
    with connect() as conn:
        conn.execute("INSERT INTO library_files (class_id, original_name, stored_path, title, doc_type, dates_json, status) "
                     "VALUES (?, 'Cal.txt', 'test/Cal.txt', 'Calendar', 'schedule', "
                     "'[{\"date\": \"2026-10-07\", \"label\": \"Unit 2 test\"}]', 'filed')", (CLASS,))
    client.put(f"/agents/scheduler/term?class_id={CLASS}", json=TERM)
    yield CLASS
    with connect() as conn:
        for table in ("library_files", "calendar_events", "term_calendar", "approvals"):
            conn.execute(f"DELETE FROM {table} WHERE class_id = ?", (CLASS,))


def _pending(client, agent: str) -> dict:
    return client.get(f"/agents/approvals?class_id={CLASS}&agent={agent}").json()["approvals"][0]


def test_no_ai_draft_can_be_approved_after_a_restart(client, history_calendar):
    assert client.post(f"/agents/scheduler/draft?class_id={CLASS}").json()["status"] == "waiting_for_approval"
    scheduler_runner._live_graphs.clear()  # what a service restart does
    a = _pending(client, "scheduler")
    out = client.post(f"/agents/approvals/{a['approval_id']}/decide",
                      json={"type": "approve", "decided_by": "teacher", "role": "teacher"})
    assert out.status_code == 200, out.text
    published = client.get(f"/agents/scheduler/events?class_id={CLASS}&status=published").json()["events"]
    assert "Unit 2 test" in [e["title"] for e in published]
    assert approvals.get(a["approval_id"])["status"] == "approved"


def test_failed_action_puts_the_approval_back_to_pending(client, history_calendar, monkeypatch):
    client.post(f"/agents/scheduler/draft?class_id={CLASS}")
    a = _pending(client, "scheduler")

    def broken(group_id, decisions):
        raise RuntimeError("model unavailable")

    monkeypatch.setitem(approvals._resumers, "scheduler", broken)
    with pytest.raises(RuntimeError):
        approvals.decide(a["approval_id"], "approve")
    assert approvals.get(a["approval_id"])["status"] == "pending", "the teacher can try again"


def test_decision_stands_when_the_action_already_ran(client, history_calendar, monkeypatch):
    """Found in review: if the tool ran (events published) and only the closing model call
    failed, reverting to pending would let a later "reject" contradict what was published."""
    assert client.post(f"/agents/scheduler/draft?class_id={CLASS}").json()["status"] == "waiting_for_approval"
    scheduler_runner._live_graphs.clear()

    class Boom(Exception):
        pass

    # Simulate "tool ran, then the closing step failed": publish, then raise from the runner.
    original_invoke = scheduler_runner._invoke

    def invoke_then_fail(graph, graph_input, thread_id, class_id):
        original_invoke(graph, graph_input, thread_id, class_id)  # the approved publish runs
        raise Boom("quota exceeded on the closing message")

    monkeypatch.setattr(scheduler_runner, "_invoke", invoke_then_fail)
    monkeypatch.setattr(scheduler_runner, "_still_waiting", staticmethod(lambda graph, thread_id: False))
    a = _pending(client, "scheduler")
    with pytest.raises(approvals.ResumeFailed):
        approvals.decide(a["approval_id"], "approve")
    assert approvals.get(a["approval_id"])["status"] == "approved", "the publish happened, so the decision stands"
    published = client.get(f"/agents/scheduler/events?class_id={CLASS}&status=published").json()["events"]
    assert "Unit 2 test" in [e["title"] for e in published]
