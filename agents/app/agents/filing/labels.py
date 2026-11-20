"""The label contract and the deterministic guardrails every label passes through,
whether it came from rules + embeddings (classify.py) or from the AI (pipeline / ai_queue).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.shared import library
from app.shared.db import connect

REVIEW_THRESHOLD = 0.6
OUTLINE_CHARS = 3000

DocType = Literal["syllabus", "lecture", "worksheet", "quiz", "test", "lab", "rubric", "reading", "schedule", "other"]
DOC_TYPES: tuple[str, ...] = DocType.__args__  # type: ignore[attr-defined]
COURSE_WIDE = {"syllabus", "schedule"}  # never belong to a single unit


class DateMention(BaseModel):
    date: str = Field(description="YYYY-MM-DD")
    label: str = Field(description="what happens that day, e.g. 'Unit 2 test' or 'Lab report due'")


class FileLabels(BaseModel):
    """What a labeler must return (Module 6: Pydantic as the contract).  Field descriptions are part of the prompt."""
    title: str = Field(description="short human title, e.g. 'Photosynthesis lecture slides'")
    doc_type: DocType = Field(description="what kind of class document this is")
    unit: str | None = Field(default=None, description="the unit it belongs to, using an exact unit name from the course outline; null for course-wide documents")
    summary: str = Field(description="one or two sentences for a teacher skimming their files")
    dates: list[DateMention] = Field(default_factory=list, description="dated events (due dates, tests, labs); empty if none")
    confidence: float = Field(ge=0, le=1, description="how sure you are of doc_type and unit, 0 to 1")


# ---------------------------------------------------------------- class context
def class_context(class_id: int) -> dict[str, Any]:
    with connect() as conn:
        r = conn.execute(
            """SELECT c.class_name, c.semester, s.subject_code, s.description AS subject
               FROM classes c JOIN subjects s ON s.subject_id = c.subject_id WHERE c.class_id = ?""",
            (class_id,),
        ).fetchone()
    return dict(r) if r else {}


def course_outline(class_id: int, exclude_file_id: int | None = None) -> str | None:
    """Start of the class's latest syllabus/schedule: it tells us what the units are."""
    with connect() as conn:
        r = conn.execute(
            """SELECT file_id FROM library_files
               WHERE class_id = ? AND doc_type IN ('syllabus', 'schedule') AND status IN ('filed', 'needs_review')
                     AND file_id != COALESCE(?, -1)
               ORDER BY doc_type = 'syllabus' DESC, file_id DESC LIMIT 1""",
            (class_id, exclude_file_id),
        ).fetchone()
    return library.get_file_text(r["file_id"])[:OUTLINE_CHARS] if r else None


_UNIT_LINE = re.compile(r"^\s*(?:[-*]\s*)?unit\s*(\d+)\s*[:\-–]\s*(.+)$", re.IGNORECASE)


def unit_catalog(class_id: int, exclude_file_id: int | None = None) -> dict[str, str]:
    """{'Unit 1: Chemistry of Life': 'Unit 1: Chemistry of Life (Aug 24 ...). Water, carbon, ...'}
    parsed from the syllabus lines that introduce units.  Empty until a syllabus is filed."""
    outline = course_outline(class_id, exclude_file_id) or ""
    units: dict[str, str] = {}
    seen: set[str] = set()
    for line in outline.splitlines():
        m = _UNIT_LINE.match(line)
        if not m or m.group(1) in seen:
            continue
        title = re.split(r"[(.]", m.group(2), maxsplit=1)[0].strip(" -:")
        if title:
            seen.add(m.group(1))
            units[f"Unit {m.group(1)}: {title}"] = line.strip()
    return units


# ---------------------------------------------------------------- guardrails
def _clean_dates(dates: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Keep only real YYYY-MM-DD dates within ~1.5 years of today; drop duplicates."""
    today, out, seen = date.today(), [], set()
    for d in dates:
        try:
            parsed = date.fromisoformat(str(d.get("date", ""))[:10])
        except ValueError:
            continue
        if abs((parsed - today).days) > 550 or (parsed.isoformat(), d.get("label")) in seen:
            continue
        seen.add((parsed.isoformat(), d.get("label")))
        out.append({"date": parsed.isoformat(), "label": str(d.get("label") or "")[:120]})
    return sorted(out, key=lambda x: x["date"])


def _unit_number(u: str) -> str | None:
    m = re.search(r"\bunit\s*(\d+)", u, re.IGNORECASE)
    return m.group(1) if m else None


def _snap_unit(unit: str | None, existing: list[str]) -> str | None:
    """Map a unit name onto the class's existing names ('unit 3 - energy' -> 'Unit 3: Cell Energy')."""
    if not unit:
        return None
    unit = re.sub(r"\s+", " ", unit).strip()
    for e in existing:
        if e.lower() == unit.lower():
            return e
    n = _unit_number(unit)
    if n:
        for e in existing:
            if _unit_number(e) == n:
                # Keep the existing name unless the new one is just more descriptive
                # ("Unit 2" -> "Unit 2: Cell Structure"); _upgrade_unit renames the folder then.
                return unit if (":" in unit and ":" not in e) else e
    return unit


def _upgrade_unit(class_id: int, new: str | None, existing: list[str]) -> None:
    """If a bare 'Unit 2' folder exists and a file names it 'Unit 2: Cell Structure',
    rename the folder for every file in the class so units don't split."""
    n = _unit_number(new) if new else None
    if not n or ":" not in new:
        return
    for e in existing:
        if e != new and _unit_number(e) == n and ":" not in e:
            with connect() as conn:
                conn.execute("UPDATE library_files SET unit = ? WHERE class_id = ? AND unit = ?", (new, class_id, e))


def known_and_catalog_units(class_id: int, exclude_file_id: int | None = None) -> list[str]:
    """Catalog names first (the syllabus is the source of truth), then any other folders."""
    names = list(unit_catalog(class_id, exclude_file_id))
    return names + [u for u in library.known_units(class_id) if u not in names]


def apply_guardrails(class_id: int, labels: FileLabels, *, exclude_file_id: int | None = None) -> list[str]:
    """Clean labels in place; return review reasons (empty = confident)."""
    existing = known_and_catalog_units(class_id, exclude_file_id)
    labels.dates = [DateMention(**d) for d in _clean_dates([d.model_dump() for d in labels.dates])]
    labels.unit = None if labels.doc_type in COURSE_WIDE else _snap_unit(labels.unit, existing)
    _upgrade_unit(class_id, labels.unit, existing)
    reasons = []
    if labels.confidence < REVIEW_THRESHOLD:
        reasons.append(f"low confidence ({labels.confidence:.2f})")
    if labels.doc_type == "other":
        reasons.append("couldn't tell what kind of document this is")
    if (existing and labels.unit and labels.unit not in existing and not _unit_number(labels.unit)
            and any(_unit_number(e) for e in existing)):
        reasons.append(f"'{labels.unit}' doesn't match this class's units")
    return reasons
