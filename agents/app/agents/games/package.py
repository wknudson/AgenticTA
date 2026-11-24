"""Unit packages: reading the unit, deterministic checks, saving the draft, publishing.

Used by the games graph (agent.py). Both generators (models.py and the no-AI extract.py)
produce the same draft shape:

    {"flashcards": [{front, back, source}],
     "fill_in":    [{sentence, answer, alternates, source}],
     "questions":  [{text, kind: "choice", options: [{text, correct}], source}
                    | {text, kind: "explain", answer, rubric, source}]}

Matching pairs are made from the reviewed flashcards when the draft is saved.
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from app.shared import library
from app.shared.db import connect

from .extract import MAX_GAME_ITEMS, MIN_CARDS, NotEnoughMaterial, Source, matching_from_cards

MAX_POINTS = 10
KINDS = ("flashcards", "matching", "fill_in")
ITEM_PREFIX = {"flashcards": "fc", "matching": "m", "fill_in": "f"}
STUDENT_FIELDS = {  # the contract's item shapes: everything else (source, review notes) stays teacher-side
    "flashcards": ("item_id", "front", "back"),
    "matching": ("item_id", "term", "definition"),
    "fill_in": ("item_id", "sentence", "answer", "alternates"),
}
KIND_TITLES = {"flashcards": "flashcards", "matching": "matching", "fill_in": "fill in the blank"}


# ---------------------------------------------------------------- reading the unit
def unit_sources(class_id: int, unit: str) -> tuple[list[Source], int]:
    """The unit's filed files that have text, plus how many more are waiting for review."""
    sources, waiting = [], 0
    for f in library.list_files(class_id, unit=unit):
        text = library.get_file_text(f.file_id).strip()
        if not text:
            continue
        if f.status == "filed":
            sources.append(Source(f.file_id, f.title or f.original_name, f.doc_type, text))
        else:
            waiting += 1
    return sources, waiting


def material_text(sources: list[Source]) -> str:
    return "\n".join(s.text for s in sources)


# ---------------------------------------------------------------- deterministic checks
_STOP = set("""about after also because been before being between both does each from have into just more most much
must only other over same some such than that their them then there these they this those through very what when
where which while will with would your""".split())


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4 and w not in _STOP}


def grounded(text: str, material_stems: set[str]) -> bool:
    """Most of an item's content words appear in the unit's material (cheap hallucination check)."""
    words = _stems(text)
    return len(words) < 2 or len(words & material_stems) / len(words) >= 0.5


def _visible(term: str, text: str) -> bool:
    return bool(term.strip()) and re.search(rf"\b{re.escape(term.strip())}\b", text, re.IGNORECASE) is not None


def check_draft(draft: dict[str, Any], material: str) -> list[dict[str, Any]]:
    """One verdict per item: {ref, ok, note}. Same checks for AI and no-AI drafts."""
    stems = _stems(material)
    out = []

    def verdict(ref: str, problems: list[str]) -> None:
        out.append({"ref": ref, "ok": not problems, "note": "; ".join(problems), "by": "checks"})

    for i, c in enumerate(draft.get("flashcards", []), 1):
        p = []
        if not c.get("front", "").strip() or not c.get("back", "").strip():
            p.append("empty side")
        elif _visible(c["front"], c["back"]):
            p.append("the back gives away the term")
        if c.get("back") and not grounded(c["back"], stems):
            p.append("not found in the unit's material")
        verdict(f"flashcards {i}", p)
    for i, f in enumerate(draft.get("fill_in", []), 1):
        p = []
        if "____" not in f.get("sentence", ""):
            p.append("no ____ blank")
        if not f.get("answer", "").strip():
            p.append("no answer")
        elif _visible(f["answer"], f.get("sentence", "").replace("____", " ")):
            p.append("the answer is visible in the sentence")
        if f.get("sentence") and not grounded(f["sentence"], stems):
            p.append("not found in the unit's material")
        verdict(f"fill_in {i}", p)
    for i, q in enumerate(draft.get("questions", []), 1):
        p = []
        if not q.get("text", "").strip():
            p.append("no question text")
        if q.get("kind") == "choice":
            opts = q.get("options") or []
            texts = [o.get("text", "").strip().lower() for o in opts]
            if not 3 <= len(opts) <= 4:
                p.append("needs 3-4 options")
            if sum(1 for o in opts if o.get("correct")) != 1:
                p.append("needs exactly one right option")
            if len(set(texts)) != len(texts) or "" in texts:
                p.append("options must be different and not empty")
            right = next((o["text"] for o in opts if o.get("correct")), "")
            if right and _visible(right, q.get("text", "")):
                p.append("the question gives away the answer")
        elif q.get("kind") == "explain":
            if not q.get("answer", "").strip() or not q.get("rubric", "").strip():
                p.append("needs a model answer and a rubric")
            elif not grounded(q["rubric"], stems):
                p.append("rubric not found in the unit's material")
        else:
            p.append("unknown question kind")
        verdict(f"questions {i}", p)
    return out


