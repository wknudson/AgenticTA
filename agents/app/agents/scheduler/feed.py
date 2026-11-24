"""The month calendar's data in one call, and no-AI suggestions for check-in lesson days.

    GET /feed?class_id[&start&end]       term, calendar events, check-ins (open day, due day,
                                         status, stage counts), drafts and graded assignments
    GET /checkin-suggestions?class_id    per Library unit: a lesson day 2 school days before
                                         the unit's next quiz or test, or why there isn't one

Everything here is deterministic. It reads shared tables with SQL (assignments,
calendar_events, unit_packages, approvals and the check-in progress tables) and filed
documents through app/shared/library. The check-in status and stage-count rules are copied
from the misconceptions briefing (briefing.checkin_status / stage_counts), because agents
don't import each other: keep the two in step.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.shared import library
from app.shared.db import connect

from .calendar import load_term
from .drafting import SOURCE_RANK, UNIT, _file_name, classify, clean_title

DEFAULT_BACK = timedelta(days=30)      # no term saved: show a month back ...
DEFAULT_AHEAD = timedelta(days=120)    # ... and about four months ahead
OPEN_BEFORE_LESSON = timedelta(days=7)  # no approval on record: the check-in opened a week before its lesson
DUE_SOON = timedelta(hours=24)
STAGES = ("not_started", "practicing", "checkin", "complete")
NO_ANCHOR = "No upcoming quiz or test found for this unit. Pick a lesson day yourself."


def _today() -> date:
    """Today on this machine (tests replace it)."""
    return date.today()


def _day(value: Any) -> date | None:
    """YYYY-MM-DD (or the date part of an ISO timestamp), else None."""
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _local_day(stamp: str | None) -> date | None:
    """The local calendar day of a stored UTC timestamp (approvals.decided_at)."""
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return _day(stamp)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone().date()


# ---- Copied from misconceptions/briefing.py (same rules as the Assignments list) ---------------

def _due_at(due: str | None) -> datetime | None:
    if not due:
        return None
    try:
        when = datetime.fromisoformat(due.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def checkin_status(due: str | None, now: datetime | None = None) -> str:
    """'closed' once the due date has passed, 'due_soon' within 24 hours of it, else 'live'."""
    when = _due_at(due)
    if when is None:
        return "live"
    now = now or datetime.now(timezone.utc)
    if now > when:
        return "closed"
    return "due_soon" if when - now <= DUE_SOON else "live"


def _enrolled_sql() -> str:
    return "SELECT student_id FROM student_classes WHERE class_id = ? AND LOWER(TRIM(status)) = 'active'"


def stage_counts(conn: sqlite3.Connection, class_id: int, assignment_ids: list[int]) -> dict[int, dict[str, int]]:
    """assignment_id -> {total, not_started, practicing, checkin, complete} over active students:
    complete = every question resolved, checkin = something answered, practicing = played the games."""
    if not assignment_ids:
        return {}
    marks = ",".join("?" * len(assignment_ids))
    students = [r["student_id"] for r in conn.execute(_enrolled_sql(), (class_id,))]
    n_questions = {r["assignment_id"]: r["n"] for r in conn.execute(
        f"SELECT assignment_id, COUNT(*) AS n FROM assignment_questions WHERE assignment_id IN ({marks}) "
        "GROUP BY assignment_id", assignment_ids)}
    progress = {(r["assignment_id"], r["student_id"]): (r["answered"] or 0, r["resolved"] or 0) for r in conn.execute(
        f"""SELECT s.assignment_id, s.student_id,
                   SUM(s.status != 'unanswered') AS answered,
                   SUM(s.status != 'unanswered' AND (s.first_correct = 1 OR s.status = 'fixed')) AS resolved
            FROM checkin_item_status s
            JOIN assignment_questions q ON q.question_id = s.question_id AND q.assignment_id = s.assignment_id
            WHERE s.assignment_id IN ({marks}) AND s.student_id IN ({_enrolled_sql()})
            GROUP BY s.assignment_id, s.student_id""", (*assignment_ids, class_id))}
    played = {(r["assignment_id"], r["student_id"]) for r in conn.execute(
        f"SELECT assignment_id, student_id FROM game_scores WHERE assignment_id IN ({marks}) "
        f"AND student_id IN ({_enrolled_sql()})", (*assignment_ids, class_id))}
    out: dict[int, dict[str, int]] = {}
    for aid in assignment_ids:
        counts = {"total": len(students), **{stage: 0 for stage in STAGES}}
        total_q = n_questions.get(aid, 0)
        for sid in students:
            answered, resolved = progress.get((aid, sid), (0, 0))
            if total_q > 0 and resolved == total_q:
                stage = "complete"
            elif answered > 0:
                stage = "checkin"
            elif (aid, sid) in played:
                stage = "practicing"
            else:
                stage = "not_started"
            counts[stage] += 1
        out[aid] = counts
    return out


# ---- The feed ----------------------------------------------------------------------------------

def feed_range(term: dict | None, start: date | None, end: date | None, today: date) -> tuple[date, date]:
    """The requested days; by default the term, else a month back to four months ahead."""
    if start is None:
        start = date.fromisoformat(term["term_start"]) if term else today - DEFAULT_BACK
    if end is None:
        end = date.fromisoformat(term["term_end"]) if term else today + DEFAULT_AHEAD
    if end < start:
        raise ValueError("end must be on or after start.")
    return start, end


def _overlaps(days: list[date | None], lo: date, hi: date) -> bool:
    known = [d for d in days if d is not None]
    return bool(known) and min(known) <= hi and max(known) >= lo


def _events(conn: sqlite3.Connection, class_id: int, lo: date, hi: date) -> list[dict[str, Any]]:
    """Calendar events still on the calendar, minus the ones tied to a check-in (checkins[] has those)."""
    rows = conn.execute(
        """SELECT event_id, title, kind, date, status, assignment_id, source FROM calendar_events
           WHERE class_id = ? AND status IN ('published', 'proposed') AND date BETWEEN ? AND ?
             AND (assignment_id IS NULL
                  OR assignment_id NOT IN (SELECT assignment_id FROM assignments WHERE mode = 'checkin'))
           ORDER BY date, event_id""", (class_id, lo.isoformat(), hi.isoformat())).fetchall()
    return [dict(r) for r in rows]


def _due_events(conn: sqlite3.Connection, class_id: int, ids: list[int]) -> dict[int, dict[str, Any]]:
    """assignment_id -> its due-day calendar entry (published first, then the newest), like the
    check-in settings editor. Entries the teacher removed don't count."""
    if not ids:
        return {}
    out: dict[int, dict[str, Any]] = {}
    for r in conn.execute(
            f"""SELECT event_id, assignment_id, date FROM calendar_events
                WHERE class_id = ? AND kind = 'assignment_due' AND status IN ('published', 'proposed')
                  AND assignment_id IN ({','.join('?' * len(ids))})
                ORDER BY status = 'published' DESC, event_id DESC""", (class_id, *ids)):
        out.setdefault(r["assignment_id"], dict(r))
    return out


