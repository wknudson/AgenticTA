"""No-AI calendar building: everything here is deterministic.

- suggest_term():  term dates + holidays from the dates the Library already pulled out of
                   the syllabus / course calendar ("First day", "Thanksgiving break, no school").
- draft_events():  turn Library dates and assignment due dates into calendar events,
                   merging the same event found in several files ("Unit 1 quiz" in the syllabus,
                   the calendar, and the quiz itself).

The scheduler agent (agent.py) does the same job with a model; this path needs no API key,
and its output still goes through check_conflicts and the teacher's approval.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from app.shared import library
from app.shared.db import connect

from .calendar import load_term, validate_events

HOLIDAY = re.compile(r"\b(no school|no class(es)?|holidays?|break|vacation|recess|day off|in-?service|"
                     r"teacher (work|planning|prep) day|professional development|school closed)\b", re.I)
TERM_START = re.compile(r"\b(first day|classes (begin|start)|(term|semester|school) (begins|starts))\b", re.I)
TERM_END = re.compile(r"\b(last day|classes end|(term|semester) ends|end of (the )?(term|semester))\b", re.I)
PAPERWORK = re.compile(r"\b(permission slips?|field trip|forms?)\b", re.I)
DUE = re.compile(r"\b(due|submit|turn in|deadline)\b", re.I)
ASSESSMENT = re.compile(r"\b(quiz|test|exam|midterm|final|assessment)\b", re.I)
READING = re.compile(r"\b(read|reading|chapter|ch\.)\b", re.I)
UNIT = re.compile(r"\bunit\s*(\d+)\b", re.I)
# Leftovers from worksheet headers: "UNIT 1 QUIZ: LINEAR FUNCTIONS Date", "Project Rubric (due )"
TRAILING_FIELD = re.compile(r"[\s:_-]*\b(date|name|period|score)\b[\s:_-]*$", re.I)
EMPTY_PARENS = re.compile(r"\(\s*(due)?\s*\)", re.I)

# Course calendars and syllabi say the date on purpose; a date on a worksheet is a weaker signal.
SOURCE_RANK = {"schedule": 0, "syllabus": 1}
RANGE_GAP_DAYS = 14  # "Thanksgiving break" on Nov 25 and Nov 27 means Nov 25-27


def _file_name(f) -> str:
    """Readable source name: the file's title minus worksheet header leftovers ("   Date: ...")."""
    title = re.split(r"\s{2,}|\s+(lab )?date:", f.title or "", maxsplit=1, flags=re.I)[0]
    return clean_title(title) or f.original_name


def _library_dates(class_id: int) -> list[dict]:
    out = []
    for f in library.list_files(class_id):
        for d in f.dates or []:
            try:
                day = date.fromisoformat(d.get("date", ""))
            except (TypeError, ValueError):
                continue
            out.append({"date": day, "label": (d.get("label") or "").strip(), "file": _file_name(f),
                        "doc_type": f.doc_type or "other"})
    return out


def clean_title(label: str) -> str:
    text = EMPTY_PARENS.sub("", label)
    for _ in range(3):
        text = TRAILING_FIELD.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" :;,-_")
    if text.isupper():
        text = text.title()
    return text[:1].upper() + text[1:] if text else text


def classify(label: str) -> str | None:
    """Event kind for a dated label, or None when it is a holiday / term marker (not an event)."""
    if HOLIDAY.search(label) or TERM_START.search(label) or TERM_END.search(label):
        return None
    if PAPERWORK.search(label):
        return "event"
    if DUE.search(label):
        return "assignment_due"
    if ASSESSMENT.search(label):
        return "assessment"
    if READING.search(label):
        return "reading"
    return "event"


