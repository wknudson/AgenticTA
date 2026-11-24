"""Teacher settings for a published check-in (the "Edit" form on the teacher's check-in page).

    GET   /agents/tutor/checkin/{assignment_id}/settings
    PATCH /agents/tutor/checkin/{assignment_id}/settings
          {title?, lesson_date?, due_date?, due_day?, tutor_mode?, tutor_reveal_after?, mastery_threshold?}

Every field is optional; only what is sent changes. `due_date` is an ISO instant (stored in UTC
like Express does) and `due_day` is the teacher's own calendar day for it (11:59 PM in Utah is
already tomorrow in UTC), the same convention as POST /agents/games/unit-package.

When the due date moves, the check-in's calendar entry (calendar_events, kind 'assignment_due')
moves with it if the new day passes the scheduler's rules, and is left where it was otherwise,
with a `calendar_note` saying why. The rules are re-checked here with SQL on the shared tables
(agents don't import each other; same checks as scheduler/calendar.py and games/package.py).

Unlocking the check-in is permanent (app/shared/checkin.py), so changing the threshold never
locks out a student who already unlocked it; the response notes say so.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.shared.db import connect

TUTOR_MODES = ("hints_only", "answer_after_tries")
MAX_TITLE = 200
REVEAL_RANGE = (1, 10)
THRESHOLD_RANGE = (0.1, 1.0)


class SettingsPatch(BaseModel):
    title: str | None = None
    lesson_date: str | None = None       # YYYY-MM-DD
    due_date: str | None = None          # ISO date-time (or YYYY-MM-DD = 23:59 UTC)
    due_day: str | None = None           # YYYY-MM-DD, the teacher's local day of due_date
    tutor_mode: str | None = None        # hints_only | answer_after_tries
    tutor_reveal_after: int | None = None
    mastery_threshold: float | None = None  # 0.1-1, or 10-100 as a percent


class SettingsError(ValueError):
    """A value the teacher has to fix (the router answers 422 with this message)."""


# ---------------------------------------------------------------- parsing
def _day(value: str, what: str) -> date:
    raw = (value or "").strip()
    try:
        day = date.fromisoformat(raw)
        if day.isoformat() != raw:  # fromisoformat also takes 20261203; we don't
            raise ValueError
    except ValueError:
        raise SettingsError(f"{what} must be a date like 2026-12-03.") from None
    return day


def _due_iso(value: str) -> str:
    """Express-style UTC timestamp, e.g. 2026-12-03T06:59:00.000Z. A bare day means 23:59 UTC."""
    raw = (value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return f"{_day(raw, 'The due date').isoformat()}T23:59:00.000Z"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise SettingsError("The due date must be a date and time like 2026-12-03T06:59:00.000Z.") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _instant(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        parsed = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _past(iso: str | None) -> bool:
    due = _instant(iso)
    return due is not None and datetime.now(timezone.utc) > due


def _threshold(value: float) -> float:
    share = value / 100 if value > 1 else value  # 80 -> 0.8
    lo, hi = THRESHOLD_RANGE
    if not lo - 1e-9 <= share <= hi + 1e-9:
        raise SettingsError("The unlock threshold must be between 10% and 100% (0.1-1).")
    return round(share, 4)


def _pct(share: float) -> str:
    return f"{round(100 * share)}%"


def _nice_day(day: date) -> str:
    return f"{day:%a}, {day:%b} {day.day}"


# ---------------------------------------------------------------- scheduler rules (by SQL)
def _term(conn: sqlite3.Connection, class_id: int) -> sqlite3.Row | None:
    try:
        return conn.execute("SELECT * FROM term_calendar WHERE class_id = ?", (class_id,)).fetchone()
    except sqlite3.OperationalError:  # scheduler tables not created yet
        return None


def school_day_problem(conn: sqlite3.Connection, class_id: int, day: date) -> str | None:
    """Why `day` isn't a school day for this class (weekend, outside the term, holiday), or None.
    Without a saved term only weekends count."""
    if day.weekday() >= 5:
        return f"{_nice_day(day)} is a weekend"
    term = _term(conn, class_id)
    if term is None:
        return None
    iso = day.isoformat()
    if not term["term_start"] <= iso <= term["term_end"]:
        return f"{_nice_day(day)} is outside the term ({term['term_start']} to {term['term_end']})"
    holidays = {h.get("date"): h.get("label") or "Holiday" for h in json.loads(term["holidays_json"] or "[]")}
    if iso in holidays:
        return f"{_nice_day(day)} is a holiday ({holidays[iso]})"
    return None


def calendar_problem(conn: sqlite3.Connection, class_id: int, day: date, except_event_id: int | None = None) -> str | None:
    """The scheduler's rules for a published due date: a school day, and not over the term's
    per-day limit of assessments and due dates (not counting the event being moved)."""
    problem = school_day_problem(conn, class_id, day)
    if problem or (term := _term(conn, class_id)) is None:
        return problem
    busy = conn.execute(
        "SELECT COUNT(*) FROM calendar_events WHERE class_id = ? AND status = 'published' AND date = ? "
        "AND kind IN ('assessment', 'assignment_due') AND event_id IS NOT ?",
        (class_id, day.isoformat(), except_event_id)).fetchone()[0]
    if busy + 1 > term["max_assessments_per_day"]:
        return (f"{_nice_day(day)} already has {busy} quiz/test or due date(s) "
                f"(the limit is {term['max_assessments_per_day']} a day)")
    return None


# ---------------------------------------------------------------- reads
def _assignment(conn: sqlite3.Connection, assignment_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM assignments WHERE assignment_id = ? AND mode = 'checkin'",
                       (assignment_id,)).fetchone()
    if row is None:
        raise LookupError("Check-in not found")
    return dict(row)


def _due_event(conn: sqlite3.Connection, assignment_id: int) -> dict[str, Any] | None:
    """The check-in's due-date entry on the class calendar (published first, then one waiting
    for approval). Entries the teacher removed don't count."""
    row = conn.execute(
        "SELECT * FROM calendar_events WHERE assignment_id = ? AND kind = 'assignment_due' "
        "AND status IN ('published', 'proposed') ORDER BY status = 'published' DESC, event_id DESC LIMIT 1",
        (assignment_id,)).fetchone()
    return dict(row) if row else None


