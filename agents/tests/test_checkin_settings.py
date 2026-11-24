"""Teacher settings for a published check-in: GET/PATCH /agents/tutor/checkin/{id}/settings."""
from __future__ import annotations

import pytest

from app.shared import checkin as ck
from app.shared.db import connect
from tests.checkin_fixtures import make_checkin

CLASS = 4  # "Intro to CS - Period 6": no other test sets a term or calendar here
TERM = {"term_start": "2099-01-05", "term_end": "2099-05-29",
        "holidays": [{"date": "2099-01-19", "label": "MLK Day"}], "max_per_day": 2}
LESSON = "2099-01-16"       # Friday
DUE_DAY = "2099-01-14"      # Wednesday, the teacher's day...
DUE = "2099-01-15T06:59:00.000Z"  # ...11:59 PM in Utah is already Thursday in UTC


def url(aid: int) -> str:
    return f"/agents/tutor/checkin/{aid}/settings"


def due_events(aid: int) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM calendar_events WHERE assignment_id = ? AND kind = 'assignment_due' "
            "AND status != 'removed' ORDER BY event_id", (aid,))]


@pytest.fixture
def term(client):
    assert client.put(f"/agents/scheduler/term?class_id={CLASS}", json=TERM).status_code == 200
    yield TERM
    with connect() as conn:
        conn.execute("DELETE FROM calendar_events WHERE class_id = ?", (CLASS,))
        conn.execute("DELETE FROM term_calendar WHERE class_id = ?", (CLASS,))


@pytest.fixture
def checkin(client, term):
    c = make_checkin(class_id=CLASS)
    r = client.patch(url(c.assignment_id), json={"lesson_date": LESSON, "due_date": DUE, "due_day": DUE_DAY})
    assert r.status_code == 200, r.text
    return c


# ---------------------------------------------------------------- read, 404
def test_get_settings(client, checkin):
    s = client.get(url(checkin.assignment_id)).json()["settings"]
    assert s["title"] == "Unit 2 check-in" and s["unit"] == "Unit 2: Cell Structure"
    assert (s["lesson_date"], s["due_date"], s["due_day"]) == (LESSON, DUE, DUE_DAY)
    assert (s["tutor_mode"], s["tutor_reveal_after"], s["mastery_threshold"]) == ("hints_only", 2, 0.8)
    assert s["past_due"] is False and s["unlocked_students"] == 0
    assert s["calendar_event"]["date"] == DUE_DAY and s["calendar_event"]["status"] == "published"


def test_legacy_assignments_and_unknown_ids_are_404(client):
    with connect() as conn:
        legacy = conn.execute("SELECT assignment_id FROM assignments WHERE mode = 'graded' LIMIT 1").fetchone()[0]
    for aid in (legacy, 999999):
        assert client.get(url(aid)).status_code == 404
        assert client.patch(url(aid), json={"title": "Nope"}).status_code == 404
    with connect() as conn:
        assert conn.execute("SELECT mode FROM assignments WHERE assignment_id = ?", (legacy,)).fetchone()[0] == "graded"


# ---------------------------------------------------------------- validation
@pytest.mark.parametrize("body, says", [
    ({"due_date": "2099-01-17T06:59:00.000Z", "due_day": "2099-01-16"}, None),  # on the lesson day: fine
    ({"due_date": "2099-01-18T06:59:00.000Z", "due_day": "2099-01-17"}, "on or before the lesson"),
    ({"lesson_date": "2099-01-13"}, "on or before the lesson"),               # lesson moved before the due day
    ({"lesson_date": "01/16/2099"}, "like 2026-12-03"),
    ({"due_date": "next friday"}, "date and time"),
    ({"due_date": DUE, "due_day": "2099-01-20"}, "doesn't match"),
    ({"title": "   "}, "can't be empty"),
    ({"tutor_mode": "tell_everything"}, "Tutor mode"),
    ({"tutor_reveal_after": 3}, "only applies"),                              # still hints_only
    ({"tutor_mode": "answer_after_tries", "tutor_reveal_after": 11}, "between 1 and 10"),
    ({"mastery_threshold": 0.05}, "between 10% and 100%"),
    ({"mastery_threshold": 5}, "between 10% and 100%"),                       # 5% as a percent: too low
    ({"mastery_threshold": 150}, "between 10% and 100%"),
])
def test_validation(client, checkin, body, says):
    before = client.get(url(checkin.assignment_id)).json()["settings"]
    r = client.patch(url(checkin.assignment_id), json=body)
    if says is None:
        assert r.status_code == 200, r.text
        return
    assert r.status_code == 422, r.text
    assert says in r.json()["detail"]
    assert client.get(url(checkin.assignment_id)).json()["settings"] == before  # nothing half-saved


