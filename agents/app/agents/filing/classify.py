"""Fast labels: rules + embeddings, NO labeling model.  (Option 2: "embeddings first, AI only when unsure")

The course requirements say it directly: if embeddings and similarity search solve the problem,
use them instead of a model you don't need.  Measured on the sample Biology course, embeddings
put 22 of 23 unit files in the right unit with zero labeling calls (see filing README).

    type    file-name keywords (strong), then the document's first line (medium),
            else nearest "type prototype" by embedding (weak -> ask the AI)
    unit    "Unit 3" written in the name/title (strong), else the nearest syllabus unit
            description by embedding; a small margin between the top two units means
            "could be either" -> course-wide or ask the AI
    title   first real line of the document, else the file name
    dates   ISO (2026-09-17), "Sep 17", "December 4, 2026", "12/4/2026", labeled with the rest of the line

The embeddings are the same chunk vectors the search index stores, so this costs nothing extra.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from langsmith import traceable

from app.shared import library
from app.shared.db import connect
from app.shared.embeddings import get_embedder

from .labels import COURSE_WIDE, DateMention, FileLabels, _clean_dates, _unit_number, class_context, unit_catalog

UNIT_MARGIN = 0.025   # top unit must beat the runner-up by this much (tuned on the sample course)
TYPE_MARGIN = 0.015

# (pattern, doc_type) in priority order: "Lab_Report_Rubric" is a rubric, "Final_Exam_Review" a worksheet.
ADMIN = r"letter|contract|permission|gradebook|roster|consent|waiver|newsletter"  # paperwork: never one unit's content

TYPE_RULES: list[tuple[str, str]] = [
    (r"syllabus", "syllabus"),
    (r"calendar|schedule|pacing", "schedule"),
    (ADMIN, "other"),
    (r"rubric|scoring guide", "rubric"),
    (r"review|study guide", "worksheet"),
    (r"quiz", "quiz"),
    (r"\b(test|exam|midterm)\b|_test|test_|exam_|_exam", "test"),
    (r"\blab\b|_lab|lab_", "lab"),
    (r"worksheet|practice|problems|homework|\bhw\b|packet|starter|activity|project", "worksheet"),
    (r"slides|lecture|notes|presentation|cheat ?sheet|whiteboard", "lecture"),
    (r"reading|article|news|textbook|chapter|excerpt", "reading"),
    (r"handout", "other"),
]
TYPE_PROTOTYPES = {
    "lecture": "Lecture slides or class notes that explain a concept with definitions and examples.",
    "worksheet": "A worksheet or practice problems for students to complete, numbered questions to answer.",
    "quiz": "A short graded quiz with a few numbered questions and a date.",
    "test": "A unit test or exam with several parts and many questions.",
    "lab": "A lab activity: materials, procedure steps, data table, and analysis questions.",
    "rubric": "A rubric table listing criteria and points for grading student work.",
    "reading": "A reading passage or article for students, written in paragraphs, with discussion questions.",
    "syllabus": "A course syllabus: units, grading policy, late work, key dates.",
    "schedule": "A class calendar listing dates and events.",
    "other": "A letter, form, or administrative document for families or students.",
}


@dataclass
class FastResult:
    labels: FileLabels
    unsure: list[str] = field(default_factory=list)  # why the AI should double-check (empty = confident)


# ---------------------------------------------------------------- rules
def _rule_type(text: str) -> str | None:
    t = text.lower()
    return next((dtype for pat, dtype in TYPE_RULES if re.search(pat, t)), None)


def _first_line(text: str) -> str | None:
    for ln in text.splitlines():
        ln = re.sub(r"^[#*\s|>-]+|[|\s]+$", "", ln).strip()
        if 3 <= len(ln) <= 120 and re.search(r"[A-Za-z]{3}", ln):
            return ln
    return None


def _pretty_name(filename: str) -> str:
    stem = re.sub(r"[_]+", " ", Path(filename).stem)
    return re.sub(r"\s+", " ", stem).strip()


def _summary(text: str, title: str | None) -> str:
    body = text.replace(title or "", "", 1) if title else text
    body = re.sub(r"\s+", " ", body).strip()
    sentences = re.split(r"(?<=[.!?])\s+", body)
    out = ""
    for s in sentences:
        if len(out) + len(s) > 220:
            break
        out = f"{out} {s}".strip()
    return out or body[:200]


# ---------------------------------------------------------------- dates
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_US = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b")
_MON = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d\d))?\b",
                  re.IGNORECASE)
_RANGE = re.compile(r"\b(to|through|until|-)\b", re.IGNORECASE)


def _school_year(month: int, today: date | None = None) -> int:
    today = today or date.today()
    start = today.year if today.month >= 7 else today.year - 1  # school year starts in August
    return start if month >= 7 else start + 1


@traceable(name="filing.extract_dates")
def extract_dates(text: str) -> list[dict[str, str]]:
    """Dated events with a label taken from the rest of the line.  Month-name dates inside a
    range ("Aug 24 to Sep 18" in a unit description) are skipped: those are spans, not events."""
    found = []
    for line in text.splitlines():
        hits = []
        for m in _ISO.finditer(line):
            hits.append((m.span(), f"{m.group(1)}-{m.group(2)}-{m.group(3)}"))
        for m in _US.finditer(line):
            hits.append((m.span(), f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"))
        mon = list(_MON.finditer(line))
        if mon and not (len(mon) > 1 and _RANGE.search(line[mon[0].end():mon[-1].start()])):
            for m in mon:
                month = _MONTHS[m.group(1)[:3].lower()]
                year = int(m.group(3)) if m.group(3) else _school_year(month)
                hits.append((m.span(), f"{year}-{month:02d}-{int(m.group(2)):02d}"))
        if not hits:
            continue
        label = line
        for (a, b), _ in sorted(hits, reverse=True):
            label = label[:a] + label[b:]
        label = re.sub(r"^\s*(to|through)\b|\b(to|through)\s*$", "", label.strip(), flags=re.IGNORECASE)
        label = re.sub(r"\s+", " ", re.sub(r"^[\s|:\-,]+|[\s|:\-,]+$", "", label)).strip()
        label = re.sub(r"^(date|due|lab date|days?)\s*[:|]?\s*", "", label, flags=re.IGNORECASE) or "mentioned in document"
        for _, d in hits:
            found.append({"date": d, "label": label[:80]})
    return _clean_dates(found)


# ---------------------------------------------------------------- embeddings
def _mean(vectors: list[list[float]]) -> list[float] | None:
    if not vectors:
        return None
    v = [sum(col) / len(vectors) for col in zip(*vectors)]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


@lru_cache(maxsize=64)
def _embed_cached(items: tuple[tuple[str, str], ...]) -> tuple[tuple[float, ...], ...] | None:
    emb = get_embedder()
    if emb is None:
        return None
    try:
        return tuple(tuple(v) for v in emb.embed_documents(list(items)))
    except Exception:
        return None


def _nearest(vec: list[float], options: dict[str, str]) -> tuple[str, float, float] | None:
    """-> (best name, similarity, margin over the runner-up) or None without embeddings."""
    if not options:
        return None
    vecs = _embed_cached(tuple(options.items()))
    if vecs is None:
        return None
    scored = sorted(((_dot(vec, list(v)), name) for name, v in zip(options, vecs)), reverse=True)
    best, runner = scored[0], (scored[1] if len(scored) > 1 else (scored[0][0] - 1.0, ""))
    return best[1], best[0], best[0] - runner[0]


# ---------------------------------------------------------------- the fast labeler
@traceable(name="filing.fast_labels")
def fast_labels(class_id: int, filename: str, text: str, vectors: list[list[float]] | None,
                exclude_file_id: int | None = None) -> FastResult:
    unsure: list[str] = []
    title = _first_line(text) or _pretty_name(filename)
    fvec = _mean(vectors or [])

    # --- type
    doc_type, type_conf = _rule_type(_pretty_name(filename)), 0.9
    if doc_type is None:
        doc_type, type_conf = _rule_type(title), 0.75
    if doc_type is None:
        guess = _nearest(fvec, TYPE_PROTOTYPES) if fvec else None
        doc_type, type_conf = (guess[0], 0.5) if guess else ("other", 0.3)
        unsure.append("type is a guess")

    # --- unit
    catalog = unit_catalog(class_id, exclude_file_id)
    unit, unit_conf = None, 0.9
    admin = bool(re.search(ADMIN, _pretty_name(filename).lower()))
    if doc_type not in COURSE_WIDE and not admin:
        n = _unit_number(f"{filename} {title}")
        named = next((u for u in catalog if _unit_number(u) == n), f"Unit {n}") if n else None
        if named:
            unit, unit_conf = named, 0.95
        elif catalog and fvec:
            best = _nearest(fvec, catalog)
            if best and best[2] >= UNIT_MARGIN:
                unit, unit_conf = best[0], min(0.9, 0.6 + best[2] * 4)
            else:
                unsure.append("unit unclear (could be course-wide)")
                unit_conf = 0.5
        elif catalog:
            unsure.append("no embeddings to place it in a unit")
            unit_conf = 0.5
        # no catalog yet: leave it course-wide until a syllabus arrives (resort_units fixes it then)

    labels = FileLabels(title=title[:90], doc_type=doc_type, unit=unit, summary=_summary(text, title),
                        dates=[DateMention(**d) for d in extract_dates(text)],
                        confidence=round(min(type_conf, unit_conf), 2))
    return FastResult(labels=labels, unsure=unsure)


@traceable(name="filing.resort_units")
def resort_units(class_id: int) -> int:
    """After a syllabus is filed: place files that were filed BEFORE it into units, using the unit
    number they state or their STORED vectors (no API calls).  Returns how many files moved.

    Covers auto-labeled files, and AI-labeled ones the AI couldn't place because no unit list
    existed yet (unit empty or a bare 'Unit 3').  Teacher labels and AI files that already
    have a full unit name are left alone."""
    catalog = unit_catalog(class_id)
    if not catalog:
        return 0
    with connect() as conn:
        rows = conn.execute(
            """SELECT file_id, original_name, title, doc_type, unit FROM library_files
               WHERE class_id = ? AND ai_pending = 0 AND status NOT IN ('archived', 'draft')
                     AND doc_type NOT IN ('syllabus', 'schedule')
                     AND (label_source IN ('auto', 'heuristic')
                          OR (label_source IN ('llm', 'llm-fallback') AND (unit IS NULL OR unit NOT LIKE '%:%')))""",
            (class_id,),
        ).fetchall()
    moved = 0
    for r in rows:
        if re.search(ADMIN, _pretty_name(r["original_name"]).lower()):
            continue  # paperwork stays course-wide
        n = _unit_number(f"{r['original_name']} {r['title'] or ''} {r['unit'] or ''}")
        new = next((u for u in catalog if _unit_number(u) == n), None) if n else None
        if new is None:
            vec = _mean(library.file_vectors(r["file_id"]))
            best = _nearest(vec, catalog) if vec else None
            new = best[0] if best and best[2] >= UNIT_MARGIN else None
        if new and new != r["unit"]:
            with connect() as conn:
                conn.execute("UPDATE library_files SET unit = ? WHERE file_id = ?", (new, r["file_id"]))
            moved += 1
    return moved


def ai_context(class_id: int, exclude_file_id: int | None = None) -> dict:
    """Everything the AI needs about the class (shared by single and batched calls)."""
    from .labels import course_outline, known_and_catalog_units  # noqa: PLC0415
    return {"ctx": class_context(class_id), "outline": course_outline(class_id, exclude_file_id),
            "units": known_and_catalog_units(class_id, exclude_file_id)}
