"""The shared check-in rules (app/shared/checkin.py) and student auth (app/shared/student_auth.py)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.shared import checkin as ck
from app.shared.db import connect
from app.shared.student_auth import (InvalidToken, checkin_for_student, current_student, issue_student_token,
                                     verify_student_token)
from tests.checkin_fixtures import ENROLLED, NOT_ENROLLED, make_checkin


def test_student_token_round_trip_and_tampering():
    token = issue_student_token(7)
    assert verify_student_token(token) == 7
    head, body, sig = token.split(".")
    with pytest.raises(InvalidToken):
        verify_student_token(f"{head}.{body}.{sig[:-2]}AA")
    with pytest.raises(InvalidToken):
        verify_student_token(issue_student_token(7, ttl_seconds=-5))
    with pytest.raises(HTTPException):
        current_student(None)
    assert current_student(f"Bearer {token}") == 7


def test_checkin_access_rules(client):
    c = make_checkin()
    assert checkin_for_student(ENROLLED[0], c.assignment_id)["mode"] == "checkin"
    with pytest.raises(HTTPException) as e:
        checkin_for_student(NOT_ENROLLED, c.assignment_id)
    assert e.value.status_code == 403
    late = make_checkin(due_date="2000-01-01T00:00:00.000Z")
    checkin_for_student(ENROLLED[0], late.assignment_id)  # reading is fine
    with pytest.raises(HTTPException):
        checkin_for_student(ENROLLED[0], late.assignment_id, writing=True)


def test_honest_try_rule():
    assert ck.honest_try("idk") == (False, ck.honest_try("idk")[1])
    assert not ck.honest_try("   ")[0]
    assert not ck.honest_try("the nucleus", previous="The nucleus!")[0]
    assert not ck.honest_try("membrane", min_words=ck.MIN_EXPLAIN_WORDS)[0]
    assert ck.honest_try("it controls what goes in and out", min_words=ck.MIN_EXPLAIN_WORDS)[0]


def test_practice_mastery_points_streaks_and_unlock(client):
    c = make_checkin(threshold=0.5)
    s = ENROLLED[1]
    with connect() as conn:
        stats = ck.practice_stats(conn, s, c.assignment_id)
        assert (stats["total"], stats["mastered"], stats["unlocked"], stats["level"]) == (10, 0, False, 1)
        out = None
        for aid, iid in c.items[:5]:
            out = ck.record_practice_answer(conn, s, c.assignment_id, aid, iid, True)
        assert out["mastered"] == 5 and out["unlocked"] and out["just_unlocked"]
        assert out["streak"] == 5 and out["points_awarded"] == 20, "5 in a row doubles the points"
        miss = ck.record_practice_answer(conn, s, c.assignment_id, *c.items[0], False)
        assert miss["streak"] == 0 and miss["mastered"] == 4, "a miss un-masters the card"
        assert miss["unlocked"] and not miss["just_unlocked"], "but unlocking is permanent"
        assert ck.item_progress(conn, s, c.assignment_id)[f"{c.items[0][0]}:{c.items[0][1]}"]["box"] == 1
        with pytest.raises(ValueError):
            ck.record_practice_answer(conn, s, c.assignment_id, c.activity_ids[0], "nope", True)


def test_checkin_statuses_grade_and_signals(client):
    c = make_checkin()
    s = ENROLLED[2]
    q1, q2 = c.mc_ids
    with connect() as conn:
        assert ck.refresh_grade(conn, s, c.assignment_id) is None, "no grade before any answer"
        ck.record_first_answer(conn, s, c.assignment_id, q1, "Mitochondria", True)
        ck.record_first_answer(conn, s, c.assignment_id, q2, "Nucleus", False)
        with pytest.raises(ValueError):
            ck.record_first_answer(conn, s, c.assignment_id, q2, "again", True)
        ck.record_tutor_turn(conn, s, c.assignment_id, q2, "hint")
        ck.record_fix_attempt(conn, s, c.assignment_id, q2, "it is the nucleus maybe", False, "Think about the boundary.")
        st = ck.record_fix_attempt(conn, s, c.assignment_id, q2, "the membrane lets things in and out", True)
        assert st["status"] == "fixed" and st["tries"] == 2
        grade = dict(conn.execute("SELECT * FROM student_grades WHERE student_id = ? AND assignment_id = ?",
                                  (s, c.assignment_id)).fetchone())
        assert round(grade["percentage"], 1) == 66.7 and grade["letter_grade"] == "Incomplete"
        ck.record_first_answer(conn, s, c.assignment_id, c.explain_id, "it keeps the inside stable", True)
        sig = ck.learning_signals(conn, s, c.assignment_id)
        assert sig["complete"] and sig["first_try_accuracy"] == 66.7 and sig["fixed_with_help"] == 100.0
        assert sig["understanding"] == round(100 * (2 + 0.5) / 3, 1)
        grade = conn.execute("SELECT points_earned, letter_grade, ai_dependency_score FROM student_grades "
                             "WHERE student_id = ? AND assignment_id = ?", (s, c.assignment_id)).fetchone()
        assert tuple(grade) == (10.0, "Complete", None), "full credit for completing, whatever the first tries were"
        # The weekly row averages every check-in this student has this week (other tests may add some).
        want = conn.execute("""SELECT AVG(sg.first_try_accuracy), AVG(sg.fixed_with_help) FROM student_grades sg
                               JOIN assignments a ON a.assignment_id = sg.assignment_id
                               WHERE sg.student_id = ? AND a.class_id = 3""", (s,)).fetchone()
        week = conn.execute("SELECT first_try_accuracy, fixed_with_help FROM student_metrics WHERE student_id = ? "
                            "AND class_id = 3", (s,)).fetchone()
        assert (week["first_try_accuracy"], week["fixed_with_help"]) == tuple(want)


def test_reveal_only_after_honest_tries_in_that_mode(client):
    a = {"tutor_mode": "answer_after_tries", "tutor_reveal_after": 2}
    assert not ck.may_reveal(a, {"status": "needs_fix", "tries": 1})
    assert ck.may_reveal(a, {"status": "needs_fix", "tries": 2})
    assert not ck.may_reveal({**a, "tutor_mode": "hints_only"}, {"status": "needs_fix", "tries": 9})