def test_title_mode_and_tries_change_together(client, checkin):
    r = client.patch(url(checkin.assignment_id), json={
        "title": "  Cells   check-in ", "tutor_mode": "answer_after_tries", "tutor_reveal_after": 3}).json()
    assert sorted(r["changed"]) == ["title", "tutor_mode", "tutor_reveal_after"]
    s = r["settings"]
    assert (s["title"], s["tutor_mode"], s["tutor_reveal_after"]) == ("Cells check-in", "answer_after_tries", 3)
    assert any("Tutor mode changed" in n for n in r["notes"])
    # The calendar entry follows the title (it still had the automatic "<title> due" name).
    assert due_events(checkin.assignment_id)[0]["title"] == "Cells check-in due"
    with connect() as conn:
        row = conn.execute("SELECT assignment_name, tutor_mode, tutor_reveal_after FROM assignments "
                           "WHERE assignment_id = ?", (checkin.assignment_id,)).fetchone()
    assert tuple(row) == ("Cells check-in", "answer_after_tries", 3)


def test_resending_the_same_values_changes_nothing(client, checkin):
    r = client.patch(url(checkin.assignment_id), json={
        "title": "Unit 2 check-in", "lesson_date": LESSON, "due_date": DUE, "due_day": DUE_DAY,
        "tutor_mode": "hints_only", "mastery_threshold": 80}).json()
    assert r["changed"] == [] and r["notes"] == ["Nothing changed."] and r["calendar_note"] is None
    assert len(due_events(checkin.assignment_id)) == 1