def _unlocked_students(conn: sqlite3.Connection, assignment_id: int) -> int:
    """Students who already unlocked the check-in (and so keep it whatever the threshold)."""
    return conn.execute(
        """SELECT COUNT(*) FROM (
             SELECT student_id FROM game_scores WHERE assignment_id = ? AND unlocked_at IS NOT NULL
             UNION
             SELECT student_id FROM checkin_item_status WHERE assignment_id = ? AND status != 'unanswered')""",
        (assignment_id, assignment_id)).fetchone()[0]


def _stored_due_day(a: dict[str, Any], event: dict[str, Any] | None) -> date | None:
    """The teacher's day for the stored due date: the calendar entry's day, else the UTC day."""
    if event:
        return date.fromisoformat(event["date"])
    due = _instant(a.get("due_date"))
    return due.astimezone(timezone.utc).date() if due else None


def _settings_out(conn: sqlite3.Connection, a: dict[str, Any]) -> dict[str, Any]:
    event = _due_event(conn, a["assignment_id"])
    due_day = _stored_due_day(a, event)
    return {
        "assignment_id": a["assignment_id"], "class_id": a["class_id"], "title": a["assignment_name"],
        "unit": a.get("unit"), "lesson_date": a.get("lesson_date"), "due_date": a.get("due_date"),
        "due_day": due_day.isoformat() if due_day else None,
        "tutor_mode": a.get("tutor_mode") or "hints_only",
        "tutor_reveal_after": int(a.get("tutor_reveal_after") or 2),
        "mastery_threshold": float(a["mastery_threshold"] if a.get("mastery_threshold") is not None else 0.8),
        "past_due": _past(a.get("due_date")),
        "calendar_event": ({k: event[k] for k in ("event_id", "date", "title", "status")} if event else None),
        "unlocked_students": _unlocked_students(conn, a["assignment_id"]),
    }


