"""Editing a draft unit package before the teacher approves it.

    PATCH /unit-package/{id}             apply_edits(): questions, game items and/or settings
    POST  /unit-package/{id}/regenerate  regenerate(): replace one question or one game item

Only drafts change (NotDraft -> 409): once a package is published, students' progress points
at its items. Hard rules fail the whole edit (EditError -> 422, one readable message). The same
deterministic checks a generated draft gets (package.check_draft) come back as warnings, and are
kept in the package's review as `edit_warnings` so the editor can show them again later.

Publishing reads the DB (package.publish, and the graph re-reads the package when the approval
resumes), so whatever is saved here is exactly what students get.

Regenerate: the model path (models.py, one generator call) when the games agent has keys and
the package wasn't drafted with offline=true; on any model error, or without keys, the next
unused candidate from the no-AI generator (extract.candidate_pool). That path is deterministic:
the package's current items and everything replaced before are skipped, so repeated clicks walk
forward through the pool and end in a friendly 409 instead of cycling.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from app.shared.db import connect

from . import models as ai
from . import package as pkg
from .extract import MIN_CARDS, candidate_pool, norm_term

MAX_QUESTIONS = 30
MAX_OPTIONS = 6
MAX_ITEMS = 40            # per game
MAX_ALTERNATES = 10
LIMIT = {"question": 1000, "option": 300, "answer": 2000, "item": 600, "alternate": 100}
TUTOR_MODES = ("hints_only", "answer_after_tries")

ITEM_FIELDS = {"flashcards": ("front", "back"), "matching": ("term", "definition"), "fill_in": ("sentence", "answer")}
ITEM_LABEL = {"flashcards": "Flashcard", "matching": "Matching pair", "fill_in": "Fill-in sentence"}
GAME_TITLE = {"flashcards": "Flashcards", "matching": "Matching", "fill_in": "Fill in the blank"}
BUCKET_NAME = {"choice": "multiple-choice question", "explain": "explain-why question", "flashcards": "flashcard",
               "matching": "matching pair", "fill_in": "fill-in sentence"}
POOL = {"choice": "choice", "explain": "explain", "flashcards": "cards", "matching": "cards", "fill_in": "fill_in"}
NEED = {"choice": {"choice": 1}, "explain": {"explain": 1}, "flashcards": {"flashcards": 1},
        "matching": {"flashcards": 1}, "fill_in": {"fill_in": 1}}


class NotFound(LookupError):
    """-> 404"""


class Conflict(Exception):
    """-> 409"""


class NotDraft(Conflict):
    pass


class NoCandidate(Conflict):
    pass


class EditError(ValueError):
    """-> 422 with every problem in one message (the first few, if there are many)."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        shown = " ".join(problems[:6])
        more = f" (and {len(problems) - 6} more)" if len(problems) > 6 else ""
        super().__init__(f"Can't save yet. {shown}{more}")


# ---------------------------------------------------------------- small helpers
def _text(v: Any) -> str:
    if v is None:
        return ""
    return (v if isinstance(v, str) else str(v)).strip()


def _norm_text(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").lower()).strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _require_draft(status: str) -> None:
    if status != "draft":
        raise NotDraft(f"This package is already {status}, so it can't be changed. To change a published "
                       "check-in, draft a new one for the unit.")


def _activities(conn: sqlite3.Connection, package_id: int) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT activity_id, kind, items_json FROM study_activities WHERE package_id = ? "
                        "ORDER BY activity_id", (package_id,)).fetchall()
    return [{"activity_id": r["activity_id"], "kind": r["kind"], "items": json.loads(r["items_json"] or "[]")}
            for r in rows]


def _material(class_id: int, unit: str) -> str:
    return pkg.material_text(pkg.unit_sources(class_id, unit)[0])