def test_lesson_date_alone(client, checkin):
    r = client.patch(url(checkin.assignment_id), json={"lesson_date": "2099-01-20"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["changed"] == ["lesson_date"] and out["settings"]["lesson_date"] == "2099-01-20"
    assert out["settings"]["due_date"] == DUE and out["calendar_note"] is None
    assert due_events(checkin.assignment_id)[0]["date"] == DUE_DAY  # the due entry doesn't move
    # A lesson on a day off is allowed (the picker warns first) but noted.
    out = client.patch(url(checkin.assignment_id), json={"lesson_date": "2099-01-19"}).json()
    assert any("holiday (MLK Day)" in n for n in out["notes"])


# ---------------------------------------------------------------- threshold
def test_threshold_accepts_percent_and_never_relocks(client, checkin):
    aid, student = checkin.assignment_id, 2
    with connect() as conn:  # a student who already unlocked the check-in at 80%
        conn.execute("INSERT INTO game_scores (student_id, assignment_id, points, unlocked_at) "
                     "VALUES (?, ?, 0, '2099-01-10T00:00:00.000Z')", (student, aid))
    out = client.patch(url(aid), json={"mastery_threshold": 100}).json()
    assert out["settings"]["mastery_threshold"] == 1.0 and out["changed"] == ["mastery_threshold"]
    note = out["notes"][0]
    assert "raised from 80% to 100%" in note and "1 student who already unlocked it keeps it" in note
    with connect() as conn:
        assert ck.practice_stats(conn, student, aid)["unlocked"]           # still unlocked
        assert not ck.practice_stats(conn, 4, aid)["unlocked"]             # nobody else is

    out = client.patch(url(aid), json={"mastery_threshold": 0.6}).json()
    assert out["settings"]["mastery_threshold"] == 0.6
    assert "lowered from 100% to 60%" in out["notes"][0] and "unlocking is permanent" in out["notes"][0]


def test_threshold_note_when_nobody_unlocked(client, checkin):
    out = client.patch(url(checkin.assignment_id), json={"mastery_threshold": 90}).json()
    assert "No student has unlocked it yet." in out["notes"][0]


# ---------------------------------------------------------------- calendar
def test_due_change_moves_the_calendar_entry(client, checkin):
    [event] = due_events(checkin.assignment_id)
    assert (event["date"], event["status"], event["source"]) == (DUE_DAY, "published", "unit package")
    out = client.patch(url(checkin.assignment_id),
                       json={"due_date": "2099-01-14T06:59:00.000Z", "due_day": "2099-01-13"}).json()
    assert out["changed"] == ["due_date"] and "moved" in out["calendar_note"]
    [moved] = due_events(checkin.assignment_id)
    assert moved["event_id"] == event["event_id"] and moved["date"] == "2099-01-13"
    assert out["settings"]["due_day"] == "2099-01-13"


@pytest.mark.parametrize("due_day, why", [
    ("2099-01-17", "weekend"),                 # Saturday
    ("2099-01-19", "holiday (MLK Day)"),
    ("2099-01-02", "outside the term"),
])
def test_due_on_a_day_off_keeps_the_entry_and_says_why(client, checkin, due_day, why):
    lesson = "2099-01-21"
    due = f"{due_day}T23:00:00.000Z"
    out = client.patch(url(checkin.assignment_id), json={"lesson_date": lesson, "due_date": due, "due_day": due_day})
    assert out.status_code == 200, out.text
    out = out.json()
    assert out["settings"]["due_date"] == due          # the due date itself still changes
    assert why in out["calendar_note"] and "stays on" in out["calendar_note"]
    assert out["calendar_note"] in out["notes"]
    assert [e["date"] for e in due_events(checkin.assignment_id)] == [DUE_DAY]


def test_per_day_limit(client, checkin):
    with connect() as conn:
        for title in ("Quiz A", "Lab report due"):
            conn.execute("INSERT INTO calendar_events (class_id, title, kind, date, source, status) "
                         "VALUES (?, ?, 'assessment', '2099-01-13', 'test', 'published')", (CLASS, title))
    out = client.patch(url(checkin.assignment_id),
                       json={"due_date": "2099-01-14T06:59:00.000Z", "due_day": "2099-01-13"}).json()
    assert "limit is 2" in out["calendar_note"]
    assert due_events(checkin.assignment_id)[0]["date"] == DUE_DAY


def test_missing_entry_is_created_when_the_day_is_valid(client, term):
    c = make_checkin(class_id=CLASS)
    assert due_events(c.assignment_id) == []
    # A weekend: nothing added, and the note says why.
    out = client.patch(url(c.assignment_id), json={
        "lesson_date": LESSON, "due_date": "2099-01-11T06:59:00.000Z", "due_day": "2099-01-10"}).json()
    assert "no due-date entry added" in out["calendar_note"] and "weekend" in out["calendar_note"]
    assert due_events(c.assignment_id) == [] and out["settings"]["calendar_event"] is None
    # A school day: added, published, from the unit package.
    out = client.patch(url(c.assignment_id), json={"due_date": DUE, "due_day": DUE_DAY}).json()
    [event] = due_events(c.assignment_id)
    assert (event["date"], event["title"], event["status"], event["source"], event["kind"]) == \
        (DUE_DAY, "Unit 2 check-in due", "published", "unit package", "assignment_due")
    assert "added" in out["calendar_note"] and out["settings"]["calendar_event"]["event_id"] == event["event_id"]


def test_without_a_term_only_weekends_are_refused(client):
    c = make_checkin(class_id=CLASS)
    try:
        out = client.patch(url(c.assignment_id), json={
            "lesson_date": "2099-01-21", "due_date": "2099-01-20T06:59:00.000Z", "due_day": "2099-01-19"}).json()
        assert "added" in out["calendar_note"]  # MLK Day isn't a holiday without a saved term
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM calendar_events WHERE class_id = ?", (CLASS,))


def test_past_due_note(client, checkin):
    out = client.patch(url(checkin.assignment_id),
                       json={"due_date": "2020-01-06T06:59:00.000Z", "due_day": "2020-01-05"}).json()
    assert out["settings"]["past_due"] is True
    assert any("already passed" in n for n in out["notes"])
    out = client.patch(url(checkin.assignment_id), json={"due_date": DUE, "due_day": DUE_DAY}).json()
    assert any("open again" in n for n in out["notes"])