def get_settings(assignment_id: int) -> dict[str, Any]:
    with connect() as conn:
        return _settings_out(conn, _assignment(conn, assignment_id))


# ---------------------------------------------------------------- update
def _threshold_note(old: float, new: float, unlocked: int) -> str:
    kept = ("No student has unlocked it yet." if unlocked == 0 else
            f"The {unlocked} student{'s' if unlocked != 1 else ''} who already unlocked it keep{'s' if unlocked == 1 else ''} "
            f"it: unlocking is permanent.")
    if new > old:
        return (f"Unlock threshold raised from {_pct(old)} to {_pct(new)}. It applies to students who haven't "
                f"unlocked the check-in yet. {kept}")
    return (f"Unlock threshold lowered from {_pct(old)} to {_pct(new)}. Students already at {_pct(new)} practice "
            f"mastery can open the check-in now. {kept}")


def update_settings(assignment_id: int, body: SettingsPatch) -> dict[str, Any]:
    sent = body.model_dump(exclude_none=True)
    with connect() as conn:
        # Take the write lock before reading, so two saves at once can't interleave.
        conn.execute("BEGIN IMMEDIATE")
        a = _assignment(conn, assignment_id)
        class_id = a["class_id"]
        event = _due_event(conn, assignment_id)
        updates: dict[str, Any] = {}
        notes: list[str] = []

        # ---- validate and normalize each field
        if "title" in sent:
            title = " ".join(sent["title"].split())
            if not title:
                raise SettingsError("The title can't be empty.")
            if len(title) > MAX_TITLE:
                raise SettingsError(f"Keep the title under {MAX_TITLE} characters.")
            if title != a["assignment_name"]:
                updates["assignment_name"] = title

        lesson = _day(sent["lesson_date"], "The lesson date") if "lesson_date" in sent else None
        if lesson and lesson.isoformat() != a.get("lesson_date"):
            updates["lesson_date"] = lesson.isoformat()

        due_iso = _due_iso(sent["due_date"]) if "due_date" in sent else a.get("due_date")
        if "due_date" in sent and due_iso != a.get("due_date"):
            updates["due_date"] = due_iso
        if "due_day" in sent:
            due_day = _day(sent["due_day"], "The due day")
            instant = _instant(due_iso)
            if instant and abs((due_day - instant.astimezone(timezone.utc).date()).days) > 1:
                raise SettingsError("The due day doesn't match the due date (they can differ by one day at most, "
                                    "for time zones).")
        elif "due_date" in sent:
            due_day = date.fromisoformat(due_iso[:10])  # no local day sent: use the UTC day
        else:
            due_day = _stored_due_day(a, event)

        if "tutor_mode" in sent:
            if sent["tutor_mode"] not in TUTOR_MODES:
                raise SettingsError("Tutor mode must be 'hints_only' or 'answer_after_tries'.")
            if sent["tutor_mode"] != a.get("tutor_mode"):
                updates["tutor_mode"] = sent["tutor_mode"]
        mode = updates.get("tutor_mode", a.get("tutor_mode") or "hints_only")
        if "tutor_reveal_after" in sent:
            lo, hi = REVEAL_RANGE
            if mode != "answer_after_tries":
                raise SettingsError("The number of honest tries only applies when the tutor may give the answer "
                                    "after tries (tutor mode 'answer_after_tries').")
            if not lo <= sent["tutor_reveal_after"] <= hi:
                raise SettingsError(f"Honest tries before the tutor explains must be between {lo} and {hi}.")
            if sent["tutor_reveal_after"] != a.get("tutor_reveal_after"):
                updates["tutor_reveal_after"] = sent["tutor_reveal_after"]

        if "mastery_threshold" in sent:
            threshold = _threshold(sent["mastery_threshold"])
            if abs(threshold - float(a["mastery_threshold"])) > 1e-9:
                updates["mastery_threshold"] = threshold

        dates_sent = {"lesson_date", "due_date", "due_day"} & sent.keys()
        lesson_iso = updates.get("lesson_date") or a.get("lesson_date")
        lesson_day = date.fromisoformat(lesson_iso[:10]) if lesson_iso else None
        if dates_sent and lesson_day and due_day and due_day > lesson_day:
            raise SettingsError(f"The due date ({_nice_day(due_day)}) must be on or before the lesson "
                                f"({_nice_day(lesson_day)}), so students finish before class.")

        # ---- write
        if updates:
            cols = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE assignments SET {cols} WHERE assignment_id = ?", (*updates.values(), assignment_id))

        # ---- calendar: the due-date entry follows the due date when the rules allow it
        calendar_note = None
        title = updates.get("assignment_name", a["assignment_name"])
        # A renamed check-in renames its calendar entry, unless the teacher renamed that entry.
        if "assignment_name" in updates and event and event["title"] == f"{a['assignment_name']} due":
            conn.execute("UPDATE calendar_events SET title = ? WHERE event_id = ?", (f"{title} due", event["event_id"]))
            event["title"] = f"{title} due"
        due_moved = "due_date" in updates
        if due_day and ("due_date" in sent or "due_day" in sent) and (
                (event and event["date"] != due_day.isoformat()) or (event is None and due_moved)):
            problem = calendar_problem(conn, class_id, due_day, event["event_id"] if event else None)
            if problem and event:
                calendar_note = (f"Calendar: the due-date entry stays on {_nice_day(date.fromisoformat(event['date']))} "
                                 f"because {problem}. Move it from the Scheduler if you want it elsewhere.")
            elif problem:
                calendar_note = (f"Calendar: no due-date entry added because {problem}. "
                                 "Add it from the Scheduler if you want it there.")
            elif event:
                conn.execute("UPDATE calendar_events SET date = ? WHERE event_id = ?",
                             (due_day.isoformat(), event["event_id"]))
                calendar_note = f"Calendar: moved \"{event['title']}\" to {_nice_day(due_day)}."
            else:
                conn.execute(
                    "INSERT INTO calendar_events (class_id, title, kind, date, assignment_id, source, status) "
                    "VALUES (?, ?, 'assignment_due', ?, ?, 'unit package', 'published')",
                    (class_id, f"{title} due", due_day.isoformat(), assignment_id))
                calendar_note = f"Calendar: added \"{title} due\" on {_nice_day(due_day)}."

        # ---- notes
        if "mastery_threshold" in updates:
            notes.append(_threshold_note(float(a["mastery_threshold"]), updates["mastery_threshold"],
                                         _unlocked_students(conn, assignment_id)))
        if "tutor_mode" in updates:
            notes.append("Tutor mode changed. It applies from each student's next message to the tutor; "
                         "hints or explanations already given stay as they were.")
        if due_moved:
            was_past, now_past = _past(a.get("due_date")), _past(due_iso)
            if now_past and not was_past:
                notes.append("That due date has already passed, so students can no longer change their answers.")
            elif was_past and not now_past:
                notes.append("The check-in is open again until the new due date.")
        if "lesson_date" in updates and (problem := school_day_problem(conn, class_id, lesson_day)):
            notes.append(f"Heads up: {problem}.")
        if calendar_note:
            notes.append(calendar_note)
        if not updates:
            notes.append("Nothing changed.")

        out = _settings_out(conn, {**a, **updates})
    changed = ["title" if k == "assignment_name" else k for k in updates]
    return {"settings": out, "changed": changed, "notes": notes, "calendar_note": calendar_note}