def _approved_days(conn: sqlite3.Connection, class_id: int) -> dict[int, date]:
    """assignment_id -> the day its unit package's publish_unit_package approval was approved."""
    packages = {r["package_id"]: r["assignment_id"] for r in conn.execute(
        "SELECT package_id, assignment_id FROM unit_packages WHERE class_id = ? AND assignment_id IS NOT NULL",
        (class_id,))}
    if not packages:
        return {}
    out: dict[int, date] = {}
    for r in conn.execute(
            """SELECT action_args, decided_at FROM approvals
               WHERE action_name = 'publish_unit_package' AND status IN ('approved', 'edited')
                 AND decided_at IS NOT NULL AND (class_id = ? OR class_id IS NULL)""", (class_id,)):
        try:
            package_id = int(json.loads(r["action_args"]).get("package_id"))
        except (TypeError, ValueError, AttributeError, json.JSONDecodeError):
            continue
        aid, day = packages.get(package_id), _local_day(r["decided_at"])
        if aid is not None and day is not None and (aid not in out or day < out[aid]):
            out[aid] = day   # approved twice: the first one published it
    return out


def _checkins(conn: sqlite3.Connection, class_id: int, lo: date, hi: date) -> list[dict[str, Any]]:
    rows = [dict(r) for r in conn.execute(
        """SELECT assignment_id, assignment_name AS title, unit, lesson_date, due_date FROM assignments
           WHERE class_id = ? AND mode = 'checkin' ORDER BY assignment_id""", (class_id,))]
    events = _due_events(conn, class_id, [r["assignment_id"] for r in rows])
    opened = _approved_days(conn, class_id)
    items = []
    for r in rows:
        aid = r["assignment_id"]
        event = events.get(aid)
        lesson = _day(r["lesson_date"])
        due_day = _day(event["date"]) if event else _day(r["due_date"])
        open_day = opened.get(aid)
        if open_day is None and (lesson or due_day):
            open_day = (lesson or due_day) - OPEN_BEFORE_LESSON
        if open_day and due_day and open_day > due_day:
            open_day = due_day
        if not _overlaps([open_day, due_day, lesson], lo, hi):
            continue
        items.append({**r, "due_day": due_day.isoformat() if due_day else None,
                      "open_day": open_day.isoformat() if open_day else None,
                      "calendar_event_id": event["event_id"] if event else None})
    counts = stage_counts(conn, class_id, [i["assignment_id"] for i in items])
    now = datetime.now(timezone.utc)
    for item in items:
        item["status"] = checkin_status(item["due_date"], now)
        item["counts"] = counts[item["assignment_id"]]
    items.sort(key=lambda i: (i["due_day"] or i["lesson_date"] or "", i["assignment_id"]))
    return items


