"""Flipped-classroom check-ins: the shared rules (docs/flipped-classroom-plan.md).

Games (practice), the tutor (check-in) and the briefing all read and write student progress
through this module, so the rules live in one place:

- **Practice:** mastery, points, streaks, levels and missed-card replay. All deterministic,
  no model calls.
- **Check-in:** question statuses (unanswered -> correct | needs_fix -> fixed) and the
  "honest try" rule.
- **Learning signals** (replacing the AI Dependency score), the completion grade, and the
  weekly metrics row.

Every function takes an open connection, so callers decide the transaction.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from typing import Any

from .db import now_iso

# ---- Practice -----------------------------------------------------------------------------

POINTS_PER_CORRECT = 10
LEVELS = 5            # level 1 at 0% mastery ... level 5 at 100%
MAX_BOX = 3           # Leitner boxes: a miss goes back to box 1, box 3 = solid
REPLAY_GAP = {1: 3, 2: 8, 3: 20}  # cards until an item in that box comes back (the player uses this)


def streak_multiplier(streak: int) -> int:
    return 3 if streak >= 10 else 2 if streak >= 5 else 1


def published_items(conn: sqlite3.Connection, assignment_id: int) -> list[tuple[int, dict]]:
    """(activity_id, item) for every item in the check-in's published games."""
    out = []
    for row in conn.execute("SELECT activity_id, items_json FROM study_activities "
                            "WHERE assignment_id = ? AND status = 'published' ORDER BY activity_id",
                            (assignment_id,)):
        for item in json.loads(row["items_json"] or "[]"):
            if item.get("item_id"):
                out.append((row["activity_id"], item))
    return out


def practice_stats(conn: sqlite3.Connection, student_id: int, assignment_id: int) -> dict[str, Any]:
    a = conn.execute("SELECT mastery_threshold FROM assignments WHERE assignment_id = ?", (assignment_id,)).fetchone()
    threshold = float(a["mastery_threshold"]) if a else 0.8
    keys = {(aid, item["item_id"]) for aid, item in published_items(conn, assignment_id)}
    mastered = 0
    if keys:
        marks = ",".join("?" * len({aid for aid, _ in keys}))
        for r in conn.execute(f"SELECT activity_id, item_id FROM game_item_progress WHERE student_id = ? "
                              f"AND last_correct = 1 AND activity_id IN ({marks})",
                              [student_id, *{aid for aid, _ in keys}]):
            mastered += (r["activity_id"], r["item_id"]) in keys
    total = len(keys)
    mastery = mastered / total if total else 1.0
    score = conn.execute("SELECT * FROM game_scores WHERE student_id = ? AND assignment_id = ?",
                         (student_id, assignment_id)).fetchone()
    # Unlocking is permanent: a practice miss after unlocking (which un-masters a card) must not
    # lock a student out of a check-in they've started.
    reached = total == 0 or mastery >= threshold - 1e-9
    started_checkin = conn.execute(
        "SELECT 1 FROM checkin_item_status WHERE student_id = ? AND assignment_id = ? AND status != 'unanswered' LIMIT 1",
        (student_id, assignment_id)).fetchone() is not None
    return {
        "mastered": mastered, "total": total, "mastery": round(mastery, 4), "threshold": threshold,
        "unlocked": reached or bool(score and score["unlocked_at"]) or started_checkin,
        "level": 1 + min(LEVELS - 1, math.floor(mastery * (LEVELS - 1) + 1e-9)), "levels": LEVELS,
        "points": score["points"] if score else 0,
        "streak": score["current_streak"] if score else 0,
        "best_streak": score["best_streak"] if score else 0,
        "answers": score["answers"] if score else 0,
        "started": bool(score),
    }


