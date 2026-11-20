"""Skeleton tests: every agent's offline demo runs end to end, approvals gate the
consequential actions, and the shared guardrails hold.  Run: npm run test:agents"""
from __future__ import annotations

import pytest

from app.shared.db import connect
from app.shared.guardrails import assert_safe_toolset, is_blocked

CLASS_ID = 1


def pending(client, agent):
    rows = client.get("/agents/approvals", params={"class_id": CLASS_ID, "agent": agent}).json()["approvals"]
    assert rows, f"expected a pending approval from {agent}"
    return rows


def test_health_lists_every_agent(client):
    body = client.get("/agents/health").json()
    names = {a["name"] for a in body["agents"]}
    assert names == {"filing", "scheduler", "materials", "games", "misconceptions", "tutor"}
    assert client.get("/agents/scheduler/ping").json()["pong"] is True


@pytest.mark.parametrize("name,blocked", [
    ("change_grade", True), ("update_student_grades", True), ("delete_file", True), ("send_email", True),
    ("check_grade_level", False), ("publish_calendar", False), ("apply_revision", False),
])
def test_hard_blocked_actions(name, blocked):
    assert is_blocked(name) is blocked


def test_assert_safe_toolset_rejects_forbidden_tool():
    def delete_file():  # noqa: D401
        """pretend tool"""
    with pytest.raises(ValueError):
        assert_safe_toolset([delete_file])


def test_scheduler_publish_waits_for_teacher_then_publishes(client):
    out = client.post("/agents/scheduler/demo", params={"class_id": CLASS_ID}).json()
    assert out["status"] == "waiting_for_approval"
    events = client.get("/agents/scheduler/events", params={"class_id": CLASS_ID}).json()["events"]
    assert events and all(e["status"] == "proposed" for e in events), "nothing is published before approval"

    row = pending(client, "scheduler")[0]
    assert row["action_name"] == "publish_calendar"
    res = client.post(f"/agents/approvals/{row['approval_id']}/decide", json={"type": "approve"}).json()
    assert res["status"] == "resumed" and res["result"]["status"] == "done"
    published = client.get("/agents/scheduler/events", params={"class_id": CLASS_ID, "status": "published"}).json()
    assert len(published["events"]) == 2


def test_scheduler_reject_means_tool_never_runs(client):
    client.post("/agents/scheduler/demo", params={"class_id": CLASS_ID})
    row = pending(client, "scheduler")[0]
    client.post(f"/agents/approvals/{row['approval_id']}/decide", json={"type": "reject", "message": "Not yet"})
    with connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM calendar_events WHERE status = 'proposed'").fetchone()[0]
    assert n == 2, "rejected publish leaves the new events unpublished"


def test_materials_revision_is_a_new_version_after_approval(client):
    client.post("/agents/filing/demo", params={"class_id": CLASS_ID})
    out = client.post("/agents/materials/demo", params={"class_id": CLASS_ID}).json()
    assert out["status"] == "waiting_for_approval"
    row = pending(client, "materials")[0]
    assert row["action_name"] == "apply_revision"
    draft_id = row["action_args"]["draft_file_id"]
    client.post(f"/agents/approvals/{row['approval_id']}/decide", json={"type": "approve"})
    with connect() as conn:
        draft = conn.execute("SELECT status, version_of FROM library_files WHERE file_id = ?", (draft_id,)).fetchone()
        original = conn.execute("SELECT status FROM library_files WHERE file_id = ?", (draft["version_of"],)).fetchone()
    assert draft["status"] == "filed" and original["status"] == "archived"


def test_games_teacher_edit_is_what_gets_published(client):
    client.post("/agents/filing/demo", params={"class_id": CLASS_ID})
    out = client.post("/agents/games/demo", params={"class_id": CLASS_ID}).json()
    assert out["status"] == "waiting_for_approval"
    row = pending(client, "games")[0]
    edited = {**row["action_args"], "items": [{"front": "Edited?", "back": "Yes"}]}
    client.post(f"/agents/approvals/{row['approval_id']}/decide", json={"type": "edit", "edited_args": edited})
    acts = client.get("/agents/games/activities", params={"class_id": CLASS_ID}).json()["activities"]
    mine = [a for a in acts if a["activity_id"] == row["action_args"]["activity_id"]]
    assert len(mine) == 1, "resume must not insert a duplicate draft"
    assert mine[0]["status"] == "published" and mine[0]["items"] == [{"front": "Edited?", "back": "Yes"}]


def test_misconceptions_redacts_before_any_model(client):
    with connect() as conn:
        conn.execute(
            "INSERT INTO student_chat_messages (student_id, assignment_id, attempt_number, role, content) VALUES (1, 1, 1, 'user', ?)",
            ("Hi I'm Alice Johnson (alice@school.edu), is mitosis the same as meiosis?",),
        )
    out = client.post("/agents/misconceptions/demo", params={"class_id": CLASS_ID, "assignment_id": 1}).json()
    joined = " ".join(out["sample_redacted"])
    assert "Alice" not in joined and "alice@school.edu" not in joined and "[student]" in joined


def test_cannot_decide_twice(client):
    client.post("/agents/scheduler/demo", params={"class_id": CLASS_ID})
    row = pending(client, "scheduler")[0]
    client.post(f"/agents/approvals/{row['approval_id']}/decide", json={"type": "approve"})
    again = client.post(f"/agents/approvals/{row['approval_id']}/decide", json={"type": "approve"})
    assert again.status_code == 409
