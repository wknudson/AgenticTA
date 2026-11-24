"""Student practice endpoints (games agent): GET /practice/{id} and POST /practice/{id}/answer."""
from __future__ import annotations

import json

from app.shared.db import connect
from app.shared.student_auth import issue_student_token
from tests.checkin_fixtures import ENROLLED, NOT_ENROLLED, make_checkin


def auth(student_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_student_token(student_id)}"}


def test_practice_state_for_an_enrolled_student(client):
    c = make_checkin()
    with connect() as conn:  # teacher-side extras in items_json must never reach the student
        items = json.loads(conn.execute("SELECT items_json FROM study_activities WHERE activity_id = ?",
                                        (c.activity_ids[0],)).fetchone()[0])
        items[0].update(source="Cell slides", review={"ok": False, "note": "check this"})
        conn.execute("UPDATE study_activities SET items_json = ?, review_json = '[\"secret note\"]' "
                     "WHERE activity_id = ?", (json.dumps(items), c.activity_ids[0]))
    r = client.get(f"/agents/games/practice/{c.assignment_id}", headers=auth(ENROLLED[0]))
    assert r.status_code == 200
    body = r.json()
    assert body["assignment"] == {"assignment_id": c.assignment_id, "title": "Unit 2 check-in",
                                  "unit": "Unit 2: Cell Structure", "lesson_date": "2099-01-02",
                                  "due_date": "2099-01-01T23:59:00.000Z"}
    assert [a["kind"] for a in body["activities"]] == ["flashcards", "matching", "fill_in"]
    assert body["activities"][0]["items"][0] == {"item_id": "c0", "front": "Mitochondria", "back": "Makes ATP"}
    assert body["activities"][2]["items"][0]["alternates"] == ["mitochondrion"]
    raw = json.dumps(body)
    assert "Cell slides" not in raw and "secret note" not in raw and "check this" not in raw
    assert body["progress"] == {} and body["replay_gap"] == {"1": 3, "2": 8, "3": 20}
    s = body["stats"]
    assert (s["total"], s["mastered"], s["unlocked"], s["threshold"], s["started"]) == (10, 0, False, 0.8, False)


def test_answers_update_progress_points_and_unlock(client):
    c = make_checkin(threshold=0.5)
    s, h = ENROLLED[1], auth(ENROLLED[1])
    url = f"/agents/games/practice/{c.assignment_id}/answer"
    out = None
    for aid, iid in c.items[:5]:
        out = client.post(url, headers=h, json={"activity_id": aid, "item_id": iid, "correct": True}).json()
    assert out["mastered"] == 5 and out["unlocked"] and out["just_unlocked"] and out["points_awarded"] == 20
    assert out["multiplier"] == 2 and out["streak"] == 5
    miss = client.post(url, headers=h, json={"activity_id": c.items[0][0], "item_id": c.items[0][1],
                                             "correct": False}).json()
    assert miss["points_awarded"] == 0 and miss["streak"] == 0 and miss["mastered"] == 4
    assert not miss["just_unlocked"]
    state = client.get(f"/agents/games/practice/{c.assignment_id}", headers=h).json()
    key = f"{c.items[0][0]}:{c.items[0][1]}"
    assert state["progress"][key] == {"times_seen": 2, "times_correct": 1, "last_correct": 0, "box": 1}
    assert state["stats"]["points"] == out["points"] and state["stats"]["started"]
    with connect() as conn:
        assert conn.execute("SELECT answers FROM game_scores WHERE student_id = ? AND assignment_id = ?",
                            (s, c.assignment_id)).fetchone()[0] == 6


def test_unknown_card_is_400(client):
    c = make_checkin()
    r = client.post(f"/agents/games/practice/{c.assignment_id}/answer", headers=auth(ENROLLED[2]),
                    json={"activity_id": c.activity_ids[0], "item_id": "nope", "correct": True})
    assert r.status_code == 400 and "isn't part of" in r.json()["detail"]


def test_auth_enrollment_and_due_date(client):
    c = make_checkin()
    url = f"/agents/games/practice/{c.assignment_id}"
    answer = {"activity_id": c.items[0][0], "item_id": c.items[0][1], "correct": True}
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer not.a.token"}).status_code == 401
    assert client.post(f"{url}/answer", json=answer).status_code == 401
    assert client.get(url, headers=auth(NOT_ENROLLED)).status_code == 403
    assert client.post(f"{url}/answer", headers=auth(NOT_ENROLLED), json=answer).status_code == 403
    assert client.get("/agents/games/practice/1", headers=auth(ENROLLED[0])).status_code == 404, "graded, not a check-in"

    late = make_checkin(due_date="2000-01-01T00:00:00.000Z")
    late_url = f"/agents/games/practice/{late.assignment_id}"
    assert client.get(late_url, headers=auth(ENROLLED[3])).status_code == 200, "reading after the due date is fine"
    r = client.post(f"{late_url}/answer", headers=auth(ENROLLED[3]),
                    json={"activity_id": late.items[0][0], "item_id": late.items[0][1], "correct": True})
    assert r.status_code == 403