def record_practice_answer(conn: sqlite3.Connection, student_id: int, assignment_id: int,
                           activity_id: int, item_id: str, correct: bool) -> dict[str, Any]:
    """Save one game answer. Returns the new stats plus what this answer earned."""
    if not any(aid == activity_id and item["item_id"] == item_id for aid, item in published_items(conn, assignment_id)):
        raise ValueError("That card isn't part of this check-in's games.")
    before = practice_stats(conn, student_id, assignment_id)
    conn.execute(
        """INSERT INTO game_item_progress (student_id, activity_id, item_id, times_seen, times_correct, last_correct, box)
           VALUES (?, ?, ?, 1, ?, ?, ?)
           ON CONFLICT (student_id, activity_id, item_id) DO UPDATE SET
             times_seen = times_seen + 1, times_correct = times_correct + excluded.times_correct,
             last_correct = excluded.last_correct,
             box = CASE WHEN excluded.last_correct = 1 THEN MIN(box + 1, ?) ELSE 1 END,
             updated_at = ?""",
        (student_id, activity_id, item_id, int(correct), int(correct), 2 if correct else 1, MAX_BOX, now_iso()))
    streak = (before["streak"] + 1) if correct else 0
    awarded = POINTS_PER_CORRECT * streak_multiplier(streak) if correct else 0
    conn.execute(
        """INSERT INTO game_scores (student_id, assignment_id, points, current_streak, best_streak, answers)
           VALUES (?, ?, ?, ?, ?, 1)
           ON CONFLICT (student_id, assignment_id) DO UPDATE SET
             points = points + excluded.points, current_streak = excluded.current_streak,
             best_streak = MAX(best_streak, excluded.current_streak), answers = answers + 1, updated_at = ?""",
        (student_id, assignment_id, awarded, streak, streak, now_iso()))
    after = practice_stats(conn, student_id, assignment_id)
    if after["unlocked"]:
        conn.execute("UPDATE game_scores SET unlocked_at = COALESCE(unlocked_at, ?) WHERE student_id = ? AND assignment_id = ?",
                     (now_iso(), student_id, assignment_id))
    refresh_grade(conn, student_id, assignment_id)
    return {**after, "points_awarded": awarded, "multiplier": streak_multiplier(streak) if correct else 1,
            "level_up": after["level"] > before["level"],
            "just_unlocked": after["unlocked"] and not before["unlocked"]}


def item_progress(conn: sqlite3.Connection, student_id: int, assignment_id: int) -> dict[str, dict]:
    """'<activity_id>:<item_id>' -> progress row, for the practice player."""
    rows = conn.execute(
        "SELECT p.* FROM game_item_progress p JOIN study_activities s ON s.activity_id = p.activity_id "
        "WHERE p.student_id = ? AND s.assignment_id = ?", (student_id, assignment_id))
    return {f"{r['activity_id']}:{r['item_id']}": {k: r[k] for k in ("times_seen", "times_correct", "last_correct", "box")}
            for r in rows}


# ---- Check-in -----------------------------------------------------------------------------

FILLER = {"idk", "i dont know", "i don't know", "dont know", "don't know", "no idea", "dunno", "?", "??",
          "nothing", "n/a", "na", "pass", "skip", "none", "no", "yes", "ok", "okay", "help", "."}
MIN_EXPLAIN_WORDS = 4
HELP_ORDER = {"none": 0, "hint": 1, "explained": 2}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", (text or "").lower())).strip()


def honest_try(text: str | None, *, previous: str | None = None, min_words: int = 1) -> tuple[bool, str | None]:
    """Is this a real attempt? (ok, reason-if-not). Cheap and deterministic, so the judge only
    runs on real attempts and a miss can't be fixed by mashing the same answer."""
    t = _norm(text or "")
    if not t:
        return False, "Write something first."
    if t in FILLER:
        return False, "Give it a real try in your own words. A guess is fine, \"idk\" isn't."
    if previous is not None and t == _norm(previous):
        return False, "That's the same as your last try. What would you change?"
    if len(t.split()) < min_words:
        return False, f"Explain it in a full sentence (at least {min_words} words)."
    return True, None


def ensure_status_rows(conn: sqlite3.Connection, student_id: int, assignment_id: int) -> None:
    conn.execute("""INSERT OR IGNORE INTO checkin_item_status (student_id, assignment_id, question_id)
                    SELECT ?, ?, question_id FROM assignment_questions WHERE assignment_id = ?""",
                 (student_id, assignment_id, assignment_id))


def status_rows(conn: sqlite3.Connection, student_id: int, assignment_id: int) -> list[dict]:
    ensure_status_rows(conn, student_id, assignment_id)
    return [dict(r) for r in conn.execute(
        """SELECT s.*, q.sort_order FROM checkin_item_status s
           JOIN assignment_questions q ON q.question_id = s.question_id
           WHERE s.student_id = ? AND s.assignment_id = ? ORDER BY q.sort_order, q.question_id""",
        (student_id, assignment_id))]


def get_status(conn: sqlite3.Connection, student_id: int, assignment_id: int, question_id: int) -> dict:
    ensure_status_rows(conn, student_id, assignment_id)
    row = conn.execute("SELECT * FROM checkin_item_status WHERE student_id = ? AND assignment_id = ? AND question_id = ?",
                       (student_id, assignment_id, question_id)).fetchone()
    if row is None:
        raise ValueError("That question isn't part of this check-in.")
    return dict(row)