# ---------------------------------------------------------------- hard rules
def clean_question(q: dict[str, Any], label: str) -> tuple[dict[str, Any], list[str]]:
    """One question in the stored shape, plus what's wrong with it."""
    p: list[str] = []
    text, kind = _text(q.get("text")), q.get("kind")
    source = _text(q.get("source")) or "teacher"
    if not text:
        p.append(f"{label}: write the question.")
    elif len(text) > LIMIT["question"]:
        p.append(f"{label}: the question is too long (max {LIMIT['question']} characters).")
    if kind == "choice":
        opts = [{"text": _text(o.get("text")), "correct": bool(o.get("correct"))}
                for o in (q.get("options") or []) if isinstance(o, dict)]
        if len(opts) < 2:
            p.append(f"{label}: give it at least 2 answer options.")
        elif len(opts) > MAX_OPTIONS:
            p.append(f"{label}: use at most {MAX_OPTIONS} answer options.")
        if any(not o["text"] for o in opts):
            p.append(f"{label}: an answer option is empty.")
        if any(len(o["text"]) > LIMIT["option"] for o in opts):
            p.append(f"{label}: an answer option is too long (max {LIMIT['option']} characters).")
        right = sum(o["correct"] for o in opts)
        if opts and right == 0:
            p.append(f"{label}: mark which option is the right answer.")
        elif right > 1:
            p.append(f"{label}: only one option can be the right answer.")
        return {"text": text, "kind": "choice", "options": opts, "source": source}, p
    if kind == "explain":
        answer, rubric = _text(q.get("answer")), _text(q.get("rubric"))
        if not answer:
            p.append(f"{label}: write a model answer.")
        if len(answer) > LIMIT["answer"] or len(rubric) > LIMIT["answer"]:
            p.append(f"{label}: the model answer or rubric is too long (max {LIMIT['answer']} characters).")
        return {"text": text, "kind": "explain", "answer": answer, "rubric": rubric, "source": source}, p
    p.append(f"{label}: the kind must be \"choice\" or \"explain\".")
    return {"text": text, "kind": kind, "source": source}, p