def combine(*verdict_lists: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """ref -> merged verdict: an item fails if any reviewer failed it."""
    merged: dict[str, dict[str, Any]] = {}
    for verdicts in verdict_lists:
        for v in verdicts:
            m = merged.setdefault(v["ref"], {"ref": v["ref"], "ok": True, "notes": []})
            if not v.get("ok", True):
                m["ok"] = False
                if v.get("note"):
                    m["notes"].append(f"{v.get('by', 'review')}: {v['note']}")
    return merged


def split_by_verdicts(draft: dict[str, Any], merged: dict[str, dict[str, Any]]) -> tuple[dict, list[dict]]:
    """(accepted draft, rejected items with the reason) for the regenerate loop."""
    accepted: dict[str, list] = {"flashcards": [], "fill_in": [], "questions": []}
    rejected = []
    for kind in accepted:
        for i, item in enumerate(draft.get(kind, []), 1):
            v = merged.get(f"{kind} {i}", {"ok": True, "notes": []})
            if v["ok"]:
                accepted[kind].append(item)
            else:
                rejected.append({"kind": kind, "item": item, "problem": "; ".join(v["notes"]) or "rejected"})
    return accepted, rejected


def counts(draft: dict[str, Any]) -> dict[str, int]:
    qs = draft.get("questions", [])
    return {"flashcards": len(draft.get("flashcards", [])), "fill_in": len(draft.get("fill_in", [])),
            "choice": sum(q.get("kind") == "choice" for q in qs), "explain": sum(q.get("kind") == "explain" for q in qs)}


def wanted(settings: dict[str, Any]) -> dict[str, int]:
    cards = int(settings["card_count"])
    return {"flashcards": cards, "fill_in": min(cards, MAX_GAME_ITEMS),
            "choice": int(settings["mc_count"]), "explain": int(settings["explain_count"])}


# ---------------------------------------------------------------- saving the draft
def _with_ids(kind: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"item_id": f"{ITEM_PREFIX[kind]}{i}", **{k: v for k, v in it.items() if k != "item_id"}}
            for i, it in enumerate(items, 1)]