def record_first_answer(conn: sqlite3.Connection, student_id: int, assignment_id: int, question_id: int,
                        answer: str, correct: bool) -> dict:
    """First answer to a question: correct, or needs_fix (then the tutor opens)."""
    st = get_status(conn, student_id, assignment_id, question_id)
    if st["status"] != "unanswered":
        raise ValueError("You've already answered this one.")
    conn.execute("""UPDATE checkin_item_status SET status = ?, first_answer = ?, first_correct = ?,
                    resolved_at = ?, updated_at = ? WHERE student_id = ? AND assignment_id = ? AND question_id = ?""",
                 ("correct" if correct else "needs_fix", answer, int(correct), now_iso() if correct else None, now_iso(),
                  student_id, assignment_id, question_id))
    refresh_grade(conn, student_id, assignment_id)
    return get_status(conn, student_id, assignment_id, question_id)


def record_fix_attempt(conn: sqlite3.Connection, student_id: int, assignment_id: int, question_id: int,
                       explanation: str, accepted: bool, feedback: str | None = None) -> dict:
    """An honest attempt to fix a missed question. Accepted -> fixed."""
    st = get_status(conn, student_id, assignment_id, question_id)
    if st["status"] != "needs_fix":
        raise ValueError("This question doesn't need fixing.")
    conn.execute("""UPDATE checkin_item_status SET tries = tries + 1, status = ?, explain_back = ?, last_feedback = ?,
                    resolved_at = ?, updated_at = ? WHERE student_id = ? AND assignment_id = ? AND question_id = ?""",
                 ("fixed" if accepted else "needs_fix", explanation, None if accepted else feedback,
                  now_iso() if accepted else None, now_iso(), student_id, assignment_id, question_id))
    refresh_grade(conn, student_id, assignment_id)
    return get_status(conn, student_id, assignment_id, question_id)


def record_tutor_turn(conn: sqlite3.Connection, student_id: int, assignment_id: int, question_id: int,
                      help_level: str = "hint") -> None:
    """A student message to the tutor. help_level only ever goes up (none < hint < explained)."""
    st = get_status(conn, student_id, assignment_id, question_id)
    level = max(st["help_level"], help_level, key=lambda h: HELP_ORDER.get(h, 0))
    conn.execute("""UPDATE checkin_item_status SET tutor_turns = tutor_turns + 1, help_level = ?, updated_at = ?
                    WHERE student_id = ? AND assignment_id = ? AND question_id = ?""",
                 (level, now_iso(), student_id, assignment_id, question_id))


def may_reveal(assignment: dict, status: dict) -> bool:
    """answer_after_tries mode: the tutor may walk through the answer after N honest tries."""
    return (assignment.get("tutor_mode") == "answer_after_tries"
            and status["status"] == "needs_fix" and status["tries"] >= int(assignment.get("tutor_reveal_after") or 2))


def save_chat(conn: sqlite3.Connection, student_id: int, assignment_id: int, question_id: int,
              role: str, content: str) -> None:
    """Check-in tutor transcripts are kept (the briefing and misconception finder read them)."""
    conn.execute("INSERT INTO student_chat_messages (student_id, assignment_id, attempt_number, role, content, question_id) "
                 "VALUES (?, ?, 1, ?, ?, ?)", (student_id, assignment_id, role, content, question_id))


def chat_history(conn: sqlite3.Connection, student_id: int, assignment_id: int, question_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT role, content, created_at FROM student_chat_messages WHERE student_id = ? AND assignment_id = ? "
        "AND question_id = ? ORDER BY chat_message_id", (student_id, assignment_id, question_id))]


# ---- Learning signals, grade, weekly metrics -----------------------------------------------