def suggest_term(class_id: int) -> dict:
    """Term settings read from filed documents. Nothing is saved; the teacher reviews the form."""
    found = _library_dates(class_id)
    if not found:
        return {"term": None, "notes": ["No dates found in this class's library yet. File the syllabus or course calendar first."]}
    current = load_term(class_id) or {}
    notes = []

    starts = sorted(d["date"] for d in found if TERM_START.search(d["label"]))
    ends = sorted(d["date"] for d in found if TERM_END.search(d["label"]))
    all_days = sorted(d["date"] for d in found)
    if starts:
        start = starts[0]
    else:
        start = all_days[0]
        notes.append("No \"first day\" found; the term starts at the earliest date in your documents.")
    if ends:
        end = ends[-1]
    else:
        end = all_days[-1]
        notes.append("No \"last day\" found; the term ends at the latest date in your documents. Adjust if needed.")
    end = max(end, start)

    by_label: dict[str, list[date]] = {}
    labels: dict[str, str] = {}
    for d in found:
        if HOLIDAY.search(d["label"]) and not TERM_START.search(d["label"]):
            key = clean_title(d["label"]).lower()
            by_label.setdefault(key, []).append(d["date"])
            labels[key] = clean_title(d["label"])
    holidays: dict[date, str] = {}
    for key, days in by_label.items():
        days = sorted(set(days))
        if len(days) > 1 and (days[-1] - days[0]).days <= RANGE_GAP_DAYS:
            days = [days[0] + timedelta(n) for n in range((days[-1] - days[0]).days + 1)]  # fill the range
        for day in days:
            if start <= day <= end and day.weekday() < 5:
                holidays.setdefault(day, labels[key])

    sources = sorted({d["file"] for d in found if d["doc_type"] in SOURCE_RANK} or {d["file"] for d in found})
    return {
        "term": {"term_start": start.isoformat(), "term_end": end.isoformat(),
                 "holidays": [{"date": k.isoformat(), "label": v} for k, v in sorted(holidays.items())],
                 "max_per_day": current.get("max_per_day", 2)},
        "sources": sources,
        "notes": notes,
    }


def _unit(title: str) -> str | None:
    m = UNIT.search(title)
    return m.group(1) if m else None


def _same_event(a: dict, b: dict) -> bool:
    """Same day, same kind, and not clearly different units."""
    if a["date"] != b["date"] or a["kind"] != b["kind"]:
        return False
    ua, ub = _unit(a["title"]), _unit(b["title"])
    return ua is None or ub is None or ua == ub


def _candidates(class_id: int) -> list[dict]:
    items = []
    for d in _library_dates(class_id):
        kind = classify(d["label"])
        title = clean_title(d["label"])
        if kind is None or not title:
            continue
        items.append({"title": title, "date": d["date"].isoformat(), "kind": kind, "source": d["file"],
                      "rank": SOURCE_RANK.get(d["doc_type"], 2)})
    with connect() as conn:
        rows = conn.execute("SELECT assignment_id, assignment_name, type, due_date FROM assignments "
                            "WHERE class_id = ? AND due_date IS NOT NULL", (class_id,)).fetchall()
    for r in rows:
        name = (r["assignment_name"] or "Assignment").strip()
        kind = "assessment" if ASSESSMENT.search(f"{r['type'] or ''} {name}") else "assignment_due"
        items.append({"title": name if kind == "assessment" else f"{name} due", "date": str(r["due_date"])[:10],
                      "kind": kind, "source": "assignment", "assignment_id": r["assignment_id"], "rank": -1})

    # Merge the same event found in several places; the best-ranked source names it.
    merged: list[dict] = []
    for item in sorted(items, key=lambda i: (i["date"], i["rank"], -len(i["title"]))):
        twin = next((m for m in merged if _same_event(m, item)), None)
        if twin is None:
            merged.append({**item, "sources": [item["source"]]})
        else:
            if item["source"] not in twin["sources"]:
                twin["sources"].append(item["source"])
            twin.setdefault("assignment_id", item.get("assignment_id"))
    for m in merged:
        m["source"] = "; ".join(m.pop("sources"))[:300]
        m.pop("rank", None)
        if m.get("assignment_id") is None:
            m.pop("assignment_id", None)
    return merged


def draft_events(class_id: int) -> dict:
    """Split the candidates into events ready to propose and ones the teacher has to decide on."""
    term = load_term(class_id)
    with connect() as conn:
        existing = [dict(r) for r in conn.execute(
            "SELECT * FROM calendar_events WHERE class_id = ? AND status IN ('proposed', 'published')", (class_id,))]
    published = [e for e in existing if e["status"] == "published"]
    ready, skipped = [], []
    for c in _candidates(class_id):
        if any(_same_event(c, e) for e in existing):
            skipped.append({**c, "problem": "already on the calendar"})
            continue
        checks = validate_events(term, [*ready, c], published)
        if checks["ok"]:
            ready.append(c)
        else:
            mine = [p["problem"] for p in checks["problems"]
                    if p.get("event") == c["title"] or (p.get("date") == c["date"] and "event" not in p)]
            skipped.append({**c, "problem": "; ".join(mine) or "conflict"})
    return {"ready": ready, "skipped": skipped}
