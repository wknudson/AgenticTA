"""The check-in tutor (app/agents/tutor): endpoints, explain-back judge, answer guard, and the
no-AI tutor. Everything runs offline (AGENTICTA_TUTOR_OFFLINE=1; conftest blanks all keys too)."""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from app.agents.tutor import tutor as tutor_mod
from app.agents.tutor.guard import guard_reply, leaks_answer
from app.agents.tutor.judge import offline_judge
from app.agents.tutor.questions import AnswerKey, get_question, seeded_shuffle
from app.shared import checkin as ck
from app.shared.db import connect
from app.shared.llm import get_model
from app.shared.student_auth import issue_student_token
from tests.checkin_fixtures import BIO, ENROLLED, NOT_ENROLLED, make_checkin

RUBRIC = "The membrane controls what enters and leaves the cell, keeping the inside stable."
MODEL_ANSWER = "It controls what goes in and out, so the cell can keep its inside stable."
GOOD_MEMBRANE = "the cell membrane is a thin barrier around the cell that decides what gets in and out"
NOTES_UNIT = "Tutor Test Unit: Organelles"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("AGENTICTA_TUTOR_OFFLINE", "1")


def auth(student_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_student_token(student_id)}"}


def url(c, tail: str = "") -> str:
    return f"/agents/tutor/checkin/{c.assignment_id}{tail}"


def unlock(c, student_id: int) -> None:
    with connect() as conn:
        for aid, iid in c.items:
            ck.record_practice_answer(conn, student_id, c.assignment_id, aid, iid, True)


def ready(client, **kw):
    """A check-in with practice done for every enrolled student."""
    c = make_checkin(**kw)
    for s in ENROLLED:
        unlock(c, s)
    return c


def file_notes(unit: str = NOTES_UNIT) -> None:
    with connect() as conn:
        if conn.execute("SELECT 1 FROM library_files WHERE unit = ?", (unit,)).fetchone():
            return
        fid = conn.execute(
            "INSERT INTO library_files (class_id, original_name, stored_path, title, doc_type, unit, status) "
            "VALUES (?, 'organelle_notes.txt', 'test/organelle_notes.txt', 'Organelle Notes', 'lecture', ?, 'filed')",
            (BIO, unit)).lastrowid
        for i, text in enumerate([
            "Mitochondria make most of the cell's ATP through cellular respiration. They burn sugar for energy.",
            "Ribosomes build proteins from amino acids. The nucleus holds the DNA.",
            "The cell membrane controls what enters and leaves the cell, so the inside stays stable.",
        ]):
            conn.execute("INSERT INTO library_chunks (file_id, chunk_idx, text) VALUES (?, ?, ?)", (fid, i, text))


def answer(client, c, s, qid, **body):
    return client.post(url(c, "/answer"), json={"question_id": qid, **body}, headers=auth(s))


def fix(client, c, s, qid, explanation, **body):
    return client.post(url(c, "/fix"), json={"question_id": qid, "explanation": explanation, **body}, headers=auth(s))


def chat(client, c, s, qid, message):
    return client.post(url(c, "/chat"), json={"question_id": qid, "message": message}, headers=auth(s))


def assert_no_answers(payload) -> None:
    raw = json.dumps(payload).lower()
    for leak in ("is_correct", "correct_answer", "rubric", RUBRIC.lower(), MODEL_ANSWER.lower()):
        assert leak not in raw, leak
    questions = payload.get("questions") or [payload["question"]]
    for q in questions:
        assert set(q) <= {"question_id", "number", "text", "kind", "options", "multi", "status", "first_answer",
                          "tries", "help_level", "last_feedback", "can_reveal"}
        for o in q.get("options", []):
            assert set(o) == {"option_id", "text"}


