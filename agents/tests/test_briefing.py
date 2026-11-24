"""The before-class briefing (misconceptions agent): roster stages, hardest questions and game
items, per-student struggles, the warm-up, and check-ins analyzed before their due date."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.agents.misconceptions import briefing, pipeline
from app.shared import checkin as ck
from app.shared.db import connect
from tests.checkin_fixtures import BIO, NOT_ENROLLED, make_checkin

BOB, DAVID, GRACE, HENRY = 2, 4, 7, 8   # enrolled in Biology (class 3)
LEAK = "LEAKY-OTHER-CLASS-ANSWER"
_created: list[int] = []


def _new_checkin(**kwargs):
    c = make_checkin(**kwargs)
    _created.append(c.assignment_id)
    return c


@pytest.fixture(autouse=True)
def _drop_test_grades():
    """Answers here write completion grades + weekly metrics; take them back out afterwards so
    other test files that check a student's weekly averages don't see these check-ins."""
    yield
    if not _created:
        return
    marks = ",".join("?" * len(_created))
    with connect() as conn:
        rows = conn.execute(f"""SELECT DISTINCT g.student_id, a.class_id FROM student_grades g
                                JOIN assignments a ON a.assignment_id = g.assignment_id
                                WHERE g.assignment_id IN ({marks})""", _created).fetchall()
        conn.execute(f"DELETE FROM student_grades WHERE assignment_id IN ({marks})", _created)
        for r in rows:
            conn.execute(ck.WEEKLY_METRICS_SQL, {"student_id": r["student_id"], "class_id": r["class_id"]})
    _created.clear()


def _play(conn, c, student, *answers):
    for (aid, iid), correct in answers:
        ck.record_practice_answer(conn, student, c.assignment_id, aid, iid, correct)


def _class_progress():
    """Grace: nothing. David: practicing. Bob: check-in started. Henry: complete.
    Student 1 (not in Biology) also has progress that must never show up.
    (Grace, student 7, never gets a grade here: test_checkin_shared checks her weekly metrics.)"""
    c = _new_checkin()
    mc1, mc2 = c.mc_ids
    with connect() as conn:
        _play(conn, c, DAVID, (c.items[0], False), (c.items[1], True))
        _play(conn, c, BOB, *[(i, True) for i in c.items])
        ck.record_first_answer(conn, BOB, c.assignment_id, mc1, "Ribosome", False)
        ck.record_first_answer(conn, BOB, c.assignment_id, mc2, "Cell membrane", True)
        _play(conn, c, HENRY, (c.items[0], False), *[(i, True) for i in c.items])
        # MC first answers are stored as the option text and shown as is.
        ck.record_first_answer(conn, HENRY, c.assignment_id, mc1, "Ribosome", False)  # the tutor stores option text
        ck.record_tutor_turn(conn, HENRY, c.assignment_id, mc1, "explained")
        ck.record_fix_attempt(conn, HENRY, c.assignment_id, mc1, "Mitochondria turn food into ATP for the cell", True)
        ck.record_first_answer(conn, HENRY, c.assignment_id, mc2, "Cell membrane", True)
        ck.record_first_answer(conn, HENRY, c.assignment_id, c.explain_id, "It controls what goes in and out", True)
        _play(conn, c, NOT_ENROLLED, (c.items[1], False), (c.items[1], False), (c.items[1], False))
        ck.record_first_answer(conn, NOT_ENROLLED, c.assignment_id, mc2, LEAK, False)
        ck.record_fix_attempt(conn, NOT_ENROLLED, c.assignment_id, mc2, LEAK + " explained", False, "nope")
    return c


def test_roster_stages_hardest_lists_and_struggles(client):
    c = _class_progress()
    mc1, mc2 = c.mc_ids
    r = client.get("/agents/misconceptions/briefing", params={"class_id": BIO, "assignment_id": c.assignment_id})
    assert r.status_code == 200, r.text
    b = r.json()
    assert LEAK not in json.dumps(b), "another class's student must not leak into the briefing"

    stages = {s["student_id"]: s["stage"] for s in b["roster"]}
    assert stages == {GRACE: "not_started", DAVID: "practicing", BOB: "checkin", HENRY: "complete"}
    assert b["counts"] == {"not_started": 1, "practicing": 1, "checkin": 1, "complete": 1, "total": 4}
    names = {s["student_id"]: s["name"] for s in b["roster"]}
    assert names[BOB] == "Bob M." and names[GRACE] == "Grace T." and names[HENRY] == "Henry D."
    david = next(s for s in b["roster"] if s["student_id"] == DAVID)
    assert david["mastery"] == 0.1 and not david["unlocked"]
    bob = next(s for s in b["roster"] if s["student_id"] == BOB)
    assert (bob["resolved"], bob["total"]) == (1, 3)

    hq = b["hardest_questions"]
    assert [h["question_id"] for h in hq] == [mc1, mc2, c.explain_id]
    assert hq[0]["answered"] == 2 and hq[0]["first_try_rate"] == 0 and hq[0]["explained"] == 1
    assert hq[1]["answered"] == 2 and hq[1]["first_try_rate"] == 1.0, "student 1's miss is not counted"

    items = b["hardest_items"]
    assert [(i["item_id"], i["misses"], i["seen"]) for i in items] == [("c0", 2, 4)], "c1 was only missed outside the class"
    assert items[0]["label"] == "Mitochondria" and items[0]["answer"] == "Makes ATP"

    struggles = {s["student_id"]: s for s in b["students"]}
    assert set(struggles) == {GRACE, DAVID, BOB, HENRY}
    assert struggles[GRACE]["missed"] == [] and struggles[DAVID]["missed"] == []
    g = struggles[BOB]["missed"]  # first answer stored as text
    assert [(m["question_id"], m["first_answer"], m["status"], m["help_level"]) for m in g] == \
        [(mc1, "Ribosome", "needs_fix", "none")]
    h = struggles[HENRY]["missed"]
    assert [(m["question_id"], m["first_answer"], m["status"], m["help_level"]) for m in h] == \
        [(mc1, "Ribosome", "fixed", "explained")]
    assert h[0]["explain_back"].startswith("Mitochondria turn food")
    assert struggles[HENRY]["signals"]["complete"] and struggles[HENRY]["signals"]["still_shaky"] == [mc1]
    assert b["assignment"]["unit"] == "Unit 2: Cell Structure" and b["assignment"]["lesson_date"] == "2099-01-02"
    assert b["warmup"] is None and b["misconceptions"] == []


def test_checkins_list_and_scoping(client):
    c = _new_checkin()
    with connect() as conn:
        graded = conn.execute("INSERT INTO assignments (class_id, assignment_name, due_date) VALUES (?, 'Old quiz', ?)",
                              (BIO, "2099-01-01T00:00:00.000Z")).lastrowid
    listed = client.get("/agents/misconceptions/checkins", params={"class_id": BIO}).json()["checkins"]
    mine = next(x for x in listed if x["assignment_id"] == c.assignment_id)
    assert mine == {"assignment_id": c.assignment_id, "title": "Unit 2 check-in", "unit": "Unit 2: Cell Structure",
                    "lesson_date": "2099-01-02", "due_date": "2099-01-01T23:59:00.000Z"}
    assert all(x["assignment_id"] != graded for x in listed)
    assert all(x["assignment_id"] != c.assignment_id
               for x in client.get("/agents/misconceptions/checkins", params={"class_id": 1}).json()["checkins"])
    for class_id, aid in ((1, c.assignment_id), (BIO, graded), (BIO, 999999)):
        assert client.get("/agents/misconceptions/briefing",
                          params={"class_id": class_id, "assignment_id": aid}).status_code == 404
        assert client.post("/agents/misconceptions/briefing/warmup",
                           params={"class_id": class_id, "assignment_id": aid, "offline": True}).status_code == 404


def test_warmup_offline_generation_and_teacher_edit(client):
    empty = _new_checkin()
    q = {"class_id": BIO, "assignment_id": empty.assignment_id, "offline": True}
    assert client.post("/agents/misconceptions/briefing/warmup", params=q).status_code == 409, "nothing to base it on"

    c = _class_progress()
    mc1 = c.mc_ids[0]
    params = {"class_id": BIO, "assignment_id": c.assignment_id}
    r = client.post("/agents/misconceptions/briefing/warmup", params={**params, "offline": True})
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["model_used"] == "deterministic" and w["edited"] is False
    assert len(w["questions"]) == 2
    assert w["questions"][0] == "Which organelle makes most of the cell's ATP? (Mitochondria / Ribosome)"
    assert "the answer is Mitochondria." in w["reteach"]
    assert [x["question_id"] for x in w["based_on"] if x["kind"] == "question"][0] == mc1

    # The top misconception for this check-in shapes the reteach.
    with connect() as conn:
        conn.execute("""INSERT INTO misconception_insights (class_id, assignment_id, topic, evidence_count, examples_json,
                        suggestion, model_used) VALUES (?, ?, 'Ribosomes vs mitochondria', 3, '[]', '{}', 'test')""",
                     (BIO, c.assignment_id))
    w = client.post("/agents/misconceptions/briefing/warmup", params={**params, "offline": True}).json()
    assert "Ribosomes vs mitochondria" in w["reteach"]
    assert any(x["kind"] == "misconception" for x in w["based_on"])

    edited = {"questions": ["Where is ATP made, and how do you know?"], "reteach": "Mitochondria make ATP. Ribosomes make proteins."}
    r = client.put("/agents/misconceptions/briefing/warmup", params=params, json=edited)
    assert r.status_code == 200, r.text
    assert r.json()["edited"] is True and r.json()["questions"] == edited["questions"]
    assert r.json()["based_on"] == w["based_on"], "editing keeps what it was based on"
    b = client.get("/agents/misconceptions/briefing", params=params).json()
    assert b["warmup"]["reteach"] == edited["reteach"] and b["warmup"]["edited"] is True
    assert b["misconceptions"][0]["topic"] == "Ribosomes vs mitochondria"
    assert client.put("/agents/misconceptions/briefing/warmup", params=params,
                      json={"questions": [], "reteach": "x"}).status_code == 422
    assert client.put("/agents/misconceptions/briefing/warmup", params={"class_id": 1, "assignment_id": c.assignment_id},
                      json=edited).status_code == 404


def test_warmup_model_path_and_fallback(client, monkeypatch):
    c = _class_progress()
    params = {"class_id": BIO, "assignment_id": c.assignment_id}
    seen = {}

    class Model:
        def invoke(self, messages):
            seen["user"] = messages[1][1]
            return SimpleNamespace(content=json.dumps({"questions": ["Q1?", "Q2?", "Q3?"], "reteach": "One. Two."}))

    monkeypatch.setattr(briefing, "get_model", lambda *a, **k: Model())
    w = client.post("/agents/misconceptions/briefing/warmup", params=params).json()
    assert w["questions"] == ["Q1?", "Q2?"] and w["reteach"] == "One. Two." and w["model_used"].startswith("ollama:")
    assert "Bob" not in seen["user"] and "Mitochondria" in seen["user"], "only questions and aggregates reach the model"

    def down(*a, **k):
        raise ConnectionError("Ollama is not running")
    monkeypatch.setattr(briefing, "get_model", down)
    w = client.post("/agents/misconceptions/briefing/warmup", params=params).json()
    assert w["model_used"] == "deterministic" and "Mitochondria" in w["reteach"]


def test_checkin_can_be_analyzed_before_due_date_grouped_by_question(client, monkeypatch):
    c = _new_checkin()   # due 2099
    mc1, mc2 = c.mc_ids
    with connect() as conn:
        ck.save_chat(conn, GRACE, c.assignment_id, mc1, "user", "Does mitosis make the ATP?")
        ck.save_chat(conn, GRACE, c.assignment_id, mc1, "assistant", "What does each organelle do?")
        ck.save_chat(conn, GRACE, c.assignment_id, mc1, "user", "Or is meiosis the one?")
        ck.save_chat(conn, DAVID, c.assignment_id, mc1, "user", "I think meiosis powers the cell")
        ck.save_chat(conn, BOB, c.assignment_id, mc2, "user", "Is mitosis what the membrane does?")
    assert pipeline.analysis_allowed(pipeline.assignment_for_analysis(BIO, c.assignment_id))
    listed = client.get("/agents/misconceptions/assignments", params={"class_id": BIO}).json()["assignments"]
    assert next(a for a in listed if a["assignment_id"] == c.assignment_id)["analysis_status"] == "eligible"

    captured = {}
    real_cluster = pipeline.cluster

    def spy(questions, **kwargs):
        captured["questions"] = questions
        return real_cluster(questions, **kwargs)
    monkeypatch.setattr(pipeline, "cluster", spy)
    r = client.post("/agents/misconceptions/demo", params={"class_id": BIO, "assignment_id": c.assignment_id})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["chats_read"] == 4 and result["questions_analyzed"] == 3, "one transcript per student per question"
    qs = captured["questions"]
    assert [q["text"] for q in qs] == ["I think meiosis powers the cell",
                                       "Does mitosis make the ATP? / Or is meiosis the one?",
                                       "Is mitosis what the membrane does?"], "grouped, same question side by side"
    assert qs[0]["about"] == qs[1]["about"] == "Which organelle makes most of the cell's ATP?"
    assert all(set(q) == {"id", "text", "about"} for q in qs) and [q["id"] for q in qs] == [1, 2, 3]
    assert result["insights_found"] == 1

    b = client.get("/agents/misconceptions/briefing", params={"class_id": BIO, "assignment_id": c.assignment_id}).json()
    assert [m["topic"] for m in b["misconceptions"]] == ["Mitosis versus meiosis"]
    assert b["misconceptions"][0]["suggestion"]["supporting_student_count"] == 3


def test_graded_assignment_still_waits_for_due_date():
    assert not pipeline.analysis_allowed({"mode": "graded", "due_date": "2099-01-01T00:00:00Z"})
    assert pipeline.analysis_allowed({"mode": "graded", "due_date": "2000-01-01T00:00:00Z"})
    assert pipeline.analysis_allowed({"mode": "checkin", "due_date": "2099-01-01T00:00:00Z"})
    # Chats without a question_id are left exactly as they were.
    raw = [{"chat_message_id": 2, "student_id": 1, "content": "b"}, {"chat_message_id": 1, "student_id": 2, "content": "a"}]
    assert pipeline.group_by_question(raw) == raw