def learning_signals(conn: sqlite3.Connection, student_id: int, assignment_id: int) -> dict[str, Any]:
    """What the teacher sees instead of an AI Dependency score. All percentages 0-100."""
    rows = status_rows(conn, student_id, assignment_id)
    total = len(rows)
    answered = [r for r in rows if r["status"] != "unanswered"]
    first_right = sum(1 for r in answered if r["first_correct"])
    misses = [r for r in answered if not r["first_correct"]]
    fixed = [r for r in misses if r["status"] == "fixed"]
    fixed_on_own = [r for r in fixed if r["help_level"] != "explained"]
    resolved = first_right + len(fixed)
    practice = practice_stats(conn, student_id, assignment_id)
    pct = lambda n, d: round(100.0 * n / d, 1) if d else None  # noqa: E731
    return {
        "total": total, "answered": len(answered), "resolved": resolved,
        "complete": total > 0 and resolved == total,
        "completion": pct(resolved, total) or 0.0,
        "practice_mastery": round(100.0 * practice["mastery"], 1),
        "first_try_accuracy": pct(first_right, len(answered)),
        "fixed_with_help": pct(len(fixed), len(misses)),       # None = nothing to fix
        "understanding": pct(first_right + 0.5 * len(fixed_on_own), total),
        "help": {h: sum(1 for r in rows if r["help_level"] == h) for h in HELP_ORDER},
        "still_shaky": [r["question_id"] for r in rows
                        if r["status"] == "needs_fix" or (r["status"] == "fixed" and r["help_level"] == "explained")],
    }


WEEKLY_METRICS_SQL = """
INSERT INTO student_metrics (student_id, class_id, week_number, week_start_date, week_end_date,
    accuracy_score, understanding_score, ai_dependency_score, engagement_score,
    practice_score, first_try_accuracy, fixed_with_help)
SELECT :student_id, :class_id, CAST(strftime('%V', 'now') AS INTEGER),
       date('now', 'weekday 0', '-6 days'), date('now', 'weekday 0'),
       AVG(COALESCE(sg.first_try_accuracy, sg.percentage)),
       AVG(COALESCE(sg.understanding_score, sg.percentage)),
       AVG(sg.ai_dependency_score),
       AVG(COALESCE(sg.engagement_score, sg.percentage)),
       AVG(sg.practice_mastery), AVG(sg.first_try_accuracy), AVG(sg.fixed_with_help)
FROM student_grades sg JOIN assignments a ON a.assignment_id = sg.assignment_id
WHERE sg.student_id = :student_id AND a.class_id = :class_id
  AND sg.submission_date >= date('now', 'weekday 0', '-6 days')
  AND sg.submission_date < date('now', 'weekday 0', '+1 days')
ON CONFLICT (student_id, class_id, week_number) DO UPDATE SET
  week_start_date = excluded.week_start_date, week_end_date = excluded.week_end_date,
  accuracy_score = excluded.accuracy_score, understanding_score = excluded.understanding_score,
  ai_dependency_score = excluded.ai_dependency_score, engagement_score = excluded.engagement_score,
  practice_score = excluded.practice_score, first_try_accuracy = excluded.first_try_accuracy,
  fixed_with_help = excluded.fixed_with_help
"""  # Same formula as upsertWeeklyMetrics in backend/routes/student.ts; keep them in sync.


def refresh_grade(conn: sqlite3.Connection, student_id: int, assignment_id: int) -> dict | None:
    """Completion grade: points = max_points x resolved / total. Written once the student has
    answered at least one question, then kept current, so a missed due date means partial credit."""
    a = conn.execute("SELECT class_id, max_points, mode FROM assignments WHERE assignment_id = ?", (assignment_id,)).fetchone()
    if a is None or a["mode"] != "checkin":
        return None
    sig = learning_signals(conn, student_id, assignment_id)
    if sig["answered"] == 0:
        return None
    points = round(float(a["max_points"]) * sig["completion"] / 100.0, 2)
    now = now_iso()
    conn.execute(
        """INSERT INTO student_grades (student_id, assignment_id, points_earned, percentage, letter_grade,
               submission_date, graded_date, understanding_score, ai_dependency_score, engagement_score,
               submission_attempts, practice_mastery, first_try_accuracy, fixed_with_help)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, ?, ?)
           ON CONFLICT (student_id, assignment_id) DO UPDATE SET
             points_earned = excluded.points_earned, percentage = excluded.percentage,
             letter_grade = excluded.letter_grade, submission_date = excluded.submission_date,
             graded_date = excluded.graded_date, understanding_score = excluded.understanding_score,
             ai_dependency_score = NULL, engagement_score = excluded.engagement_score, submission_attempts = 1,
             practice_mastery = excluded.practice_mastery, first_try_accuracy = excluded.first_try_accuracy,
             fixed_with_help = excluded.fixed_with_help""",
        (student_id, assignment_id, points, sig["completion"], "Complete" if sig["complete"] else "Incomplete",
         now, now, sig["understanding"], sig["practice_mastery"], sig["practice_mastery"],
         sig["first_try_accuracy"], sig["fixed_with_help"]))
    conn.execute(WEEKLY_METRICS_SQL, {"student_id": student_id, "class_id": a["class_id"]})
    return sig
