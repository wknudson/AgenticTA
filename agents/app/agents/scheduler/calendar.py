"""Teacher settings and deterministic calendar validation (no model calls)."""
import json
from collections import Counter
from datetime import date

from pydantic import BaseModel, Field, model_validator

from app.shared.db import connect


class Holiday(BaseModel):
    date: date
    label: str = Field(default="Holiday", min_length=1, max_length=120)


class TermSettings(BaseModel):
    term_start: date
    term_end: date
    holidays: list[Holiday] = Field(default_factory=list, max_length=100)
    max_per_day: int = Field(default=2, ge=1, le=20)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.term_end < self.term_start:
            raise ValueError("Term end must be on or after term start.")
        dates = [h.date for h in self.holidays]
        if len(set(dates)) != len(dates):
            raise ValueError("Each holiday date must be unique.")
        if any(d < self.term_start or d > self.term_end for d in dates):
            raise ValueError("Holidays must fall within the term.")
        return self


def load_term(class_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM term_calendar WHERE class_id = ?", (class_id,)).fetchone()
    if row is None:
        return None
    return {"term_start": row["term_start"], "term_end": row["term_end"],
            "holidays": json.loads(row["holidays_json"]), "max_per_day": row["max_assessments_per_day"]}


def save_term(class_id: int, settings: TermSettings) -> dict:
    data = settings.model_dump(mode="json")
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM classes WHERE class_id = ?", (class_id,)).fetchone():
            raise LookupError("Class not found.")
        conn.execute("""INSERT INTO term_calendar
            (class_id, term_start, term_end, holidays_json, max_assessments_per_day)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(class_id) DO UPDATE SET
            term_start=excluded.term_start, term_end=excluded.term_end,
            holidays_json=excluded.holidays_json,
            max_assessments_per_day=excluded.max_assessments_per_day""",
            (class_id, data["term_start"], data["term_end"], json.dumps(data["holidays"]), data["max_per_day"]))
    return data


def validate_events(term: dict | None, events: list[dict], published: list[dict] = ()) -> dict:
    if term is None:
        return {"ok": False, "problems": [{"problem": "Save term dates and holidays before scheduling."}]}
    holidays = {h["date"]: h["label"] for h in term["holidays"]}
    problems = []
    counts = Counter(e["date"] for e in published if e["kind"] in ("assessment", "assignment_due"))
    for event in events:
        title, raw = event.get("title", ""), event.get("date", "")
        issue = {"event": title, "date": raw}
        try:
            day = date.fromisoformat(raw)
            if day.isoformat() != raw:
                raise ValueError()
        except (ValueError, TypeError):
            problems.append({**issue, "problem": "Date must be YYYY-MM-DD."})
            continue
        if not isinstance(title, str) or not title.strip():
            problems.append({**issue, "problem": "Event title is required."})
        if event.get("kind", "event") not in ("assessment", "assignment_due", "reading", "event"):
            problems.append({**issue, "problem": "Unknown event kind."})
        if not term["term_start"] <= raw <= term["term_end"]:
            problems.append({**issue, "problem": "outside the term"})
        if day.weekday() >= 5:
            problems.append({**issue, "problem": "weekend"})
        if raw in holidays:
            problems.append({**issue, "problem": f"holiday: {holidays[raw]}"})
        if event.get("kind") in ("assessment", "assignment_due"):
            counts[raw] += 1
    proposed_days = {e.get("date") for e in events}
    for day, count in counts.items():
        if day in proposed_days and count > term["max_per_day"]:
            problems.append({"date": day, "problem": f"{count} assessments/due dates (max {term['max_per_day']})"})
    return {"ok": not problems, "problems": problems}