def _settings(raw: str | None) -> dict[str, Any]:
    try:
        settings = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return settings if isinstance(settings, dict) else {}


def _drafts(conn: sqlite3.Connection, class_id: int, lo: date, hi: date) -> list[dict[str, Any]]:
    """Unit packages still waiting for the publish_unit_package approval."""
    out = []
    for r in conn.execute("SELECT package_id, unit, settings_json FROM unit_packages "
                          "WHERE class_id = ? AND status = 'draft' ORDER BY package_id", (class_id,)):
        s = _settings(r["settings_json"])
        lesson = _day(s.get("lesson_date"))
        due_day = _day(s.get("due_day")) or _day(s.get("due_date"))
        if not _overlaps([lesson, due_day], lo, hi):
            continue
        out.append({"package_id": r["package_id"], "unit": r["unit"],
                    "title": s.get("title") or f"{r['unit']} check-in",
                    "lesson_date": lesson.isoformat() if lesson else None,
                    "due_day": due_day.isoformat() if due_day else None})
    out.sort(key=lambda d: (d["lesson_date"] or d["due_day"] or "", d["package_id"]))
    return out


def _graded(conn: sqlite3.Connection, class_id: int, lo: date, hi: date) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT assignment_id, assignment_name AS title, type, due_date FROM assignments
           WHERE class_id = ? AND mode != 'checkin' AND due_date IS NOT NULL
             AND substr(due_date, 1, 10) BETWEEN ? AND ?
           ORDER BY due_date, assignment_id""", (class_id, lo.isoformat(), hi.isoformat())).fetchall()
    return [dict(r) for r in rows]


def build_feed(class_id: int, start: date | None = None, end: date | None = None) -> dict[str, Any]:
    """Everything the month calendar shows for [start, end] (raises ValueError if end < start)."""
    term = load_term(class_id)
    lo, hi = feed_range(term, start, end, _today())
    with connect() as conn:
        return {
            "term": term,
            "events": _events(conn, class_id, lo, hi),
            "checkins": _checkins(conn, class_id, lo, hi),
            "drafts": _drafts(conn, class_id, lo, hi),
            "assignments": _graded(conn, class_id, lo, hi),
        }


# ---- Check-in suggestions (no AI) ----------------------------------------------------------------

def is_school_day(day: date, term: dict | None, holidays: set[str] | None = None) -> bool:
    """A weekday, inside the term and not a holiday (only weekdays count when no term is saved)."""
    if day.weekday() >= 5:
        return False
    if term is None:
        return True
    iso = day.isoformat()
    if holidays is None:
        holidays = {h["date"] for h in term["holidays"]}
    return term["term_start"] <= iso <= term["term_end"] and iso not in holidays


def lesson_day(anchor: date, term: dict | None, today: date) -> tuple[date | None, int]:
    """(lesson day, school days before the anchor): the 2nd school day before the anchor if it's
    still after today, else the 1st, else (None, 0)."""
    holidays = {h["date"] for h in term["holidays"]} if term else set()
    day = anchor - timedelta(days=1)
    if term:  # nothing after the term counts, so start walking back from its last day
        day = min(day, date.fromisoformat(term["term_end"]))
        floor = max(today, date.fromisoformat(term["term_start"]) - timedelta(days=1))
    else:
        floor = today
    found: list[date] = []
    while day > floor and len(found) < 2:
        if is_school_day(day, term, holidays):
            found.append(day)
        day -= timedelta(days=1)
    if not found:
        return None, 0
    return found[-1], len(found)


def _unit_number(unit: str) -> int | None:
    m = UNIT.search(unit)
    return int(m.group(1)) if m else None


def mentions_unit(unit: str, text: str) -> bool:
    """"Unit 3 quiz" mentions "Unit 3: Quadratic Functions" ("Unit 30" doesn't). A unit without
    a number has to be named in full."""
    number = _unit_number(unit)
    if number is None:
        return unit.strip().casefold() in text.casefold()
    return re.search(rf"\bunit\s*0*{number}\b", text, re.I) is not None


def _key(unit: str | None) -> str:
    return " ".join((unit or "").split()).casefold()


def _nice(day: date, today: date) -> str:
    text = f"{day:%a}, {day:%b} {day.day}"
    return text if day.year == today.year else f"{text}, {day.year}"


def _anchor(unit: str, events: list[dict[str, Any]], dated: list[dict[str, Any]], today: date) -> dict[str, Any] | None:
    """The unit's earliest upcoming quiz or test: from the calendar, else from Library dates."""
    on_calendar = sorted(
        ((d, e["event_id"], e) for e in events
         if (d := _day(e["date"])) and d > today and mentions_unit(unit, e["title"])),
        key=lambda x: (x[0], x[1]))
    if on_calendar:
        d, _, e = on_calendar[0]
        return {"title": e["title"], "date": d.isoformat(), "kind": e["kind"], "source": "calendar"}
    in_files = sorted(
        (x for x in dated if x["date"] > today and mentions_unit(unit, x["label"])),
        key=lambda x: (x["date"], x["rank"], x["title"]))
    if in_files:
        x = in_files[0]
        return {"title": x["title"], "date": x["date"].isoformat(), "kind": "assessment", "source": x["file"]}
    return None


def checkin_suggestions(class_id: int) -> dict[str, Any]:
    today, now = _today(), datetime.now(timezone.utc)
    term = load_term(class_id)
    files = library.list_files(class_id)   # filed + needs review (no archived files or drafts)
    # Units exactly as filed (the unit package looks its files up by this string); course-wide files have none.
    units = sorted({f.unit for f in files if f.status == "filed" and f.unit and f.unit.strip()},
                   key=lambda u: (_unit_number(u) is None, _unit_number(u) or 0, u.casefold()))
    dated = []
    for f in files:
        for d in f.dates or []:
            day, label = _day(d.get("date")), (d.get("label") or "").strip()
            if day and label and classify(label) == "assessment":
                dated.append({"date": day, "label": label, "title": clean_title(label) or label,
                              "file": _file_name(f), "rank": SOURCE_RANK.get(f.doc_type or "", 2)})
    with connect() as conn:
        open_checkins: dict[str, str] = {}
        for r in conn.execute("SELECT assignment_name, unit, due_date FROM assignments "
                              "WHERE class_id = ? AND mode = 'checkin' AND unit IS NOT NULL "
                              "ORDER BY assignment_id", (class_id,)):
            if checkin_status(r["due_date"], now) != "closed":
                open_checkins.setdefault(_key(r["unit"]), r["assignment_name"])
        drafted = {_key(r["unit"]) for r in conn.execute(
            "SELECT unit FROM unit_packages WHERE class_id = ? AND status = 'draft'", (class_id,))}
        events = [dict(r) for r in conn.execute(
            "SELECT event_id, title, kind, date FROM calendar_events WHERE class_id = ? AND kind = 'assessment' "
            "AND status NOT IN ('removed', 'rejected')", (class_id,))]

    suggestions, skipped = [], []
    for unit in units:
        key = _key(unit)
        if key in open_checkins:
            skipped.append({"unit": unit, "reason": f"This unit already has a check-in that isn't closed yet "
                                                    f"(\"{open_checkins[key]}\")."})
            continue
        if key in drafted:
            skipped.append({"unit": unit, "reason": "A check-in for this unit is drafted and waiting for approval."})
            continue
        anchor = _anchor(unit, events, dated, today)
        if anchor is None:
            skipped.append({"unit": unit, "reason": NO_ANCHOR})
            continue
        when = date.fromisoformat(anchor["date"])
        lesson, before = lesson_day(when, term, today)
        if lesson is None:
            skipped.append({"unit": unit, "reason": f"{anchor['title']} on {_nice(when, today)} is too soon: "
                                                    "there's no school day left before it. Pick a lesson day yourself."})
            continue
        if before == 2:
            reason = (f"2 school days before {anchor['title']} on {_nice(when, today)}, "
                      "so the check-in feeds the review lesson.")
        else:
            reason = (f"1 school day before {anchor['title']} on {_nice(when, today)} (there isn't time for 2), "
                      "so the check-in feeds the last lesson before it.")
        suggestions.append({"unit": unit, "lesson_date": lesson.isoformat(),
                            "due_day": (lesson - timedelta(days=1)).isoformat(), "reason": reason, "anchor": anchor})
    suggestions.sort(key=lambda s: (s["lesson_date"], s["unit"]))
    return {"suggestions": suggestions, "skipped": skipped}
