"""Calendar build-out: term suggestion and no-AI drafting from Library dates, and teacher edits."""
from __future__ import annotations

import json

import pytest

from app.agents.scheduler.drafting import classify, clean_title, suggest_term
from app.shared.db import connect

CLASS = 5  # "World History - Period 3": no other test files anything here
TERM = {"term_start": "2026-08-24", "term_end": "2026-12-18", "holidays": [], "max_per_day": 2}


def _file(conn, name: str, doc_type: str, dates: list[dict], title: str | None = None) -> None:
    conn.execute(
        "INSERT INTO library_files (class_id, original_name, stored_path, title, doc_type, dates_json, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'filed')",
        (CLASS, name, f"test/{name}", title or name, doc_type, json.dumps(dates)))


@pytest.fixture
def history(client):
    with connect() as conn:
        _file(conn, "Calendar.txt", "schedule", [
            {"date": "2026-08-24", "label": "First day"},
            {"date": "2026-09-16", "label": "Unit 1 quiz (ancient Egypt)"},
            {"date": "2026-11-25", "label": "Thanksgiving break"},
            {"date": "2026-11-27", "label": "Thanksgiving break"},
            {"date": "2026-12-09", "label": "Unit 4 project due"},
            {"date": "2026-12-18", "label": "Last day of the semester"},
        ], title="WORLD HISTORY CALENDAR")
        _file(conn, "Syllabus.docx", "syllabus", [
            {"date": "2026-09-16", "label": "Unit 1 quiz"},
            {"date": "2026-09-16", "label": "Unit 2 reading: Chapter 3"},
        ])
        _file(conn, "Unit1_Quiz.pdf", "quiz", [{"date": "2026-09-16", "label": "UNIT 1 QUIZ: EGYPT Date"}],
              title="UNIT 1 QUIZ: EGYPT   Date: 2026-09-16")
        _file(conn, "Weekend.pdf", "worksheet", [{"date": "2026-09-19", "label": "Saturday review session"}])
    yield CLASS
    with connect() as conn:
        conn.execute("DELETE FROM library_files WHERE class_id = ?", (CLASS,))
        conn.execute("DELETE FROM calendar_events WHERE class_id = ?", (CLASS,))
        conn.execute("DELETE FROM term_calendar WHERE class_id = ?", (CLASS,))
        conn.execute("DELETE FROM approvals WHERE class_id = ?", (CLASS,))


def test_labels_are_cleaned_and_sorted_into_kinds():
    assert clean_title("UNIT 1 QUIZ: LINEAR FUNCTIONS Date") == "Unit 1 Quiz: Linear Functions"
    assert clean_title("Compound Interest Project Rubric (due )") == "Compound Interest Project Rubric"
    assert classify("Thanksgiving break, no school") is None
    assert classify("First day") is None
    assert classify("Final project due") == "assignment_due"
    assert classify("Unit 2 test") == "assessment"
    assert classify("Read chapter 4") == "reading"
    assert classify("Field trip permission slips due") == "event"


def test_term_is_suggested_from_the_calendar_without_saving(client, history):
    out = client.get(f"/agents/scheduler/term/suggest?class_id={history}").json()
    term = out["term"]
    assert (term["term_start"], term["term_end"]) == ("2026-08-24", "2026-12-18")
    assert [h["date"] for h in term["holidays"]] == ["2026-11-25", "2026-11-26", "2026-11-27"], "range is filled in"
    assert client.get(f"/agents/scheduler/term?class_id={history}").json()["term"] is None, "nothing saved"


def test_suggestion_with_an_empty_library_says_so(client):
    assert suggest_term(2)["term"] is None


def test_draft_merges_duplicates_flags_problems_and_waits_for_approval(client, history):
    assert client.post(f"/agents/scheduler/draft?class_id={history}").status_code == 409, "term required"
    client.put(f"/agents/scheduler/term?class_id={history}", json=TERM)

    out = client.post(f"/agents/scheduler/draft?class_id={history}").json()
    assert out["status"] == "waiting_for_approval"
    drafted = {(e["date"], e["title"]) for e in out["drafted"]}
    assert drafted == {("2026-09-16", "Unit 1 quiz (ancient Egypt)"), ("2026-09-16", "Unit 2 reading: Chapter 3"),
                       ("2026-12-09", "Unit 4 project due")}
    quiz = next(e for e in out["drafted"] if e["kind"] == "assessment")
    assert quiz["source"] == "World History Calendar; Syllabus.docx; Unit 1 Quiz: Egypt", "3 files, 1 event"
    assert [(s["title"], s["problem"]) for s in out["skipped"]] == [("Saturday review session", "weekend")]

    events = client.get(f"/agents/scheduler/events?class_id={history}").json()["events"]
    assert {e["status"] for e in events} == {"proposed"}, "students see nothing until approved"
    again = client.post(f"/agents/scheduler/draft?class_id={history}").json()
    assert again["drafted"] == [] and sum(s["problem"] == "already on the calendar" for s in again["skipped"]) == 3

    approval = client.get(f"/agents/approvals?class_id={history}&agent=scheduler").json()["approvals"][0]
    assert approval["action_name"] == "publish_calendar"
    client.post(f"/agents/approvals/{approval['approval_id']}/decide",
                json={"type": "approve", "decided_by": "teacher", "role": "teacher"})
    published = client.get(f"/agents/scheduler/events?class_id={history}&status=published").json()["events"]
    assert len(published) == 3


def test_teacher_add_move_and_remove_follow_the_rules(client, history):
    client.put(f"/agents/scheduler/term?class_id={history}",
               json={**TERM, "holidays": [{"date": "2026-11-26", "label": "Thanksgiving"}], "max_per_day": 1})
    base = "/agents/scheduler/events"
    quiz = client.post(f"{base}?class_id={history}", json={"title": "Map quiz", "date": "2026-10-06", "kind": "assessment"})
    assert quiz.status_code == 200 and quiz.json()["event"]["status"] == "published"
    eid = quiz.json()["event"]["event_id"]

    assert client.post(f"{base}?class_id={history}", json={"title": "Sat", "date": "2026-10-10"}).status_code == 409
    full = client.post(f"{base}?class_id={history}", json={"title": "Essay", "date": "2026-10-06", "kind": "assignment_due"})
    assert full.status_code == 409 and "max 1" in full.json()["detail"]
    assert client.post(f"{base}?class_id={history}", json={"title": "Club fair", "date": "2026-10-06"}).status_code == 200

    assert client.patch(f"{base}/{eid}?class_id={history}", json={"date": "2026-11-26"}).status_code == 409, "holiday"
    moved = client.patch(f"{base}/{eid}?class_id={history}", json={"date": "2026-10-07", "title": "Map quiz (moved)"})
    assert moved.status_code == 200 and moved.json()["event"]["date"] == "2026-10-07"
    assert client.patch(f"{base}/{eid}?class_id={history}", json={"title": "Same day, still fine"}).status_code == 200

    assert client.delete(f"{base}/{eid}?class_id={history}").status_code == 200
    assert eid not in [e["event_id"] for e in client.get(f"{base}?class_id={history}").json()["events"]]
    with connect() as conn:
        assert conn.execute("SELECT status FROM calendar_events WHERE event_id = ?", (eid,)).fetchone()[0] == "removed"
    assert client.delete(f"{base}/{eid}?class_id={history}").status_code == 404
