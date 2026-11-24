"""GET /agents/scheduler/feed (everything the month calendar shows, in one call) and
GET /agents/scheduler/checkin-suggestions (no-AI lesson days for check-ins)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from app.agents.scheduler import feed
from app.shared.db import connect
from tests.checkin_fixtures import make_checkin

FEED = "/agents/scheduler/feed"
SUGGEST = "/agents/scheduler/checkin-suggestions"
TERM = {"term_start": "2026-08-24", "term_end": "2026-12-18", "max_per_day": 2,
        "holidays": [{"date": f"2026-11-{d}", "label": "Thanksgiving break"} for d in (25, 26, 27)]}
ACTIVE, INACTIVE = (1, 2, 3, 5), 6   # seed students


@pytest.fixture
def cls(client):
    """A class of its own, so no other test's rows show up here (and ours don't show up there)."""
    with connect() as conn:
        class_id = conn.execute("INSERT INTO classes (class_code, subject_id, teacher_id, class_name) "
                                "VALUES ('FEEDTEST', 1, 1, 'Scheduler feed test')").lastrowid
        for sid in ACTIVE:
            conn.execute("INSERT INTO student_classes (student_id, class_id, status) VALUES (?, ?, 'active')",
                         (sid, class_id))
        conn.execute("INSERT INTO student_classes (student_id, class_id, status) VALUES (?, ?, 'inactive')",
                     (INACTIVE, class_id))
    yield class_id
    with connect() as conn:
        conn.execute("DELETE FROM assignments WHERE class_id = ?", (class_id,))   # cascades questions, progress
        conn.execute("DELETE FROM student_classes WHERE class_id = ?", (class_id,))
        conn.execute("DELETE FROM classes WHERE class_id = ?", (class_id,))      # cascades the agent tables


def _checkin(class_id: int, unit: str, lesson: str | None, due: str | None):
    c = make_checkin(class_id=class_id, unit=unit, due_date=due)
    with connect() as conn:
        conn.execute("UPDATE assignments SET lesson_date = ?, assignment_name = ? WHERE assignment_id = ?",
                     (lesson, f"{unit.split(':')[0]} check-in", c.assignment_id))
    return c


def _event(conn, class_id: int, title: str, day: str, kind: str = "event", status: str = "published",
           assignment_id: int | None = None, source: str = "added by teacher") -> int:
    return conn.execute("INSERT INTO calendar_events (class_id, title, kind, date, assignment_id, source, status) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)", (class_id, title, kind, day, assignment_id, source, status)).lastrowid


def _graded(conn, class_id: int, name: str, kind: str, due: str | None) -> int:
    return conn.execute("INSERT INTO assignments (class_id, assignment_name, type, max_points, due_date) "
                        "VALUES (?, ?, ?, 20, ?)", (class_id, name, kind, due)).lastrowid


def _package(conn, class_id: int, unit: str, settings: dict, status: str = "draft",
             assignment_id: int | None = None) -> int:
    return conn.execute("INSERT INTO unit_packages (class_id, unit, settings_json, status, assignment_id) "
                        "VALUES (?, ?, ?, ?, ?)", (class_id, unit, json.dumps(settings), status, assignment_id)).lastrowid


def _approval(conn, class_id: int, package_id: int, status: str, decided_at: str | None) -> None:
    conn.execute("INSERT INTO approvals (group_id, position, agent, class_id, action_name, action_args, status, "
                 "decided_at) VALUES (?, 0, 'games', ?, 'publish_unit_package', ?, ?, ?)",
                 (f"games-test-{package_id}-{status}", class_id, json.dumps({"class_id": class_id, "package_id": package_id}),
                  status, decided_at))


def _file(conn, class_id: int, name: str, unit: str | None, dates: list[dict], status: str = "filed",
          doc_type: str = "lecture", title: str | None = None) -> None:
    conn.execute("INSERT INTO library_files (class_id, original_name, stored_path, title, doc_type, unit, dates_json, "
                 "status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (class_id, name, f"test/{name}", title or name, doc_type, unit, json.dumps(dates), status))


def _get(client, url: str, **params):
    r = client.get(url, params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ---- Feed ----------------------------------------------------------------------------------------

def test_feed_has_everything_the_month_shows(client, cls):
    assert client.put(f"/agents/scheduler/term?class_id={cls}", json=TERM).status_code == 200
    # Published from a package approved on Nov 2; its calendar entry is the teacher's local due day.
    quad = _checkin(cls, "Unit 3: Quadratic Functions", "2026-11-11", "2026-11-10T06:59:00.000Z")
    poly = _checkin(cls, "Unit 4: Polynomials", "2026-11-20", "2026-11-19T23:59:00.000Z")   # no approval, no event
    early = _checkin(cls, "Unit 5: Exponentials", "2026-11-30", "2026-11-17T23:59:00.000Z")  # due long before lesson
    october = _checkin(cls, "Unit 2: Linear Functions", "2026-11-02", "2026-11-01T23:59:00.000Z")  # opens in October
    december = _checkin(cls, "Unit 6: Logarithms", "2026-12-10", "2026-12-09T23:59:00.000Z")
    with connect() as conn:
        pid = _package(conn, cls, "Unit 3: Quadratic Functions", {"title": "Unit 3 check-in"}, "published", quad.assignment_id)
        _approval(conn, cls, pid, "approved", "2026-11-02T12:00:00.000Z")
        _approval(conn, cls, pid, "rejected", "2026-10-30T12:00:00.000Z")   # an earlier rejection doesn't count
        due_event = _event(conn, cls, "Unit 3 check-in due", "2026-11-09", "assignment_due",
                           assignment_id=quad.assignment_id, source="unit package")
        _event(conn, cls, "Unit 3 check-in due (old)", "2026-11-10", "assignment_due", "removed",
               assignment_id=quad.assignment_id, source="unit package")
        quiz = _graded(conn, cls, "Polynomial quiz", "quiz", "2026-11-13T23:59:00.000Z")
        essay = _graded(conn, cls, "Essay", "essay", "2026-12-15T23:59:00.000Z")
        _graded(conn, cls, "Reading log", "homework", None)
        trip = _event(conn, cls, "Field trip", "2026-11-12")
        quiz_event = _event(conn, cls, "Polynomial quiz", "2026-11-13", "assessment", assignment_id=quiz,
                            source="assignment")
        test = _event(conn, cls, "Unit 4 test", "2026-11-18", "assessment", "proposed", source="Syllabus.docx")
        _event(conn, cls, "Assembly", "2026-11-13", status="removed")
        _event(conn, cls, "Old idea", "2026-11-16", status="rejected")
        _event(conn, cls, "Winter concert", "2026-12-15")
        _event(conn, cls, "Spring kickoff", "2027-01-12")   # after the term
        seq = _package(conn, cls, "Unit 7: Sequences", {"title": "Unit 7 check-in", "lesson_date": "2026-11-24",
                                                       "due_date": "2026-11-24T06:59:00.000Z", "due_day": "2026-11-23"})
        mat = _package(conn, cls, "Unit 8: Matrices", {"lesson_date": "2026-11-30", "due_date": "2026-11-29T23:59:00.000Z"})
        _package(conn, cls, "Unit 9: Probability", {"title": "Later", "lesson_date": "2026-12-14"})
        _package(conn, cls, "Unit 7: Sequences", {"title": "Rejected", "lesson_date": "2026-11-24"}, "rejected")
        # Stages on the quadratics check-in: 1 nothing, 2 played, 3 answered one, 5 resolved all three
        # (one fixed after a miss). Student 6 is no longer active in the class, so never counts.
        mc1, mc2 = quad.mc_ids
        for sid in (2, INACTIVE):
            conn.execute("INSERT INTO game_scores (student_id, assignment_id, points) VALUES (?, ?, 10)",
                         (sid, quad.assignment_id))
        for sid, qid, status, first in ((3, mc1, "correct", 1), (INACTIVE, mc1, "correct", 1), (5, mc1, "correct", 1),
                                        (5, mc2, "fixed", 0), (5, quad.explain_id, "correct", 1)):
            conn.execute("INSERT INTO checkin_item_status (student_id, assignment_id, question_id, status, first_correct) "
                         "VALUES (?, ?, ?, ?, ?)", (sid, quad.assignment_id, qid, status, first))

    body = _get(client, FEED, class_id=cls, start="2026-11-01", end="2026-11-30")
    assert set(body) == {"term", "events", "checkins", "drafts", "assignments"}
    assert body["term"] == _get(client, "/agents/scheduler/term", class_id=cls)["term"]

    assert body["events"] == [
        {"event_id": trip, "title": "Field trip", "kind": "event", "date": "2026-11-12", "status": "published",
         "assignment_id": None, "source": "added by teacher"},
        {"event_id": quiz_event, "title": "Polynomial quiz", "kind": "assessment", "date": "2026-11-13",
         "status": "published", "assignment_id": quiz, "source": "assignment"},
        {"event_id": test, "title": "Unit 4 test", "kind": "assessment", "date": "2026-11-18", "status": "proposed",
         "assignment_id": None, "source": "Syllabus.docx"},
    ], "removed/rejected, out-of-range and check-in rows are left out"

    rows = {c["assignment_id"]: c for c in body["checkins"]}
    assert set(rows) == {quad.assignment_id, poly.assignment_id, early.assignment_id, october.assignment_id}
    assert rows[quad.assignment_id] == {
        "assignment_id": quad.assignment_id, "title": "Unit 3 check-in", "unit": "Unit 3: Quadratic Functions",
        "lesson_date": "2026-11-11", "due_date": "2026-11-10T06:59:00.000Z",
        "due_day": "2026-11-09", "open_day": "2026-11-02", "status": "closed",
        "counts": {"total": 4, "not_started": 1, "practicing": 1, "checkin": 1, "complete": 1},
        "calendar_event_id": due_event}
    assert {k: rows[poly.assignment_id][k] for k in ("due_day", "open_day", "calendar_event_id")} == {
        "due_day": "2026-11-19", "open_day": "2026-11-13", "calendar_event_id": None}, "fallback: lesson minus 7 days"
    assert rows[early.assignment_id]["open_day"] == "2026-11-17", "never after the due day"
    assert rows[october.assignment_id]["open_day"] == "2026-10-26", "overlapping the range is enough"
    assert rows[poly.assignment_id]["counts"] == {"total": 4, "not_started": 4, "practicing": 0, "checkin": 0,
                                                  "complete": 0}
    assert [c["assignment_id"] for c in body["checkins"]] == [
        october.assignment_id, quad.assignment_id, early.assignment_id, poly.assignment_id], "by due day"

    assert body["drafts"] == [
        {"package_id": seq, "unit": "Unit 7: Sequences", "title": "Unit 7 check-in", "lesson_date": "2026-11-24",
         "due_day": "2026-11-23"},
        {"package_id": mat, "unit": "Unit 8: Matrices", "title": "Unit 8: Matrices check-in",
         "lesson_date": "2026-11-30", "due_day": "2026-11-29"},
    ]
    assert body["assignments"] == [{"assignment_id": quiz, "title": "Polynomial quiz", "type": "quiz",
                                    "due_date": "2026-11-13T23:59:00.000Z"}], "graded only, due in range"

    # No range: the whole term.
    term = _get(client, FEED, class_id=cls)
    titles = {e["title"] for e in term["events"]}
    assert "Winter concert" in titles and "Spring kickoff" not in titles
    assert essay in [a["assignment_id"] for a in term["assignments"]]
    assert december.assignment_id in [c["assignment_id"] for c in term["checkins"]]
    assert [d["title"] for d in term["drafts"]] == ["Unit 7 check-in", "Unit 8: Matrices check-in", "Later"]


def test_feed_status_and_default_range_without_a_term(client, cls):
    now, today = datetime.now(timezone.utc), date.today()

    def iso(when: datetime) -> str:
        return when.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    closed = _checkin(cls, "Unit 1: Basics", (today + timedelta(days=1)).isoformat(), iso(now - timedelta(days=1)))
    soon = _checkin(cls, "Unit 2: Next", (today + timedelta(days=1)).isoformat(), iso(now + timedelta(hours=2)))
    later = _checkin(cls, "Unit 3: Later", (today + timedelta(days=4)).isoformat(), iso(now + timedelta(days=3)))
    far = _checkin(cls, "Unit 4: Far", (today + timedelta(days=401)).isoformat(), iso(now + timedelta(days=400)))
    with connect() as conn:
        for title, offset in (("in, back", -29), ("out, back", -31), ("in, ahead", 119), ("out, ahead", 121)):
            _event(conn, cls, title, (today + timedelta(days=offset)).isoformat())

    body = _get(client, FEED, class_id=cls)
    assert body["term"] is None
    assert {e["title"] for e in body["events"]} == {"in, back", "in, ahead"}, "today-30 .. today+120"
    status = {c["assignment_id"]: c["status"] for c in body["checkins"]}
    assert status == {closed.assignment_id: "closed", soon.assignment_id: "due_soon", later.assignment_id: "live"}
    assert far.assignment_id not in status


def test_feed_rejects_a_bad_range(client, cls):
    assert client.get(FEED, params={"class_id": cls, "start": "2026-11-30", "end": "2026-11-01"}).status_code == 422
    assert client.get(FEED, params={"class_id": cls, "start": "soon"}).status_code == 422


# ---- Check-in suggestions ------------------------------------------------------------------------

def test_lesson_day_skips_weekends_holidays_and_the_past():
    monday = date(2026, 11, 2)
    # Mon Nov 30 test: back past the weekend and Thanksgiving (Wed-Fri) to Tue 24 (1st) and Mon 23 (2nd).
    assert feed.lesson_day(date(2026, 11, 30), TERM, monday) == (date(2026, 11, 23), 2)
    assert feed.lesson_day(date(2026, 11, 30), None, monday) == (date(2026, 11, 26), 2), "no term: weekdays only"
    assert feed.lesson_day(date(2026, 11, 4), TERM, monday) == (date(2026, 11, 3), 1), "today doesn't count"
    assert feed.lesson_day(date(2026, 11, 3), TERM, monday) == (None, 0)
    assert feed.lesson_day(date(2027, 1, 12), TERM, monday) == (date(2026, 12, 17), 2), "inside the term only"
    assert feed.lesson_day(date(2026, 8, 25), TERM, date(2026, 8, 1)) == (date(2026, 8, 24), 1), "term start"
    assert feed.mentions_unit("Unit 3: Quadratic Functions", "UNIT 3 QUIZ")
    assert feed.mentions_unit("Unit 3: Quadratic Functions", "unit3 test")
    assert not feed.mentions_unit("Unit 3: Quadratic Functions", "Unit 30 quiz")
    assert feed.mentions_unit("Cells", "Cells quiz") and not feed.mentions_unit("Cells", "Unit 1 quiz")


def test_suggestions_anchor_on_the_next_quiz_or_test(client, cls, monkeypatch):
    monkeypatch.setattr(feed, "_today", lambda: date(2026, 11, 2))   # a Monday
    assert client.put(f"/agents/scheduler/term?class_id={cls}", json=TERM).status_code == 200
    units = {n: name for n, name in ((2, "Unit 2: Linear Functions"), (3, "Unit 3: Quadratic Functions"),
                                     (4, "Unit 4: Polynomials"), (5, "Unit 5: Exponentials"), (6, "Unit 6: Logarithms"),
                                     (7, "Unit 7: Sequences"), (8, "Unit 8: Matrices"))}
    with connect() as conn:
        for n, name in units.items():
            _file(conn, cls, f"Unit{n}_Notes.pdf", name, [])
        _file(conn, cls, "Unit3_Practice.pdf", units[3], [{"date": "2026-11-20", "label": "Unit 3 test"}])
        _file(conn, cls, "Unit9_Ideas.pdf", "Unit 9: Draft Ideas", [], status="needs_review")
        _file(conn, cls, "Unit10_Old.pdf", "Unit 10: Old", [{"date": "2026-11-20", "label": "Unit 10 quiz"}],
              status="archived")
        # The course calendar is course-wide (no unit): it adds dates, not a unit.
        _file(conn, cls, "Calendar.pdf", None, [
            {"date": "2026-11-30", "label": "Unit 4 Test"},
            {"date": "2026-11-06", "label": "Unit 40 quiz"},
            {"date": "2026-11-16", "label": "Unit 4 project due"},
            {"date": "2026-10-01", "label": "Unit 7 quiz"},
            {"date": "2026-11-18", "label": "Unit 7 notebook check"},
            {"date": "2026-11-09", "label": "Unit 5 quiz"},
        ], doc_type="schedule", title="Algebra II calendar")
        _event(conn, cls, "Unit 3 quiz (quadratics)", "2026-11-11", "assessment")
        _event(conn, cls, "Unit 3 warm-up quiz", "2026-10-20", "assessment")        # past
        _event(conn, cls, "Unit 4 quiz", "2026-11-05", "assessment", "removed")      # taken off the calendar
        _event(conn, cls, "Unit 2 test", "2026-11-04", "assessment", "proposed")
        _event(conn, cls, "Unit 8 quiz", "2026-11-03", "assessment")                 # tomorrow
        _event(conn, cls, "Unit 7 review day", "2026-11-12")                         # not an assessment
        _package(conn, cls, units[6], {"title": "Unit 6 check-in", "lesson_date": "2026-11-20"})
        _package(conn, cls, units[3], {"title": "Rejected one"}, status="rejected")
    _checkin(cls, units[5], "2099-01-02", "2099-01-01T23:59:00.000Z")   # still open
    _checkin(cls, units[2], "2026-10-02", "2026-10-01T23:59:00.000Z")   # closed: Unit 2 can have another

    body = _get(client, SUGGEST, class_id=cls)
    assert set(body) == {"suggestions", "skipped"}
    assert body["suggestions"] == [
        {"unit": units[2], "lesson_date": "2026-11-03", "due_day": "2026-11-02",
         "reason": "1 school day before Unit 2 test on Wed, Nov 4 (there isn't time for 2), "
                   "so the check-in feeds the last lesson before it.",
         "anchor": {"title": "Unit 2 test", "date": "2026-11-04", "kind": "assessment", "source": "calendar"}},
        {"unit": units[3], "lesson_date": "2026-11-09", "due_day": "2026-11-08",
         "reason": "2 school days before Unit 3 quiz (quadratics) on Wed, Nov 11, so the check-in feeds the review lesson.",
         "anchor": {"title": "Unit 3 quiz (quadratics)", "date": "2026-11-11", "kind": "assessment",
                    "source": "calendar"}},
        {"unit": units[4], "lesson_date": "2026-11-23", "due_day": "2026-11-22",
         "reason": "2 school days before Unit 4 Test on Mon, Nov 30, so the check-in feeds the review lesson.",
         "anchor": {"title": "Unit 4 Test", "date": "2026-11-30", "kind": "assessment",
                    "source": "Algebra II calendar"}},
    ]
    skipped = {s["unit"]: s["reason"] for s in body["skipped"]}
    assert list(skipped) == [units[5], units[6], units[7], units[8]]
    assert "isn't closed" in skipped[units[5]] and "Unit 5 check-in" in skipped[units[5]]
    assert "waiting for approval" in skipped[units[6]]
    assert skipped[units[7]] == "No upcoming quiz or test found for this unit. Pick a lesson day yourself."
    assert skipped[units[8]].startswith("Unit 8 quiz on Tue, Nov 3 is too soon")


def test_suggestions_with_an_empty_library(client, cls):
    assert _get(client, SUGGEST, class_id=cls) == {"suggestions": [], "skipped": []}