# ---------------------------------------------------------------- access
def test_auth_enrollment_and_missing_checkin(client):
    c = make_checkin()
    assert client.get(url(c)).status_code == 401
    assert client.get(url(c), headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get(url(c), headers=auth(NOT_ENROLLED)).status_code == 403
    assert chat(client, c, NOT_ENROLLED, c.mc_ids[0], "hi").status_code == 403
    assert client.get("/agents/tutor/checkin/999999", headers=auth(ENROLLED[0])).status_code == 404
    assert client.get("/agents/tutor/info").json()["name"] == "tutor"
    assert client.get("/agents/tutor/ping").json()["pong"] is True


def test_questions_hidden_until_practice_unlocks(client):
    c = make_checkin()
    s = ENROLLED[0]
    state = client.get(url(c), headers=auth(s)).json()
    assert state["unlocked"] is False and state["questions"] == []
    assert state["assignment"]["tutor_mode"] == "hints_only" and state["assignment"]["past_due"] is False
    assert answer(client, c, s, c.mc_ids[0], option_id=c.mc_correct[c.mc_ids[0]]).status_code == 403
    assert chat(client, c, s, c.mc_ids[0], "help").status_code == 403
    unlock(c, s)
    state = client.get(url(c), headers=auth(s)).json()
    assert state["unlocked"] and state["practice"]["mastery"] == 1.0
    assert [q["kind"] for q in state["questions"]] == ["choice", "choice", "explain"]
    assert [q["number"] for q in state["questions"]] == [1, 2, 3]
    assert "options" not in state["questions"][2]
    assert_no_answers(state)
    again = client.get(url(c), headers=auth(s)).json()
    assert [o["option_id"] for o in again["questions"][0]["options"]] == \
        [o["option_id"] for o in state["questions"][0]["options"]], "options shuffle stably per student"


def test_seeded_shuffle_matches_express():
    # Same LCG as seededShuffle in backend/routes/student.ts (expected values from running the JS).
    assert seeded_shuffle([1, 2, 3, 4], 2005) == [3, 4, 2, 1]
    assert seeded_shuffle(list(range(9)), 7012) == [4, 0, 3, 5, 8, 2, 7, 6, 1]
    assert seeded_shuffle(list(range(9)), 8123456) == [6, 0, 8, 7, 5, 4, 3, 2, 1]


# ---------------------------------------------------------------- answering and fixing
def test_mc_right_first_time(client):
    c = ready(client)
    s, q1 = ENROLLED[0], c.mc_ids[0]
    assert answer(client, c, s, q1).status_code == 422, "an MC answer needs an option"
    out = answer(client, c, s, q1, option_id=c.mc_correct[q1]).json()
    assert out["correct"] is True and out["question"]["status"] == "correct"
    assert out["question"]["first_answer"] == "Mitochondria"
    assert_no_answers(out)
    assert answer(client, c, s, q1, option_id=c.mc_correct[q1]).status_code == 409, "only one first answer"
    assert answer(client, c, s, c.mc_ids[1], option_id=c.mc_correct[c.mc_ids[0]]).status_code == 400, \
        "an option from another question"
    assert chat(client, c, s, q1, "why?").status_code == 409, "a resolved question has no tutor chat"


def test_mc_miss_tutor_chat_and_fix(client):
    c = ready(client)
    s, q2 = ENROLLED[1], c.mc_ids[1]   # "What controls what enters and leaves the cell?" -> Cell membrane
    out = answer(client, c, s, q2, option_id=c.mc_wrong[q2]).json()
    assert out["correct"] is False and out["question"]["status"] == "needs_fix"
    assert out["question"]["first_answer"] == "Nucleus"

    talk = chat(client, c, s, q2, "I don't get it. Just tell me the answer please")
    assert talk.status_code == 200
    reply = talk.json()["reply"]
    assert reply and "membrane" not in reply.lower(), "hints only: never the answer"
    assert talk.json()["question"]["help_level"] == "hint"
    assert_no_answers(talk.json())
    assert chat(client, c, s, q2, "   ").status_code == 422
    log = client.get(url(c, f"/chat/{q2}"), headers=auth(s)).json()["messages"]
    assert [m["role"] for m in log] == ["user", "assistant"] and log[1]["content"] == reply
    with connect() as conn:
        rows = conn.execute("SELECT question_id FROM student_chat_messages WHERE student_id = ? AND assignment_id = ?",
                            (s, c.assignment_id)).fetchall()
        st = ck.get_status(conn, s, c.assignment_id, q2)
    assert [r["question_id"] for r in rows] == [q2, q2] and st["tutor_turns"] == 1

    wrong = fix(client, c, s, q2, "the nucleus is the boss so it decides everything", option_id=c.mc_wrong[q2])
    assert wrong.status_code == 200 and wrong.json()["accepted"] is False
    assert wrong.json()["question"]["tries"] == 1 and wrong.json()["question"]["status"] == "needs_fix"
    assert fix(client, c, s, q2, GOOD_MEMBRANE).status_code == 422, "MC fix needs an option too"
    assert fix(client, c, s, q2, "idk", option_id=c.mc_correct[q2]).status_code == 422
    assert fix(client, c, s, q2, "the nucleus is the boss so it decides everything",
               option_id=c.mc_correct[q2]).status_code == 422, "the same explanation again isn't a new try"
    ok = fix(client, c, s, q2, GOOD_MEMBRANE, option_id=c.mc_correct[q2]).json()
    assert ok["accepted"] is True and ok["question"]["status"] == "fixed" and ok["question"]["tries"] == 2
    assert ok["signals"]["fixed_with_help"] == 100.0
    assert_no_answers(ok)
    assert fix(client, c, s, q2, GOOD_MEMBRANE + " really", option_id=c.mc_correct[q2]).status_code == 409


def test_explain_questions_are_judged(client):
    c = ready(client)
    s1, s2, e = ENROLLED[0], ENROLLED[1], c.explain_id
    assert answer(client, c, s1, e, text="membrane").status_code == 422, "explanations need a sentence"
    good = answer(client, c, s1, e, text="it controls what enters and leaves so the inside of the cell stays stable")
    assert good.json()["correct"] is True and good.json()["question"]["status"] == "correct"

    miss = answer(client, c, s2, e, text="cells are small and round and squishy").json()
    assert miss["correct"] is False and miss["question"]["status"] == "needs_fix"
    echo = fix(client, c, s2, e, "Explain why a cell needs a membrane.")
    assert echo.status_code == 422 and "question" in echo.json()["detail"].lower(), "an echo isn't an honest try"
    vague = fix(client, c, s2, e, "it controls stuff and is stable").json()
    assert vague["accepted"] is False and vague["question"]["last_feedback"]
    assert RUBRIC.lower() not in vague["feedback"].lower()
    fixed = fix(client, c, s2, e, "the membrane controls what enters and leaves, keeping the inside stable").json()
    assert fixed["accepted"] is True and fixed["question"]["status"] == "fixed"


def test_offline_judge_is_lenient_but_not_fooled():
    key = AnswerKey("short_answer", "Explain why a cell needs a membrane.", model_answer=MODEL_ANSWER, rubric=RUBRIC)
    assert offline_judge("It controls what goes in and out so the cell keeps its inside stable", key).accepted
    assert not offline_judge("A cell needs a membrane, that's why.", key).accepted
    assert not offline_judge("photosynthesis happens in the chloroplast", key).accepted
    mc = AnswerKey("multiple_choice", "Which organelle makes most of the cell's ATP?", {1}, ["Mitochondria"], ["Ribosome"])
    assert offline_judge("mitochondria do cellular respiration", mc).accepted
    assert offline_judge("they are the powerhouse and burn sugar for energy", mc).accepted
    assert not offline_judge("I think it is right", mc).accepted


def test_model_judge_structured_output_guard_and_fallback(monkeypatch):
    from app.agents.tutor import judge as judge_mod
    key = AnswerKey("short_answer", "Explain why a cell needs a membrane.", model_answer=MODEL_ANSWER, rubric=RUBRIC)

    def scripted(args):
        call = AIMessage("", tool_calls=[{"name": "JudgeOut", "args": args, "id": "j1"}])
        monkeypatch.setattr(judge_mod, "tutor_model", lambda: get_model("tutor", script=[call]))

    scripted({"accepted": True, "missing_idea": None})
    assert judge_mod.judge("it is like a gate that picks what comes in", key, offline=False).source == "model"
    scripted({"accepted": False, "missing_idea": "Say more about what it controls."})
    v = judge_mod.judge("it is a wall around the cell", key, offline=False)
    assert (v.accepted, v.source) == (False, "model") and "controls" in v.feedback
    scripted({"accepted": False, "missing_idea": RUBRIC})   # a nudge that gives the idea away is replaced
    v = judge_mod.judge("it is a wall around the cell", key, offline=False)
    assert not v.accepted and RUBRIC.lower() not in v.feedback.lower()
    monkeypatch.setattr(judge_mod, "tutor_model", lambda: get_model("tutor"))  # no key -> MissingApiKey
    v = judge_mod.judge("it controls what enters and leaves so the inside stays stable", key, offline=False)
    assert (v.accepted, v.source) == (True, "offline"), "a failed model call falls back, never a 500"


# ---------------------------------------------------------------- guard and tutor modes
def test_guard_blocks_answers_in_hints_only(client):
    c = make_checkin()
    with connect() as conn:
        mc = get_question(conn, c.assignment_id, c.mc_ids[1]).key       # Cell membrane
        ex = get_question(conn, c.assignment_id, c.explain_id).key
    for leak in ("The answer is Cell membrane.", "It's the membrane, it's the boundary of the cell!"):
        text, blocked = guard_reply(leak, mc, allow_reveal=False)
        assert blocked and "membrane" not in text.lower()
        assert guard_reply(leak, mc, allow_reveal=True) == (leak, False), "allowed once may_reveal() is true"
    assert not guard_reply("What does the nucleus do? Check your notes on the boundary of the cell.", mc,
                           allow_reveal=False)[1]
    paraphrase = "Basically the membrane controls what enters and leaves the cell, which keeps the inside stable."
    assert leaks_answer(paraphrase, ex), "Dice >= 0.72 against the rubric"
    assert leaks_answer(f"Sure! {MODEL_ANSWER} Hope that helps.", ex), "verbatim model answer"
    assert not leaks_answer("Think about a security guard at a door. What would happen without one?", ex)


def test_model_tutor_output_guard_and_fallback(client):
    """The create_agent path with a scripted model: the guard middleware swaps a leaking reply,
    the tools run, and a broken model falls back to the no-AI tutor instead of a 500."""
    c = make_checkin(unit=NOTES_UNIT)
    file_notes()
    with connect() as conn:
        q = get_question(conn, c.assignment_id, c.mc_ids[1])
        st = ck.get_status(conn, ENROLLED[2], c.assignment_id, q.question_id)
    a = {"class_id": BIO, "unit": NOTES_UNIT, "tutor_mode": "hints_only", "ai_params": "Use sports analogies."}
    ctx = tutor_mod.TutorContext(assignment=a, question=q, status=st, reveal=False, message="what is it?")
    assert "Use sports analogies." in tutor_mod.system_prompt(ctx)
    assert "Cell membrane" not in tutor_mod.system_prompt(ctx).split("Options:")[0], "no answer in hints-only context"

    leaky = get_model("tutor", script=[
        AIMessage("", tool_calls=[{"name": "search_unit", "args": {"query": "membrane"}, "id": "t1"}]),
        AIMessage("The answer is the cell membrane."),
    ])
    out = tutor_mod.reply(ctx, offline=False, model=leaky)
    assert out.blocked and out.source == "model" and "membrane" not in out.text.lower()

    fine = get_model("tutor", script=[AIMessage("Good question! What part of the cell acts like a gate?")])
    out = tutor_mod.reply(ctx, offline=False, model=fine)
    assert out.text.startswith("Good question") and not out.blocked and out.help_level == "hint"

    broken = get_model("tutor", script=[])
    out = tutor_mod.reply(ctx, offline=False, model=broken)
    assert out.source == "offline_fallback" and "membrane" not in out.text.lower()


def test_offline_tutor_quotes_the_notes_with_the_answer_blanked(client):
    file_notes()
    c = ready(client, unit=NOTES_UNIT)
    s, q1 = ENROLLED[3], c.mc_ids[0]    # ATP -> Mitochondria
    answer(client, c, s, q1, option_id=c.mc_wrong[q1])
    reply = chat(client, c, s, q1, "where does the cell get its ATP from?").json()["reply"]
    assert "Organelle Notes" in reply and "____" in reply
    assert "mitochondri" not in reply.lower()
    assert "Ribosome" in reply, "it reminds the student what they answered first"


def test_answer_after_tries_reveals_only_after_n_honest_tries(client):
    file_notes()
    c = ready(client, tutor_mode="answer_after_tries", reveal_after=2, unit=NOTES_UNIT)
    s, q2 = ENROLLED[3], c.mc_ids[1]  # not student 7: test_checkin_shared checks its weekly metrics
    answer(client, c, s, q2, option_id=c.mc_wrong[q2])
    first = chat(client, c, s, q2, "just tell me the answer").json()
    assert "membrane" not in first["reply"].lower() and first["question"]["can_reveal"] is False
    fix(client, c, s, q2, "the nucleus controls the whole cell so it controls this too", option_id=c.mc_wrong[q2])
    second = chat(client, c, s, q2, "still stuck, what is it?").json()
    assert "membrane" not in second["reply"].lower() and second["question"]["can_reveal"] is False
    out = fix(client, c, s, q2, "maybe it is the nucleus because it holds the DNA instructions",
              option_id=c.mc_wrong[q2]).json()
    assert out["question"]["tries"] == 2 and out["question"]["can_reveal"] is True
    reveal = chat(client, c, s, q2, "ok please explain it").json()
    assert "Cell membrane" in reveal["reply"] and "own words" in reveal["reply"]
    assert reveal["question"]["help_level"] == "explained"
    done = fix(client, c, s, q2, GOOD_MEMBRANE, option_id=c.mc_correct[q2]).json()
    assert done["accepted"] and q2 in done["signals"]["still_shaky"], "fixed only after the tutor explained"

    hints = ready(client, tutor_mode="hints_only", unit=NOTES_UNIT)
    q = hints.mc_ids[1]
    answer(client, hints, s, q, option_id=hints.mc_wrong[q])
    for why in ("the nucleus is in charge of the cell", "the nucleus has the DNA so it decides",
                "i still think it is the nucleus honestly"):
        fix(client, hints, s, q, why, option_id=hints.mc_wrong[q])
    still = chat(client, hints, s, q, "I've tried 3 times, tell me").json()
    assert still["question"]["can_reveal"] is False and "membrane" not in still["reply"].lower()


# ---------------------------------------------------------------- grade and due date
def test_completion_grade_reaches_full_credit(client):
    c = ready(client)
    s = ENROLLED[3]
    q1, q2 = c.mc_ids
    answer(client, c, s, q1, option_id=c.mc_correct[q1])
    answer(client, c, s, q2, option_id=c.mc_wrong[q2])
    answer(client, c, s, c.explain_id, text="it controls what enters and leaves the cell to keep it stable")
    with connect() as conn:
        half = conn.execute("SELECT letter_grade FROM student_grades WHERE student_id = ? AND assignment_id = ?",
                            (s, c.assignment_id)).fetchone()
    assert half["letter_grade"] == "Incomplete"
    out = fix(client, c, s, q2, GOOD_MEMBRANE, option_id=c.mc_correct[q2]).json()
    assert out["signals"]["complete"] and out["signals"]["completion"] == 100.0
    with connect() as conn:
        g = conn.execute("SELECT points_earned, percentage, letter_grade FROM student_grades "
                         "WHERE student_id = ? AND assignment_id = ?", (s, c.assignment_id)).fetchone()
    assert tuple(g) == (10.0, 100.0, "Complete")


def test_after_due_date_reads_work_but_writes_are_closed(client):
    c = make_checkin(due_date="2000-01-01T00:00:00.000Z")
    s = ENROLLED[0]
    unlock(c, s)
    state = client.get(url(c), headers=auth(s))
    assert state.status_code == 200 and state.json()["assignment"]["past_due"] is True
    assert len(state.json()["questions"]) == 3
    assert answer(client, c, s, c.mc_ids[0], option_id=c.mc_correct[c.mc_ids[0]]).status_code == 403
    assert chat(client, c, s, c.mc_ids[0], "help").status_code == 403
    assert fix(client, c, s, c.mc_ids[0], GOOD_MEMBRANE).status_code == 403
    assert client.get(url(c, f"/chat/{c.mc_ids[0]}"), headers=auth(s)).json() == {"messages": []}


def test_select_all_is_an_exact_set_match(client):
    c = ready(client)
    s = ENROLLED[0]
    with connect() as conn:
        qid = conn.execute("INSERT INTO assignment_questions (assignment_id, sort_order, question_text, question_type) "
                           "VALUES (?, 3, 'Which organelles are in animal cells?', 'select_all_that_apply')",
                           (c.assignment_id,)).lastrowid
        ids = [conn.execute("INSERT INTO assignment_question_options (question_id, option_text, is_correct) "
                            "VALUES (?, ?, ?)", (qid, t, ok)).lastrowid
               for t, ok in (("Nucleus", 1), ("Mitochondria", 1), ("Cell wall", 0))]
    q = next(q for q in client.get(url(c), headers=auth(s)).json()["questions"] if q["question_id"] == qid)
    assert q["multi"] is True and q["kind"] == "choice"
    out = answer(client, c, s, qid, option_ids=[ids[0]]).json()
    assert out["correct"] is False
    ok = fix(client, c, s, qid, "both have DNA or make energy and animal cells have no cell wall",
             option_ids=[ids[1], ids[0]]).json()
    assert ok["accepted"] is True and ok["question"]["status"] == "fixed"


def test_echoing_the_question_is_not_an_attempt(client, monkeypatch):
    """Found in live testing: pasting the question back counted as a (wrong) first try."""
    from app.shared import checkin as ck
    from app.shared.db import connect
    from app.shared.student_auth import issue_student_token
    from tests.checkin_fixtures import make_checkin

    monkeypatch.setenv("AGENTICTA_TUTOR_OFFLINE", "1")
    c = make_checkin(threshold=0.1)
    s = 8
    with connect() as conn:
        ck.record_practice_answer(conn, s, c.assignment_id, *c.items[0], True)
    h = {"Authorization": f"Bearer {issue_student_token(s)}"}
    r = client.post(f"/agents/tutor/checkin/{c.assignment_id}/answer", headers=h,
                    json={"question_id": c.explain_id, "text": "Explain why a cell needs a membrane."})
    assert r.status_code == 422 and "repeats the question" in r.json()["detail"]
    with connect() as conn:
        assert ck.get_status(conn, s, c.assignment_id, c.explain_id)["status"] == "unanswered"


def test_mc_fix_needs_a_real_reason_not_just_the_option(client, monkeypatch):
    """Found in review: offline, "my answer is Mitochondria" fixed a missed MC question."""
    from app.shared import checkin as ck
    from app.shared.db import connect
    from app.shared.student_auth import issue_student_token
    from tests.checkin_fixtures import make_checkin

    monkeypatch.setenv("AGENTICTA_TUTOR_OFFLINE", "1")
    c = make_checkin(threshold=0.1)
    s, q = 4, c.mc_ids[0]
    with connect() as conn:
        ck.record_practice_answer(conn, s, c.assignment_id, *c.items[0], True)
    h = {"Authorization": f"Bearer {issue_student_token(s)}"}
    base = f"/agents/tutor/checkin/{c.assignment_id}"
    client.post(f"{base}/answer", headers=h, json={"question_id": q, "option_id": c.mc_wrong[q]})
    wrong = client.post(f"{base}/fix", headers=h, json={"question_id": q, "option_id": c.mc_wrong[q],
                                                         "explanation": "my answer is the ribosome now"}).json()
    named = client.post(f"{base}/fix", headers=h, json={"question_id": q, "option_id": c.mc_correct[q],
                                                         "explanation": "my answer is mitochondria"}).json()
    assert not wrong["accepted"] and not named["accepted"]
    assert wrong["feedback"] == named["feedback"], "a wrong option and a weak reason look the same"
    real = client.post(f"{base}/fix", headers=h, json={"question_id": q, "option_id": c.mc_correct[q],
                       "explanation": "mitochondria break down sugar to release energy for the cell"}).json()
    assert real["accepted"]


def test_pasting_the_revealed_answer_is_not_own_words(client, monkeypatch):
    """Found in review: after the tutor reveals the answer, pasting it back fixed the question."""
    from app.shared import checkin as ck
    from app.shared.db import connect
    from app.shared.student_auth import issue_student_token
    from tests.checkin_fixtures import make_checkin

    monkeypatch.setenv("AGENTICTA_TUTOR_OFFLINE", "1")
    c = make_checkin(threshold=0.1, tutor_mode="answer_after_tries", reveal_after=1)
    s = 7
    with connect() as conn:
        ck.record_practice_answer(conn, s, c.assignment_id, *c.items[0], True)
    h = {"Authorization": f"Bearer {issue_student_token(s)}"}
    base = f"/agents/tutor/checkin/{c.assignment_id}"
    e = c.explain_id
    client.post(f"{base}/answer", headers=h, json={"question_id": e, "text": "cells are small and round and squishy"})
    client.post(f"{base}/fix", headers=h, json={"question_id": e, "explanation": "it makes the cell look nice and round"})
    pasted = "The membrane controls what enters and leaves the cell, keeping the inside stable."
    r = client.post(f"{base}/fix", headers=h, json={"question_id": e, "explanation": pasted})
    assert r.status_code == 422 and "own words" in r.json()["detail"]
    ok = client.post(f"{base}/fix", headers=h, json={"question_id": e,
                     "explanation": "it is like a gate that picks what can get in or out so things inside stay steady"})
    assert ok.status_code == 200
