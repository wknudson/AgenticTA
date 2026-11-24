"""GET /agents/misconceptions/checkins?overview=true: per check-in stage counts (active students
only, same rules as the briefing), live/due_soon/closed status, the class's drafts still waiting
for approval, and the per-student view (&student_id) the Metrics tab links from."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.misconceptions import briefing
from app.shared import checkin as ck
from app.shared.db import connect
from tests.checkin_fixtures import BIO, NOT_ENROLLED, make_checkin

BOB, DAVID, EMMA, GRACE, HENRY = 2, 4, 5, 7, 8   # Emma is not in Biology (class 3); the rest are
URL = "/agents/misconceptions/checkins"
_created: list[int] = []


def _new_checkin(**kwargs):
    c = make_checkin(**kwargs)
    _created.append(c.assignment_id)
    return c


@pytest.fixture(autouse=True)
def _drop_test_grades():
    """Answers write completion grades + weekly metrics; take them back out afterwards (same as
    test_briefing) so other files that check a student's weekly averages don't see them."""
    yield
    if not _created:
        return
    marks = ",".join("?" * len(_created))
    with connect() as conn:
        rows = conn.execute(f"""SELECT DISTINCT g.student_id, a.class_id FROM student_grades g
                                JOIN assignments a ON a.assignment_id = g.assignment_id
                                WHERE g.assignment_id IN ({marks})""", _created).fetchall()
        conn.execute(f"DELETE FROM student_grades WHERE assignment_id IN ({marks})", _created)
        for r in rows:
            conn.execute(ck.WEEKLY_METRICS_SQL, {"student_id": r["student_id"], "class_id": r["class_id"]})
    _created.clear()


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _overview(client, class_id=BIO, **params):
    r = client.get(URL, params={"class_id": class_id, "overview": True, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _row(body, assignment_id):
    return next(x for x in body["checkins"] if x["assignment_id"] == assignment_id)


def _progress(c):
    """Grace: nothing. David: practicing. Bob: check-in started. Henry: complete. (Grace never
    gets a grade here: test_checkin_shared checks her weekly metrics.)"""
    mc1, mc2 = c.mc_ids
    with connect() as conn:
        for (aid, iid), correct in ((c.items[0], False), (c.items[1], True)):
            ck.record_practice_answer(conn, DAVID, c.assignment_id, aid, iid, correct)
        for aid, iid in c.items:
            ck.record_practice_answer(conn, BOB, c.assignment_id, aid, iid, True)
            ck.record_practice_answer(conn, HENRY, c.assignment_id, aid, iid, True)
        ck.record_first_answer(conn, BOB, c.assignment_id, mc1, "Ribosome", False)
        ck.record_first_answer(conn, HENRY, c.assignment_id, mc1, "Ribosome", False)
        ck.record_tutor_turn(conn, HENRY, c.assignment_id, mc1, "explained")
        ck.record_fix_attempt(conn, HENRY, c.assignment_id, mc1, "Mitochondria turn food into ATP for the cell", True)
        ck.record_first_answer(conn, HENRY, c.assignment_id, mc2, "Cell membrane", True)
        ck.record_first_answer(conn, HENRY, c.assignment_id, c.explain_id, "It controls what goes in and out", True)
        # Progress that must never count: a student from another class, and one whose Biology
        # enrollment is inactive (written straight to the tables, so no grades are created).
        conn.execute("INSERT OR IGNORE INTO student_classes (student_id, class_id, status) VALUES (?, ?, 'inactive')",
                     (EMMA, BIO))
        for sid in (NOT_ENROLLED, EMMA):
            conn.execute("INSERT INTO game_scores (student_id, assignment_id, points) VALUES (?, ?, 5)",
                         (sid, c.assignment_id))
            conn.execute("""INSERT INTO checkin_item_status (student_id, assignment_id, question_id, status, first_correct)
                            VALUES (?, ?, ?, 'correct', 1)""", (sid, c.assignment_id, mc1))


def _drop_inactive_enrollment():
    with connect() as conn:
        conn.execute("DELETE FROM student_classes WHERE student_id = ? AND class_id = ? AND status = 'inactive'",
                     (EMMA, BIO))


def test_counts_match_the_briefing_and_skip_other_students(client):
    c = _new_checkin()
    try:
        _progress(c)
        row = _row(_overview(client), c.assignment_id)
        assert row["counts"] == {"total": 4, "not_started": 1, "practicing": 1, "checkin": 1, "complete": 1}
        b = client.get("/agents/misconceptions/briefing", params={"class_id": BIO, "assignment_id": c.assignment_id})
        assert row["counts"] == b.json()["counts"], "same rules as the briefing's roster"
        # The original fields are all still there, unchanged.
        assert {k: row[k] for k in ("title", "unit", "lesson_date", "due_date")} == {
            "title": "Unit 2 check-in", "unit": "Unit 2: Cell Structure", "lesson_date": "2099-01-02",
            "due_date": "2099-01-01T23:59:00.000Z"}
        assert row["status"] == "live"

        # A brand-new check-in: everyone is "not started".
        fresh = _new_checkin()
        assert _row(_overview(client), fresh.assignment_id)["counts"] == {
            "total": 4, "not_started": 4, "practicing": 0, "checkin": 0, "complete": 0}
    finally:
        _drop_inactive_enrollment()


def test_status_buckets(client):
    now = datetime.now(timezone.utc)
    closed = _new_checkin(due_date=_iso(now - timedelta(days=1)))
    soon = _new_checkin(due_date=_iso(now + timedelta(hours=2)))
    later = _new_checkin(due_date=_iso(now + timedelta(days=3)))
    undated = _new_checkin(due_date=None)
    body = _overview(client)
    assert {aid: _row(body, aid)["status"] for aid in (closed.assignment_id, soon.assignment_id,
                                                       later.assignment_id, undated.assignment_id)} == {
        closed.assignment_id: "closed", soon.assignment_id: "due_soon",
        later.assignment_id: "live", undated.assignment_id: "live"}


def test_checkin_status_edges():
    now = datetime(2030, 5, 6, 12, 0, tzinfo=timezone.utc)
    s = briefing.checkin_status
    assert s("2030-05-07T12:00:00.000Z", now) == "due_soon", "exactly 24 hours away counts as due soon"
    assert s("2030-05-07T12:00:01Z", now) == "live"
    assert s("2030-05-06T11:59:59Z", now) == "closed"
    assert s("2030-05-06T12:00:00", now) == "due_soon", "no time zone = UTC; not past yet"
    assert s("2030-05-06T14:00:00+02:00", now) == "due_soon"
    assert s(None, now) == s("", now) == s("next week", now) == "live"


def test_drafts_list_only_this_classes_drafts(client):
    settings = {"title": "Unit 5 check-in", "lesson_date": "2099-03-04", "due_date": "2099-03-03T23:59:00.000Z",
                "tutor_mode": "hints_only"}
    ids: dict[str, int] = {}
    with connect() as conn:
        def add(key, class_id, status, unit="Unit 5: Genetics", s=settings, created="2099-02-01T10:00:00.000Z"):
            ids[key] = conn.execute(
                "INSERT INTO unit_packages (class_id, unit, settings_json, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (class_id, unit, json.dumps(s), status, created)).lastrowid
        add("draft", BIO, "draft")
        add("untitled", BIO, "draft", unit="Unit 6: Evolution", s={"lesson_date": "2099-04-01"},
            created="2099-02-02T10:00:00.000Z")
        add("published", BIO, "published")
        add("rejected", BIO, "rejected")
        add("other_class", 1, "draft")
    try:
        drafts = _overview(client)["drafts"]
        listed = [d["package_id"] for d in drafts]
        assert ids["draft"] in listed and ids["untitled"] in listed
        assert listed.index(ids["untitled"]) < listed.index(ids["draft"]), "newest first"
        for key in ("published", "rejected", "other_class"):
            assert ids[key] not in listed, key
        mine = next(d for d in drafts if d["package_id"] == ids["draft"])
        assert mine == {"package_id": ids["draft"], "unit": "Unit 5: Genetics", "title": "Unit 5 check-in",
                        "lesson_date": "2099-03-04", "due_date": "2099-03-03T23:59:00.000Z",
                        "created_at": "2099-02-01T10:00:00.000Z"}
        untitled = next(d for d in drafts if d["package_id"] == ids["untitled"])
        assert untitled["title"] == "Unit 6: Evolution check-in" and untitled["due_date"] is None
        with connect() as conn:   # whatever else is listed is also one of class 3's drafts
            marks = ",".join("?" * len(listed))
            assert {(r["class_id"], r["status"]) for r in conn.execute(
                f"SELECT class_id, status FROM unit_packages WHERE package_id IN ({marks})", listed)} == {(BIO, "draft")}
        assert ids["other_class"] in [d["package_id"] for d in _overview(client, class_id=1)["drafts"]]
    finally:
        with connect() as conn:
            conn.execute(f"DELETE FROM unit_packages WHERE package_id IN ({','.join('?' * len(ids))})", list(ids.values()))


def test_other_classes_excluded_and_default_shape_unchanged(client):
    bio = _new_checkin()
    algebra = _new_checkin(class_id=1)
    body = _overview(client)
    assert all(x["assignment_id"] != algebra.assignment_id for x in body["checkins"])
    other = _overview(client, class_id=1)
    assert all(x["assignment_id"] != bio.assignment_id for x in other["checkins"])
    assert _row(other, algebra.assignment_id)["counts"]["total"] == 4, "class 1's own active roster"

    plain = client.get(URL, params={"class_id": BIO}).json()
    assert "drafts" not in plain
    assert set(_row(plain, bio.assignment_id)) == {"assignment_id", "title", "unit", "lesson_date", "due_date"}


def test_one_students_checkins(client):
    c = _new_checkin()
    try:
        _progress(c)
        henry = _row(client.get(URL, params={"class_id": BIO, "student_id": HENRY}).json(), c.assignment_id)["student"]
        assert henry["stage"] == "complete" and (henry["resolved"], henry["total"]) == (3, 3)
        assert henry["first_try_accuracy"] == pytest.approx(66.7) and henry["fixed_with_help"] == 100.0
        grace = _row(client.get(URL, params={"class_id": BIO, "student_id": GRACE}).json(), c.assignment_id)["student"]
        assert grace["stage"] == "not_started" and grace["answered"] == 0 and grace["first_try_accuracy"] is None
        roster = {s["student_id"]: s["stage"] for s in client.get(
            "/agents/misconceptions/briefing", params={"class_id": BIO, "assignment_id": c.assignment_id}).json()["roster"]}
        for sid in (BOB, DAVID):
            got = _row(client.get(URL, params={"class_id": BIO, "student_id": sid}).json(), c.assignment_id)
            assert got["student"]["stage"] == roster[sid]
        # Not in the class, or no longer active in it: 404, nothing about them comes back.
        assert client.get(URL, params={"class_id": BIO, "student_id": NOT_ENROLLED}).status_code == 404
        assert client.get(URL, params={"class_id": BIO, "student_id": EMMA}).status_code == 404
        both = _row(_overview(client, student_id=HENRY), c.assignment_id)
        assert both["student"]["stage"] == "complete" and both["counts"]["complete"] == 1
    finally:
        _drop_inactive_enrollment()