def clean_questions(raw: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    problems: list[str] = []
    if not raw:
        problems.append("Keep at least one check-in question.")
    elif len(raw) > MAX_QUESTIONS:
        problems.append(f"A check-in can have at most {MAX_QUESTIONS} questions.")
    out = []
    for i, q in enumerate(raw, 1):
        clean, p = clean_question(q, f"Question {i}")
        out.append(clean)
        problems += p
    return out, problems


def clean_item(kind: str, raw: dict[str, Any], label: str) -> tuple[dict[str, Any], list[str]]:
    """One game item's content fields (no item_id / source), plus what's wrong with it."""
    a, b = ITEM_FIELDS[kind]
    va, vb = _text(raw.get(a)), _text(raw.get(b))
    if kind == "fill_in":
        va = re.sub(r"_{3,}", "____", va)          # "___" or "______" -> the player's blank
    p: list[str] = []
    missing = [name for name, v in ((a, va), (b, vb)) if not v]
    if missing:
        p.append(f"{label}: fill in the {' and the '.join(missing)}.")
    if len(va) > LIMIT["item"] or len(vb) > LIMIT["item"]:
        p.append(f"{label}: too long (max {LIMIT['item']} characters per side).")
    item: dict[str, Any] = {a: va, b: vb}
    if kind == "fill_in":
        if va and "____" not in va:
            p.append(f"{label}: the sentence needs a blank, written ____, where the answer goes.")
        alts = raw.get("alternates") or []
        if isinstance(alts, str):
            alts = alts.split(",")
        clean: list[str] = []
        for x in alts if isinstance(alts, list) else []:
            t = _text(x)
            if t and t.lower() != vb.lower() and t.lower() not in (c.lower() for c in clean):
                clean.append(t)
        if len(clean) > MAX_ALTERNATES or any(len(c) > LIMIT["alternate"] for c in clean):
            p.append(f"{label}: keep it to {MAX_ALTERNATES} short accepted answers.")
        item["alternates"] = clean
    return item, p


def _id_number(item_id: str, prefix: str) -> int:
    m = re.fullmatch(rf"{re.escape(prefix)}(\d+)", item_id or "")
    return int(m.group(1)) if m else 0


def clean_items(kind: str, raw: list[dict[str, Any]], existing: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """The edited item list. Items that send an item_id the game already has keep it (and their
    source); everything else gets a fresh id never used in this game before (fc11, fc12 ...)."""
    if kind not in ITEM_FIELDS:
        return existing, [f"This package has a game of an unknown kind ({kind}); it can't be edited."]
    problems: list[str] = []
    if len(raw) > MAX_ITEMS:
        problems.append(f"{GAME_TITLE[kind]}: at most {MAX_ITEMS} cards per game.")
    prefix = pkg.ITEM_PREFIX[kind]
    prev = {it["item_id"]: it for it in existing if isinstance(it.get("item_id"), str)}
    taken, used = set(prev), set()
    out: list[dict[str, Any]] = []
    for i, r in enumerate(raw, 1):
        r = r if isinstance(r, dict) else {}
        fields, p = clean_item(kind, r, f"{ITEM_LABEL[kind]} {i}")
        problems += p
        iid = r.get("item_id")
        old = prev.get(iid) if isinstance(iid, str) and iid not in used else None
        if old is not None:
            used.add(iid)
            out.append({"item_id": iid, **fields, "source": _text(r.get("source")) or old.get("source") or "teacher"})
        else:
            out.append({"item_id": None, **fields, "source": _text(r.get("source")) or "teacher"})
    n = 1 + max([_id_number(t, prefix) for t in taken] + [0])
    for item in out:
        if item["item_id"] is None:
            while f"{prefix}{n}" in taken:
                n += 1
            item["item_id"] = f"{prefix}{n}"
            taken.add(item["item_id"])
    return out, problems


def clean_settings(current: dict[str, Any], edits: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Title, dates, tutor mode and the mastery bar. Moving the lesson without a due date moves
    the due date to its default (the evening before, like POST /unit-package)."""
    s, p = dict(current), []
    if "title" in edits:
        t = _text(edits["title"])
        if not t:
            p.append("Settings: the title can't be empty.")
        elif len(t) > 200:
            p.append("Settings: the title is too long (max 200 characters).")
        else:
            s["title"] = t
    if "tutor_mode" in edits:
        if edits["tutor_mode"] not in TUTOR_MODES:
            p.append("Settings: the tutor mode must be \"hints_only\" or \"answer_after_tries\".")
        else:
            s["tutor_mode"] = edits["tutor_mode"]
    if "tutor_reveal_after" in edits:
        n = edits["tutor_reveal_after"]
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 10:
            p.append("Settings: honest tries before the tutor explains must be 1 to 10.")
        else:
            s["tutor_reveal_after"] = n
    if "mastery_threshold" in edits:
        v = edits["mastery_threshold"]
        ok = isinstance(v, (int, float)) and not isinstance(v, bool)
        if ok and 1 < v <= 100:
            v = v / 100                              # 80 -> 0.8
        if not ok or not 0 < v <= 1:
            p.append("Settings: the mastery threshold must be between 1% and 100%.")
        else:
            s["mastery_threshold"] = float(v)
    if {"lesson_date", "due_date", "due_day"} & set(edits):
        try:
            lesson = date.fromisoformat(_text(edits.get("lesson_date")) or s["lesson_date"])
        except ValueError:
            return s, p + ["Settings: the lesson date must be YYYY-MM-DD."]
        due_moved = False
        if _text(edits.get("due_date")):
            try:
                s["due_date"] = pkg.normalize_due(_text(edits["due_date"]), lesson)
                due_moved = True
            except ValueError:
                p.append("Settings: the due date must be YYYY-MM-DD or an ISO date-time.")
        elif "lesson_date" in edits and lesson.isoformat() != s["lesson_date"]:
            s["due_date"] = pkg.normalize_due(None, lesson)
            due_moved = True
        s["lesson_date"] = lesson.isoformat()
        if _text(edits.get("due_day")):
            try:
                s["due_day"] = date.fromisoformat(_text(edits["due_day"])).isoformat()
            except ValueError:
                p.append("Settings: due_day must be YYYY-MM-DD.")
        elif due_moved:
            s["due_day"] = s["due_date"][:10]
        if (s.get("due_day") or s["due_date"][:10]) > s["lesson_date"]:
            p.append("Settings: the due date should be on or before the lesson date.")
    return s, p


# ---------------------------------------------------------------- warnings (soft checks)
def package_warnings(questions: list[dict[str, Any]], activities: list[dict[str, Any]],
                     material: str) -> list[dict[str, Any]]:
    """package.check_draft on the whole package, as
    {target: "question"|"item"|"activity", index? (0-based question), activity_id?, item_id?, label, note}."""
    out: list[dict[str, Any]] = []
    seen_q: dict[str, int] = {}
    for v in pkg.check_draft({"questions": questions}, material):
        if not v["ok"]:
            n = int(v["ref"].rsplit(" ", 1)[1])
            out.append({"target": "question", "index": n - 1, "label": f"Question {n}", "note": v["note"]})
    for i, q in enumerate(questions, 1):
        key = _norm_text(q.get("text", ""))
        if key and key in seen_q:
            out.append({"target": "question", "index": i - 1, "label": f"Question {i}",
                        "note": f"same question as question {seen_q[key]}"})
        seen_q.setdefault(key, i)
    for a in activities:
        kind, items = a["kind"], a["items"]
        if kind not in ITEM_FIELDS:
            continue
        if not items:
            out.append({"target": "activity", "activity_id": a["activity_id"], "label": GAME_TITLE[kind],
                        "note": "no cards left, so students won't see this game"})
            continue
        if kind == "fill_in":
            draft = {"fill_in": items}
        else:
            front, back = ITEM_FIELDS[kind]
            draft = {"flashcards": [{"front": it.get(front, ""), "back": it.get(back, "")} for it in items]}
        for v in pkg.check_draft(draft, material):
            if not v["ok"]:
                n = int(v["ref"].rsplit(" ", 1)[1])
                out.append({"target": "item", "activity_id": a["activity_id"], "item_id": items[n - 1].get("item_id"),
                            "label": f"{ITEM_LABEL[kind]} {n}", "note": v["note"]})
        if kind != "fill_in":
            seen: dict[str, int] = {}
            for n, it in enumerate(items, 1):
                key = norm_term(it.get(ITEM_FIELDS[kind][0], ""))
                if key and key in seen:
                    out.append({"target": "item", "activity_id": a["activity_id"], "item_id": it.get("item_id"),
                                "label": f"{ITEM_LABEL[kind]} {n}", "note": f"same term as card {seen[key]}"})
                seen.setdefault(key, n)
    return out


def _refresh_approval(package_id: int) -> None:
    """Keep the Approvals inbox headline (counts, title, dates) in step with the edits."""
    p = pkg.get_package(package_id)
    if p is None:
        return
    try:
        with connect() as conn:
            conn.execute("UPDATE approvals SET description = ? WHERE agent = 'games' AND status = 'pending' "
                         "AND action_name = 'publish_unit_package' AND json_extract(action_args, '$.package_id') = ?",
                         (pkg.approval_description(p), package_id))
    except sqlite3.Error:
        pass  # only the headline; the package itself is saved


# ---------------------------------------------------------------- PATCH
def apply_edits(package_id: int, *, questions: list[dict[str, Any]] | None = None,
                activities: list[dict[str, Any]] | None = None,
                settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Save the teacher's edits to a draft. Returns {package, warnings}."""
    current = pkg.get_package(package_id)
    if current is None:
        raise NotFound("Unit package not found")
    _require_draft(current["status"])
    material = _material(current["class_id"], current["unit"])
    with connect() as conn:
        # Under the write lock, so an approval can't publish halfway through an edit.
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM unit_packages WHERE package_id = ?", (package_id,)).fetchone()
        _require_draft(row["status"])
        acts = _activities(conn, package_id)
        by_id = {a["activity_id"]: a for a in acts}
        problems: list[str] = []

        new_q = None
        if questions is not None:
            new_q, p = clean_questions(questions)
            problems += p
        new_items: dict[int, list[dict[str, Any]]] = {}
        for edit in activities or []:
            aid = edit.get("activity_id")
            act = by_id.get(aid)
            if act is None:
                problems.append(f"Game {aid} isn't part of this package.")
                continue
            if aid in new_items:
                problems.append(f"{GAME_TITLE.get(act['kind'], act['kind'])} is listed twice.")
                continue
            items, p = clean_items(act["kind"], list(edit.get("items") or []), act["items"])
            new_items[aid] = items
            problems += p
        total = sum(len(new_items.get(a["activity_id"], a["items"])) for a in acts)
        if total < MIN_CARDS:
            problems.append(f"Keep at least {MIN_CARDS} practice cards across the games (this leaves {total}).")
        new_s = None
        if settings:
            new_s, p = clean_settings(json.loads(row["settings_json"]), settings)
            problems += p
        if problems:
            raise EditError(problems)

        final_q = new_q if new_q is not None else json.loads(row["questions_json"] or "[]")
        for a in acts:
            a["items"] = new_items.get(a["activity_id"], a["items"])
        warnings = package_warnings(final_q, acts, material)
        review = json.loads(row["review_json"] or "{}")
        review.update(edited_at=_now(), edit_warnings=warnings)

        if new_q is not None:
            conn.execute("UPDATE unit_packages SET questions_json = ? WHERE package_id = ?",
                         (json.dumps(new_q), package_id))
        for aid, items in new_items.items():
            conn.execute("UPDATE study_activities SET items_json = ? WHERE activity_id = ? AND package_id = ?",
                         (json.dumps(items), aid, package_id))
        if new_s is not None:
            conn.execute("UPDATE unit_packages SET settings_json = ? WHERE package_id = ?",
                         (json.dumps(new_s), package_id))
        conn.execute("UPDATE unit_packages SET review_json = ? WHERE package_id = ?", (json.dumps(review), package_id))
    _refresh_approval(package_id)
    return {"package": pkg.get_package(package_id), "warnings": warnings}


# ---------------------------------------------------------------- regenerate
def _keys(bucket: str, item: dict[str, Any]) -> set[str]:
    """What makes two items 'the same' for regenerate: the term, the answer, or the question."""
    if bucket in ITEM_FIELDS:
        field = {"flashcards": "front", "matching": "term", "fill_in": "answer"}[bucket]
        keys = {norm_term(_text(item.get(field)))}
    else:
        keys = {_norm_text(_text(item.get("text")))}
        right = next((o.get("text", "") for o in item.get("options") or [] if o.get("correct")), "")
        if bucket == "choice" and right.strip():
            keys.add("answer:" + norm_term(right))
    return keys - {""}


def _taken(bucket: str, p: dict[str, Any], act: dict[str, Any] | None) -> set[str]:
    if act is not None:
        return set().union(*(_keys(bucket, it) for it in act["items"]))
    return set().union(*(_keys(q.get("kind", "explain"), q) for q in p["questions"]))


def _offline_candidate(sources: list[Any], bucket: str, taken: set[str], unit: str) -> dict[str, Any]:
    if not sources:
        raise NoCandidate(f"\"{unit}\" has no filed text any more, so there's nothing to draw a new "
                          f"{BUCKET_NAME[bucket]} from. Edit this one by hand or delete it.")
    for c in candidate_pool(sources)[POOL[bucket]]:
        cand = {"term": c["front"], "definition": c["back"], "source": c["source"]} if bucket == "matching" else dict(c)
        if not _keys(bucket, cand) & taken:
            return cand
    raise NoCandidate(f"No more no-AI suggestions for this {BUCKET_NAME[bucket]}: everything the generator found "
                      f"in \"{unit}\" is already in the package or was replaced before. Edit it by hand or delete it.")


def _model_candidate(sources: list[Any], unit: str, bucket: str, old: dict[str, Any],
                     act: dict[str, Any] | None, taken: set[str]) -> dict[str, Any]:
    """One generator call for one item; anything unusable raises (the caller falls back)."""
    avoid = None
    if act is not None and bucket in ("flashcards", "matching"):
        avoid = [_text(it.get(ITEM_FIELDS[bucket][0])) for it in act["items"]]
    shown = {"front": old.get("front") or old.get("term"), "sentence": old.get("sentence"), "text": old.get("text")}
    rejected = [{"kind": bucket, "item": {k: v for k, v in shown.items() if v},
                 "problem": "the teacher asked for a different one"}]
    draft = ai.generate_package(sources, unit, dict(NEED[bucket]), avoid=avoid, rejected=rejected)
    if bucket in ("choice", "explain"):
        cand, problems = clean_question(next(q for q in draft["questions"] if q.get("kind") == bucket), "AI question")
    else:
        raw = draft["fill_in"][0] if bucket == "fill_in" else draft["flashcards"][0]
        if bucket == "matching":
            raw = {"term": raw["front"], "definition": raw["back"], "source": raw.get("source")}
        fields, problems = clean_item(bucket, raw, "AI card")
        cand = {**fields, "source": _text(raw.get("source")) or "AI"}
    if problems:
        raise ValueError("; ".join(problems))
    if _keys(bucket, cand) & taken:
        raise ValueError("the model repeated something already in the package")
    return cand


def regenerate(package_id: int, *, kind: str, index: int | None = None, activity_id: int | None = None,
               item_id: str | None = None, offline: bool | None = None) -> dict[str, Any]:
    """Replace one question (by index) or one game item (activity_id + item_id). Returns
    {package, warnings, replaced:{...}, generated_by, note}."""
    p = pkg.get_package(package_id)
    if p is None:
        raise NotFound("Unit package not found")
    _require_draft(p["status"])
    act, pos = None, None
    if kind == "question":
        if index is None:
            raise EditError(["Say which question to regenerate (index)."])
        if not 0 <= index < len(p["questions"]):
            raise NotFound(f"Question {index + 1} isn't in this package.")
        old = p["questions"][index]
        bucket = old.get("kind")
        if bucket not in ("choice", "explain"):
            raise EditError([f"Question {index + 1} has an unknown kind."])
    elif kind == "item":
        act = next((a for a in p["activities"] if a["activity_id"] == activity_id), None)
        if act is None:
            raise NotFound("That game isn't part of this package.")
        pos = next((i for i, it in enumerate(act["items"]) if it.get("item_id") == item_id), None)
        if pos is None:
            raise NotFound(f"Card {item_id} isn't in that game.")
        old, bucket = act["items"][pos], act["kind"]
        if bucket not in ITEM_FIELDS:
            raise EditError(["That game can't be regenerated."])
    else:
        raise EditError(["kind must be \"question\" or \"item\"."])

    sources, _ = pkg.unit_sources(p["class_id"], p["unit"])
    history = (p.get("review") or {}).get("replaced") or {}
    taken = _taken(bucket, p, act) | set(history.get(bucket, []))
    use_offline = bool(p["settings"].get("offline")) if offline is None else offline
    new, generated_by, note = None, "offline", None
    if not use_offline and sources and ai.models_ready():
        try:
            new = _model_candidate(sources, p["unit"], bucket, old, act, taken)
            generated_by = ai.generator_name()
        except Exception as exc:  # outage, quota, unusable output: the no-AI path instead
            note = f"AI regeneration failed ({type(exc).__name__}); used the no-AI generator instead."
    if new is None:
        new = _offline_candidate(sources, bucket, taken, p["unit"])
    if act is not None:
        new = {"item_id": old["item_id"], **new}
    material = pkg.material_text(sources)

    changed = Conflict("The package changed while the replacement was being written. Reload it and try again.")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM unit_packages WHERE package_id = ?", (package_id,)).fetchone()
        _require_draft(row["status"])
        questions = json.loads(row["questions_json"] or "[]")
        acts = _activities(conn, package_id)
        if act is None:
            if index >= len(questions) or questions[index] != old:
                raise changed
            questions[index] = new
            conn.execute("UPDATE unit_packages SET questions_json = ? WHERE package_id = ?",
                         (json.dumps(questions), package_id))
        else:
            target = next((a for a in acts if a["activity_id"] == activity_id), None)
            if target is None or pos >= len(target["items"]) or target["items"][pos] != old:
                raise changed
            target["items"][pos] = new
            conn.execute("UPDATE study_activities SET items_json = ? WHERE activity_id = ? AND package_id = ?",
                         (json.dumps(target["items"]), activity_id, package_id))
        review = json.loads(row["review_json"] or "{}")
        replaced = review.setdefault("replaced", {})
        replaced[bucket] = sorted(set(replaced.get(bucket, [])) | _keys(bucket, old))
        warnings = package_warnings(questions, acts, material)
        review.update(edited_at=_now(), edit_warnings=warnings)
        conn.execute("UPDATE unit_packages SET review_json = ? WHERE package_id = ?", (json.dumps(review), package_id))
    ref = {"kind": "question", "index": index} if act is None else \
        {"kind": "item", "activity_id": activity_id, "item_id": old["item_id"]}
    return {"package": pkg.get_package(package_id), "warnings": warnings, "replaced": ref,
            "generated_by": generated_by, "note": note}
