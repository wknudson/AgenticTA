"""Tutor agent: the student check-in (docs/flipped-classroom-plan.md, sections 4 and 5, and the
"Tutor agent" table in the appendix). Owner: Will.

    GET  /agents/tutor/checkin/{assignment_id}                    state: practice, unlock, questions, signals
    POST /agents/tutor/checkin/{assignment_id}/answer             first answer to a question
    POST /agents/tutor/checkin/{assignment_id}/fix                fix a miss: right answer + own-words explanation
    POST /agents/tutor/checkin/{assignment_id}/chat               talk to the tutor about one question
    GET  /agents/tutor/checkin/{assignment_id}/chat/{question_id} that conversation

Teacher (no student token, like the other teacher routes of this service; checkin_settings.py):
    GET   /agents/tutor/checkin/{assignment_id}/settings          title, dates, tutor mode, threshold
    PATCH /agents/tutor/checkin/{assignment_id}/settings          change them (moves the calendar entry)

Every student route needs the student's Express JWT (Authorization: Bearer ...). Every state
change goes through app/shared/checkin.py. No response ever includes the right answer.

Database work is split around model calls (load, then call the model with no connection open,
then write), so a slow model never holds a SQLite write lock.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from app.shared import checkin as ck
from app.shared.agent_router import make_router
from app.shared.db import connect
from app.shared.student_auth import checkin_for_student, current_student
from app.shared.tracing import agent_trace

from . import checkin_settings as cs
from . import tutor
from .judge import COPIED, JUST_THE_QUESTION, NOT_YET, copies_answer, copies_question, judge
from .models import offline_mode
from .questions import MULTI_TYPES, Question, get_question, public_question, public_questions

router = make_router("tutor")

MAX_MESSAGE_CHARS = 2000


class AnswerIn(BaseModel):
    question_id: int
    option_id: int | None = None
    option_ids: list[int] | None = None  # select-all questions only (Q.multi)
    text: str | None = None


class FixIn(BaseModel):
    question_id: int
    option_id: int | None = None
    option_ids: list[int] | None = None
    explanation: str = ""


class ChatIn(BaseModel):
    question_id: int
    message: str = ""


# ---------------------------------------------------------------- helpers
def _past(iso: str | None) -> bool:
    if not iso:
        return False
    try:
        due = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) > (due if due.tzinfo else due.replace(tzinfo=timezone.utc))


def _assignment_out(a: dict[str, Any]) -> dict[str, Any]:
    return {"assignment_id": a["assignment_id"], "title": a["assignment_name"], "unit": a.get("unit"),
            "tutor_mode": a.get("tutor_mode"), "tutor_reveal_after": a.get("tutor_reveal_after"),
            "due_date": a.get("due_date"), "lesson_date": a.get("lesson_date"), "max_points": a.get("max_points"),
            "past_due": _past(a.get("due_date"))}


def _require_unlocked(conn, student_id: int, assignment_id: int) -> None:
    stats = ck.practice_stats(conn, student_id, assignment_id)
    if not stats["unlocked"]:
        raise HTTPException(403, f"Finish practice first: the check-in unlocks at {round(100 * stats['threshold'])}% "
                                 f"mastery (you're at {round(100 * stats['mastery'])}%).")


def _bad(exc: ValueError) -> HTTPException:
    """A state conflict (already answered, nothing to fix): 409, so a stale tab reloads."""
    return HTTPException(409, str(exc))


def _not_honest(reason: str | None) -> HTTPException:
    return HTTPException(422, reason or "Give it a real try in your own words.")


def _load(student_id: int, assignment_id: int, question_id: int) -> tuple[dict, Question, dict]:
    """(assignment, question, status) for a write, after auth, due date and unlock checks."""
    a = checkin_for_student(student_id, assignment_id, writing=True)
    with connect() as conn:
        _require_unlocked(conn, student_id, assignment_id)
        try:
            q = get_question(conn, assignment_id, question_id)
            st = ck.get_status(conn, student_id, assignment_id, question_id)
        except ValueError as e:
            raise _bad(e)
    return a, q, st


def _chosen(q: Question, option_id: int | None, option_ids: list[int] | None) -> list[dict] | None:
    """The chosen option(s), or None if nothing was picked. 400 for an option of another question."""
    ids = list(dict.fromkeys(option_ids or [])) if q.question_type in MULTI_TYPES else []
    if not ids and option_id is not None:
        ids = [option_id]
    if not ids:
        return None
    chosen = [q.option(i) for i in ids]
    if any(o is None for o in chosen):
        raise HTTPException(400, "That option isn't part of this question.")
    return chosen  # type: ignore[return-value]


def _is_right(q: Question, chosen: list[dict]) -> bool:
    return {o["option_id"] for o in chosen} == q.key.correct_ids


def _result(student_id: int, a: dict, q: Question, st: dict, **extra: Any) -> dict[str, Any]:
    with connect() as conn:
        signals = ck.learning_signals(conn, student_id, a["assignment_id"])
    return {"question": public_question(q, st, student_id=student_id, assignment=a), **extra, "signals": signals}


# ---------------------------------------------------------------- endpoints
@router.get("/checkin/{assignment_id}")
def checkin_state(assignment_id: int, student_id: int = Depends(current_student)) -> dict[str, Any]:
    a = checkin_for_student(student_id, assignment_id)
    with connect() as conn:
        practice = ck.practice_stats(conn, student_id, assignment_id)
        questions = public_questions(conn, student_id, a) if practice["unlocked"] else []
        signals = ck.learning_signals(conn, student_id, assignment_id)
    return {"assignment": _assignment_out(a), "practice": practice, "unlocked": practice["unlocked"],
            "questions": questions, "signals": signals}


@router.post("/checkin/{assignment_id}/answer")
def first_answer(assignment_id: int, body: AnswerIn, student_id: int = Depends(current_student)) -> dict[str, Any]:
    a, q, st = _load(student_id, assignment_id, body.question_id)
    if st["status"] != "unanswered":
        raise HTTPException(409, "You've already answered this one.")
    if q.kind == "choice":
        chosen = _chosen(q, body.option_id, body.option_ids)
        if not chosen:
            raise _not_honest("Pick an answer first.")
        correct = _is_right(q, chosen)
        answer = ", ".join(o["option_text"] for o in chosen)
        feedback = "Right!" if correct else "Not quite. Let's figure this one out together."
    else:
        ok, reason = ck.honest_try(body.text, min_words=ck.MIN_EXPLAIN_WORDS)
        if not ok:
            raise _not_honest(reason)
        if copies_question(body.text or "", q.key):  # an echo isn't a first try: don't spend it
            raise _not_honest(JUST_THE_QUESTION)
        answer = (body.text or "").strip()
        with agent_trace("tutor", class_id=a["class_id"], assignment_id=assignment_id, question_id=q.question_id):
            verdict = judge(answer, q.key, offline=offline_mode())
        correct = verdict.accepted
        extra = "" if verdict.feedback == NOT_YET else f" {verdict.feedback}"
        feedback = "Right! That shows the key idea." if correct else \
            f"Not quite.{extra} Let's figure this one out together."
    if not correct:
        feedback += " Ask the tutor, then fix it with the right answer and a short explanation in your own words."
    with connect() as conn:
        try:
            st = ck.record_first_answer(conn, student_id, assignment_id, q.question_id, answer, correct)
        except ValueError as e:
            raise _bad(e)
    return _result(student_id, a, q, st, correct=correct, feedback=feedback)


@router.post("/checkin/{assignment_id}/fix")
def fix(assignment_id: int, body: FixIn, student_id: int = Depends(current_student)) -> dict[str, Any]:
    a, q, st = _load(student_id, assignment_id, body.question_id)
    if st["status"] != "needs_fix":
        raise HTTPException(409, "This question doesn't need fixing.")
    previous = st["explain_back"] or (st["first_answer"] if q.kind == "explain" else None)
    ok, reason = ck.honest_try(body.explanation, previous=previous, min_words=ck.MIN_EXPLAIN_WORDS)
    if not ok:
        raise _not_honest(reason)
    if copies_question(body.explanation, q.key):  # don't count an echo as an honest try
        raise _not_honest(JUST_THE_QUESTION)
    # Once the tutor has walked through the answer, pasting it back isn't "your own words".
    if (st["help_level"] == "explained" or ck.may_reveal(a, st)) and copies_answer(body.explanation, q.key):
        raise _not_honest(COPIED)
    explanation = body.explanation.strip()
    if q.kind == "choice":
        chosen = _chosen(q, body.option_id, body.option_ids)
        if not chosen:
            raise _not_honest("Pick the answer you now think is right, too.")
        right_option = _is_right(q, chosen)
    else:
        right_option = True
    if right_option:
        with agent_trace("tutor", class_id=a["class_id"], assignment_id=assignment_id, question_id=q.question_id):
            verdict = judge(explanation, q.key, offline=offline_mode())
        accepted, feedback = verdict.accepted, verdict.feedback
    else:
        # Same feedback as a weak reason, so a student can't find the right option by elimination.
        accepted = False
        feedback = NOT_YET
    with connect() as conn:
        try:
            st = ck.record_fix_attempt(conn, student_id, assignment_id, q.question_id, explanation, accepted,
                                       None if accepted else feedback)
        except ValueError as e:
            raise _bad(e)
    if accepted:
        feedback = "Fixed! " + feedback
    return _result(student_id, a, q, st, accepted=accepted, feedback=feedback)


@router.post("/checkin/{assignment_id}/chat")
def chat(assignment_id: int, body: ChatIn, student_id: int = Depends(current_student)) -> dict[str, Any]:
    a, q, st = _load(student_id, assignment_id, body.question_id)
    if st["status"] not in ("unanswered", "needs_fix"):
        raise HTTPException(409, "This question is already done. Pick one that still needs work.")
    message = (body.message or "").strip()
    if not message:
        raise _not_honest("Write something first.")
    if len(message) > MAX_MESSAGE_CHARS:
        raise _not_honest(f"That's a long message. Keep it under {MAX_MESSAGE_CHARS} characters.")
    with connect() as conn:
        history = ck.chat_history(conn, student_id, assignment_id, q.question_id)
    ctx = tutor.TutorContext(assignment=a, question=q, status=st, reveal=ck.may_reveal(a, st),
                             message=message, history=history)
    with agent_trace("tutor", class_id=a["class_id"], assignment_id=assignment_id, question_id=q.question_id):
        out = tutor.reply(ctx)
    with connect() as conn:
        ck.save_chat(conn, student_id, assignment_id, q.question_id, "user", message)
        ck.save_chat(conn, student_id, assignment_id, q.question_id, "assistant", out.text)
        ck.record_tutor_turn(conn, student_id, assignment_id, q.question_id, out.help_level)
        st = ck.get_status(conn, student_id, assignment_id, q.question_id)
    return {"reply": out.text, "question": public_question(q, st, student_id=student_id, assignment=a)}


@router.get("/checkin/{assignment_id}/chat/{question_id}")
def chat_log(assignment_id: int, question_id: int, student_id: int = Depends(current_student)) -> dict[str, Any]:
    checkin_for_student(student_id, assignment_id)
    with connect() as conn:
        try:
            get_question(conn, assignment_id, question_id)
        except ValueError as e:
            raise _bad(e)
        rows = ck.chat_history(conn, student_id, assignment_id, question_id)
    return {"messages": [{"role": r["role"], "content": r["content"]} for r in rows]}


# ---------------------------------------------------------------- teacher: check-in settings
@router.get("/checkin/{assignment_id}/settings")
def checkin_settings(assignment_id: int) -> dict[str, Any]:
    """{settings: {assignment_id, class_id, title, unit, lesson_date, due_date, due_day, tutor_mode,
    tutor_reveal_after, mastery_threshold, past_due, calendar_event, unlocked_students}}"""
    try:
        return {"settings": cs.get_settings(assignment_id)}
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.patch("/checkin/{assignment_id}/settings")
def update_checkin_settings(assignment_id: int, body: cs.SettingsPatch) -> dict[str, Any]:
    """Change only the fields sent. -> {settings, changed, notes, calendar_note}. 404 unless a
    check-in, 422 {detail} for a value to fix (e.g. a due date after the lesson)."""
    try:
        return cs.update_settings(assignment_id, body)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except cs.SettingsError as e:
        raise HTTPException(422, str(e)) from e