def save_draft_package(class_id: int, unit: str, settings: dict[str, Any], draft: dict[str, Any],
                       review: dict[str, Any], generated_by: str, attempts: int) -> tuple[int, list[int]]:
    cards = draft["flashcards"]
    if len(cards) < MIN_CARDS:
        raise NotEnoughMaterial(f"Only {len(cards)} flashcard(s) passed review (need at least {MIN_CARDS}). "
                                "Add more notes to this unit in the Library and try again.")
    games = {"flashcards": cards, "matching": matching_from_cards(cards), "fill_in": draft["fill_in"]}
    questions = sorted(draft["questions"], key=lambda q: q["kind"] != "choice")  # MC first, then explain
    with connect() as conn:
        package_id = conn.execute(
            "INSERT INTO unit_packages (class_id, unit, settings_json, questions_json, review_json, generated_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (class_id, unit, json.dumps(settings), json.dumps(questions), json.dumps(review), generated_by)).lastrowid
        activity_ids = []
        for kind in KINDS:
            items = _with_ids(kind, games[kind])
            if not items:
                continue
            notes = [v for v in review.get("verdicts", []) if v.get("ref", "").startswith(kind)]
            activity_ids.append(conn.execute(
                "INSERT INTO study_activities (class_id, unit, kind, title, items_json, review_json, attempts, "
                "status, package_id) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?)",
                (class_id, unit, kind, f"{unit} {KIND_TITLES[kind]}", json.dumps(items), json.dumps(notes),
                 attempts, package_id)).lastrowid)
    return package_id, activity_ids


# ---------------------------------------------------------------- reading a package
def get_package(package_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM unit_packages WHERE package_id = ?", (package_id,)).fetchone()
        if row is None:
            return None
        acts = conn.execute("SELECT activity_id, kind, title, items_json, status FROM study_activities "
                            "WHERE package_id = ? ORDER BY activity_id", (package_id,)).fetchall()
    return {
        "package_id": row["package_id"], "class_id": row["class_id"], "unit": row["unit"], "status": row["status"],
        "settings": json.loads(row["settings_json"]), "generated_by": row["generated_by"],
        "activities": [{"activity_id": a["activity_id"], "kind": a["kind"], "title": a["title"],
                        "items": json.loads(a["items_json"])} for a in acts],
        "questions": json.loads(row["questions_json"] or "[]"),
        "assignment_id": row["assignment_id"],
        "review": json.loads(row["review_json"] or "{}"),
        "created_at": row["created_at"],
    }


def summary(pkg: dict[str, Any]) -> dict[str, Any]:
    by_kind = {a["kind"]: len(a["items"]) for a in pkg["activities"]}
    qs = pkg["questions"]
    return {"flashcards": by_kind.get("flashcards", 0), "matching": by_kind.get("matching", 0),
            "fill_in": by_kind.get("fill_in", 0), "mc": sum(q["kind"] == "choice" for q in qs),
            "explain": sum(q["kind"] == "explain" for q in qs), "generated_by": pkg["generated_by"]}


def approval_description(p: dict[str, Any]) -> str:
    """The Approvals inbox headline for publish_unit_package (refreshed when the teacher edits)."""
    s, n = p["settings"], summary(p)
    built_by = "the no-AI generator" if n["generated_by"] == "offline" else f"{n['generated_by']}, checked by a reviewer"
    return (f"Publish \"{s['title']}\" ({p['unit']}) to students? Games: {n['flashcards']} flashcards, "
            f"{n['matching']} matching pairs, {n['fill_in']} fill-in sentences. Check-in: {n['mc']} multiple "
            f"choice + {n['explain']} explain-why questions, unlocked at {round(100 * s['mastery_threshold'])}% "
            f"mastery. Due {s.get('due_day') or s['due_date'][:10]} for the {s['lesson_date']} lesson. Built by {built_by}.")


def student_items(kind: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only the contract fields: no review notes or sources go to students."""
    fields = STUDENT_FIELDS.get(kind)
    if not fields:
        return []
    out = []
    for it in items:
        if not it.get("item_id"):
            continue
        clean = {k: it[k] for k in fields if k in it}
        if kind == "fill_in":
            clean.setdefault("alternates", [])
        out.append(clean)
    return out


# ---------------------------------------------------------------- publish / reject
def _points(n: int) -> list[float]:
    """MAX_POINTS split over n questions in cents, so the parts add up exactly."""
    cents = MAX_POINTS * 100
    base, extra = divmod(cents, n)
    return [(base + (1 if i < extra else 0)) / 100 for i in range(n)]


def _calendar_problem(conn: sqlite3.Connection, class_id: int, day: date) -> str | None:
    """The scheduler's rules for a published due date (same as scheduler/calendar.py, read by SQL
    because agents don't import each other): school day, inside the term, not a holiday, and not
    over the per-day limit of assessments and due dates."""
    if day.weekday() >= 5:
        return f"{day:%A} {day.isoformat()} is a weekend"
    try:
        term = conn.execute("SELECT * FROM term_calendar WHERE class_id = ?", (class_id,)).fetchone()
    except sqlite3.OperationalError:
        term = None
    if term is None:
        return None
    iso = day.isoformat()
    if not term["term_start"] <= iso <= term["term_end"]:
        return f"{iso} is outside the term ({term['term_start']} to {term['term_end']})"
    holidays = {h["date"]: h.get("label", "Holiday") for h in json.loads(term["holidays_json"] or "[]")}
    if iso in holidays:
        return f"{iso} is a holiday ({holidays[iso]})"
    busy = conn.execute("SELECT COUNT(*) FROM calendar_events WHERE class_id = ? AND status = 'published' "
                        "AND date = ? AND kind IN ('assessment', 'assignment_due')", (class_id, iso)).fetchone()[0]
    if busy + 1 > term["max_assessments_per_day"]:
        return f"{iso} already has {busy} assessment(s)/due date(s) (max {term['max_assessments_per_day']})"
    return None


def publish(package_id: int) -> dict[str, Any]:
    """Approved: the check-in assignment, its questions and options, the games and (when the due
    date passes the scheduler's rules) the calendar event, all in one transaction."""
    with connect() as conn:
        # Take the write lock before checking the status, so two approvals at once (two tabs)
        # can't both see "draft" and publish two assignments.
        conn.execute("BEGIN IMMEDIATE")
        pkg = conn.execute("SELECT * FROM unit_packages WHERE package_id = ?", (package_id,)).fetchone()
        if pkg is None:
            raise LookupError(f"Unit package {package_id} not found")
        if pkg["status"] != "draft":
            return {"assignment_id": pkg["assignment_id"], "status": pkg["status"], "calendar_event_id": None,
                    "calendar_note": f"Package was already {pkg['status']}; nothing changed."}
        s = json.loads(pkg["settings_json"])
        questions = json.loads(pkg["questions_json"] or "[]")
        class_id, unit = pkg["class_id"], pkg["unit"]
        types = sorted({"multiple_choice" if q["kind"] == "choice" else "short_answer" for q in questions})
        assignment_id = conn.execute(
            """INSERT INTO assignments (class_id, assignment_name, description, type, max_points, due_date,
                   assignment_link, question_types, allowed_submissions, mode, unit, tutor_mode, tutor_reveal_after,
                   mastery_threshold, lesson_date)
               VALUES (?, ?, ?, 'Homework', ?, ?, ?, ?, 1, 'checkin', ?, ?, ?, ?, ?)""",
            (class_id, s["title"], f"Practice games and a check-in for {unit}, before the {s['lesson_date']} lesson.",
             MAX_POINTS, s["due_date"], secrets.token_hex(8), ",".join(types), unit, s["tutor_mode"],
             s["tutor_reveal_after"], s["mastery_threshold"], s["lesson_date"])).lastrowid
        for order, (q, points) in enumerate(zip(questions, _points(max(1, len(questions)))), 1):
            if q["kind"] == "choice":
                qid = conn.execute("INSERT INTO assignment_questions (assignment_id, sort_order, question_text, "
                                   "question_type, max_points) VALUES (?, ?, ?, 'multiple_choice', ?)",
                                   (assignment_id, order, q["text"], points)).lastrowid
                correct_id = None
                for opt in q["options"]:
                    oid = conn.execute("INSERT INTO assignment_question_options (question_id, option_text, is_correct) "
                                       "VALUES (?, ?, ?)", (qid, opt["text"], int(bool(opt["correct"])))).lastrowid
                    if opt["correct"]:
                        correct_id = oid
            else:
                qid = conn.execute("INSERT INTO assignment_questions (assignment_id, sort_order, question_text, "
                                   "question_type, max_points, explain_rubric) VALUES (?, ?, ?, 'short_answer', ?, ?)",
                                   (assignment_id, order, q["text"], points, q["rubric"])).lastrowid
                correct_id = conn.execute("INSERT INTO assignment_question_options (question_id, option_text, "
                                          "is_correct) VALUES (?, ?, 1)", (qid, q["answer"])).lastrowid
            # Same as backend/routes/classes.ts: correct_answer holds the right option's id.
            conn.execute("UPDATE assignment_questions SET correct_answer = ? WHERE question_id = ?",
                         (str(correct_id), qid))
        conn.execute("UPDATE study_activities SET status = 'published', assignment_id = ? "
                     "WHERE package_id = ? AND status = 'draft'", (assignment_id, package_id))
        conn.execute("UPDATE unit_packages SET status = 'published', assignment_id = ? WHERE package_id = ?",
                     (assignment_id, package_id))

        due_day = date.fromisoformat(s.get("due_day") or s["due_date"][:10])
        problem = _calendar_problem(conn, class_id, due_day)
        event_id = None
        if problem is None:
            event_id = conn.execute(
                "INSERT INTO calendar_events (class_id, title, kind, date, assignment_id, source, status) "
                "VALUES (?, ?, 'assignment_due', ?, ?, 'unit package', 'published')",
                (class_id, f"{s['title']} due", due_day.isoformat(), assignment_id)).lastrowid
            note = f"Calendar: added \"{s['title']} due\" on {due_day.isoformat()}."
        else:
            note = f"Calendar: no event added because {problem}. Add it from the Scheduler if you want it there."
    return {"assignment_id": assignment_id, "status": "published", "questions": len(questions),
            "calendar_event_id": event_id, "calendar_note": note}


def reject(package_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE unit_packages SET status = 'rejected' WHERE package_id = ? AND status = 'draft'",
                     (package_id,))
        conn.execute("UPDATE study_activities SET status = 'rejected' WHERE package_id = ? AND status = 'draft'",
                     (package_id,))


# ---------------------------------------------------------------- dates
def normalize_due(due: str | None, lesson: date) -> str:
    """Express-style ISO timestamp. Default: the evening before the lesson (23:59)."""
    if not due:
        return f"{date.fromordinal(lesson.toordinal() - 1).isoformat()}T23:59:00.000Z"
    due = due.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
        return f"{date.fromisoformat(due).isoformat()}T23:59:00.000Z"
    parsed = datetime.fromisoformat(due.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
