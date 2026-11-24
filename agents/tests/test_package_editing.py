"""Editing a draft unit package before approving it (games agent, editing.py):
PATCH validation, edits that persist, publishing the edited content, regenerating one question or
card (no-AI path, model path, fallback), and 409 once the package isn't a draft. Tests have no
keys, so packages come from the no-AI generator."""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta

import pytest

from app.agents.games import models as ai
from app.shared.db import connect
from app.shared.student_auth import issue_student_token

BIO = 3
UNIT = "Unit 2: Cell Structure"
LESSON = date(2099, 3, 4)            # a Wednesday, far in the future (never past due)


@pytest.fixture(scope="module")
def filed(client):
    client.post("/agents/filing/demo", params={"class_id": BIO})


@pytest.fixture(scope="module")
def validation_draft(client, filed):
    """One draft for the validation tests (failed edits leave it unchanged); rejected at the end
    so no stray pending approval is left for other tests."""
    pid = make_package(client, title="Validation draft", mc_count=2, explain_count=1)
    yield pid
    if get(client, pid)["status"] == "draft":
        decide(client, pid, "reject")


def make_package(client, **overrides) -> int:
    body = {"class_id": BIO, "unit": UNIT, "lesson_date": LESSON.isoformat(), **overrides}
    r = client.post("/agents/games/unit-package", json=body)
    assert r.status_code == 200, r.text
    return r.json()["package_id"]


def get(client, pid: int) -> dict:
    r = client.get(f"/agents/games/unit-package/{pid}")
    assert r.status_code == 200, r.text
    return r.json()


def approval_for(client, pid: int) -> dict:
    rows = client.get("/agents/approvals", params={"class_id": BIO, "agent": "games"}).json()["approvals"]
    return next(r for r in rows if r["action_name"] == "publish_unit_package" and r["action_args"]["package_id"] == pid)


def decide(client, pid: int, decision: str) -> dict:
    r = client.post(f"/agents/approvals/{approval_for(client, pid)['approval_id']}/decide",
                    json={"type": decision, "decided_by": "teacher", "role": "teacher"})
    assert r.status_code == 200, r.text
    return r.json()


def patch(client, pid: int, body: dict):
    return client.patch(f"/agents/games/unit-package/{pid}", json=body)


def regen(client, pid: int, body: dict):
    return client.post(f"/agents/games/unit-package/{pid}/regenerate", json=body)


def act(p: dict, kind: str) -> dict:
    return next(a for a in p["activities"] if a["kind"] == kind)


# ---------------------------------------------------------------- PATCH
def test_edits_persist_and_publish_uses_the_edited_content(client, filed):
    pid = make_package(client, title="Edit me", mc_count=3, explain_count=1)
    p = get(client, pid)
    questions = copy.deepcopy(p["questions"])
    questions[0]["text"] = "Which organelle stores DNA and controls the cell?"
    questions[0]["options"] = [{"text": "Nucleus", "correct": True}, {"text": "Ribosomes", "correct": False},
                               {"text": "Cell wall", "correct": False}]
    del questions[1]
    questions.append({"text": "Explain why plant cells have a cell wall.", "kind": "explain",
                      "answer": "It supports and protects the cell.", "rubric": "The cell wall supports the plant cell."})
    fc = act(p, "flashcards")
    old_ids = [it["item_id"] for it in fc["items"]]
    items = copy.deepcopy(fc["items"])
    items[0]["back"] = "Holds the DNA; the control center."
    del items[1]
    items.append({"front": "Vacuole", "back": "Stores water in plant cells."})
    fill = act(p, "fill_in")
    fill_items = copy.deepcopy(fill["items"])
    fill_items[0]["sentence"] = "The ___ is where the cell keeps its DNA."      # 3 underscores: normalized
    fill_items[0]["answer"] = "nucleus"
    fill_items[0]["alternates"] = "nuclei, Nucleus, , nuclei"                  # a comma list is fine too

    r = patch(client, pid, {
        "questions": questions,
        "activities": [{"activity_id": fc["activity_id"], "items": items},
                       {"activity_id": fill["activity_id"], "items": fill_items}],
        "settings": {"title": "Edited title", "mastery_threshold": 70, "tutor_mode": "answer_after_tries",
                     "tutor_reveal_after": 3},
    })
    assert r.status_code == 200, r.text
    out = r.json()
    assert isinstance(out["warnings"], list)
    saved = out["package"]
    assert saved == get(client, pid), "the response is the stored package"
    assert [q["text"] for q in saved["questions"]] == [q["text"] for q in questions]
    assert saved["questions"][-1]["source"] == "teacher" and saved["questions"][0]["source"] == p["questions"][0]["source"]
    new_fc = act(saved, "flashcards")["items"]
    assert [it["item_id"] for it in new_fc[:-1]] == [old_ids[0]] + old_ids[2:], "existing ids are kept"
    assert new_fc[0]["back"] == "Holds the DNA; the control center." and new_fc[0]["source"] == fc["items"][0]["source"]
    assert new_fc[-1]["front"] == "Vacuole" and new_fc[-1]["item_id"] not in old_ids
    assert new_fc[-1]["item_id"] == f"fc{len(old_ids) + 1}", "a fresh id, never a deleted card's"
    f0 = act(saved, "fill_in")["items"][0]
    assert f0["sentence"] == "The ____ is where the cell keeps its DNA." and f0["alternates"] == ["nuclei"]
    assert f0["item_id"] == fill["items"][0]["item_id"]
    assert act(saved, "matching")["items"] == act(p, "matching")["items"], "games not in the PATCH are untouched"
    s = saved["settings"]
    assert (s["title"], s["mastery_threshold"], s["tutor_mode"], s["tutor_reveal_after"]) == \
        ("Edited title", 0.7, "answer_after_tries", 3)
    assert s["lesson_date"] == p["settings"]["lesson_date"] and s["due_date"] == p["settings"]["due_date"]
    assert saved["review"]["edit_warnings"] == out["warnings"]
    desc = approval_for(client, pid)["description"]
    assert "Edited title" in desc and "2 multiple choice + 2 explain-why" in desc, "the inbox headline follows"

    res = decide(client, pid, "approve")
    assert res["result"]["status"] == "done"
    final = get(client, pid)
    aid = final["assignment_id"]
    assert final["status"] == "published" and aid
    with connect() as conn:
        a = dict(conn.execute("SELECT * FROM assignments WHERE assignment_id = ?", (aid,)).fetchone())
        assert (a["assignment_name"], a["mastery_threshold"], a["tutor_mode"], a["tutor_reveal_after"]) == \
            ("Edited title", 0.7, "answer_after_tries", 3)
        qs = [dict(r) for r in conn.execute("SELECT * FROM assignment_questions WHERE assignment_id = ? "
                                            "ORDER BY sort_order", (aid,))]
        assert [q["question_text"] for q in qs] == [q["text"] for q in questions]
        opts = conn.execute("SELECT option_text, is_correct FROM assignment_question_options WHERE question_id = ? "
                            "ORDER BY option_id", (qs[0]["question_id"],)).fetchall()
        assert [tuple(o) for o in opts] == [("Nucleus", 1), ("Ribosomes", 0), ("Cell wall", 0)]
        last = qs[-1]
        assert last["question_type"] == "short_answer" and last["explain_rubric"] == "The cell wall supports the plant cell."
        assert conn.execute("SELECT option_text FROM assignment_question_options WHERE question_id = ? AND is_correct = 1",
                            (last["question_id"],)).fetchone()[0] == "It supports and protects the cell."
        stored = json.loads(conn.execute("SELECT items_json FROM study_activities WHERE activity_id = ?",
                                         (fc["activity_id"],)).fetchone()[0])
        assert stored == new_fc
    body = client.get(f"/agents/games/practice/{aid}",
                      headers={"Authorization": f"Bearer {issue_student_token(2)}"}).json()
    student_fc = next(x for x in body["activities"] if x["kind"] == "flashcards")["items"]
    assert [it["front"] for it in student_fc] == [it["front"] for it in new_fc]
    assert all("source" not in it for it in student_fc)

    # Published: no more edits.
    r = patch(client, pid, {"settings": {"title": "Too late"}})
    assert r.status_code == 409 and "already published" in r.json()["detail"]
    r = regen(client, pid, {"kind": "question", "index": 0})
    assert r.status_code == 409


@pytest.mark.parametrize("break_it, message", [
    (lambda q, a: q[0].update(options=q[0]["options"][:1]), "Question 1: give it at least 2 answer options."),
    (lambda q, a: [o.update(correct=True) for o in q[0]["options"]], "Question 1: only one option can be"),
    (lambda q, a: [o.update(correct=False) for o in q[0]["options"]], "Question 1: mark which option is the right"),
    (lambda q, a: q[0]["options"][1].update(text="  "), "Question 1: an answer option is empty."),
    (lambda q, a: q[0].update(text=""), "Question 1: write the question."),
    (lambda q, a: q[-1].update(answer=""), "write a model answer."),
    (lambda q, a: q.clear(), "Keep at least one check-in question."),
    (lambda q, a: a["fill_in"]["items"][0].update(sentence="No blank in this one."), "needs a blank, written ____"),
    (lambda q, a: a["flashcards"]["items"][2].update(back=""), "Flashcard 3: fill in the back."),
], ids=["one option", "two right", "none right", "empty option", "no text", "no model answer", "no questions",
        "no blank", "empty back"])
def test_hard_rules_are_422_and_change_nothing(client, validation_draft, break_it, message):
    pid = validation_draft
    before = get(client, pid)
    q, acts = copy.deepcopy(before["questions"]), {a["kind"]: copy.deepcopy(a) for a in before["activities"]}
    break_it(q, acts)
    r = patch(client, pid, {"questions": q, "activities": [{"activity_id": a["activity_id"], "items": a["items"]}
                                                           for a in acts.values()]})
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, str) and detail.startswith("Can't save yet.") and message in detail
    assert get(client, pid) == before


def test_other_422s_404s_and_warnings(client, validation_draft):
    pid = validation_draft
    before = get(client, pid)
    ids = {a["kind"]: a["activity_id"] for a in before["activities"]}
    # Too few practice cards across all games (the hard minimum is 4).
    r = patch(client, pid, {"activities": [{"activity_id": ids["flashcards"], "items": []},
                                           {"activity_id": ids["matching"], "items": []},
                                           {"activity_id": ids["fill_in"], "items": act(before, "fill_in")["items"][:2]}]})
    assert r.status_code == 422 and "Keep at least 4 practice cards" in r.json()["detail"]
    r = patch(client, pid, {"activities": [{"activity_id": 999999, "items": []}]})
    assert r.status_code == 422 and "isn't part of this package" in r.json()["detail"]
    r = patch(client, pid, {"settings": {"due_date": (LESSON + timedelta(days=2)).isoformat()}})
    assert r.status_code == 422 and "on or before the lesson" in r.json()["detail"]
    r = patch(client, pid, {"settings": {"title": "  ", "tutor_mode": "whatever", "mastery_threshold": 0}})
    detail = r.json()["detail"]
    assert r.status_code == 422 and "title" in detail and "tutor mode" in detail and "mastery threshold" in detail
    assert get(client, pid) == before
    assert patch(client, 999999, {"settings": {"title": "x"}}).status_code == 404

    # Soft checks come back as warnings, pointing at the question / card.
    q = copy.deepcopy(before["questions"])
    right = next(o["text"] for o in q[0]["options"] if o["correct"])
    q[0]["text"] = f"Is the answer {right}?"
    fc = copy.deepcopy(act(before, "flashcards")["items"])
    fc[1]["front"] = fc[0]["front"]
    r = patch(client, pid, {"questions": q, "activities": [{"activity_id": ids["flashcards"], "items": fc},
                                                           {"activity_id": ids["matching"], "items": []}]})
    assert r.status_code == 200, r.text
    w = r.json()["warnings"]
    assert {"target": "question", "index": 0, "label": "Question 1", "note": "the question gives away the answer"} in w
    assert any(x["target"] == "item" and x["item_id"] == fc[1]["item_id"] and "same term as card 1" in x["note"] for x in w)
    assert any(x["target"] == "activity" and x["activity_id"] == ids["matching"] for x in w), "an emptied game"
    assert get(client, pid)["review"]["edit_warnings"] == w

    # Moving the lesson moves the default due date with it.
    r = patch(client, pid, {"settings": {"lesson_date": (LESSON + timedelta(days=7)).isoformat()}})
    s = r.json()["package"]["settings"]
    assert r.status_code == 200 and s["due_date"] == f"{LESSON + timedelta(days=6)}T23:59:00.000Z"
    assert s["due_day"] == (LESSON + timedelta(days=6)).isoformat()



# ---------------------------------------------------------------- regenerate
def test_regenerate_no_ai_is_deterministic_and_walks_forward(client, filed):
    a, b = (make_package(client, title=f"Regen {n}", card_count=6, mc_count=2, explain_count=1) for n in "AB")
    pa, pb = get(client, a), get(client, b)

    r = regen(client, a, {"kind": "question", "index": 0})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["generated_by"] == "offline" and out["note"] is None and out["replaced"] == {"kind": "question", "index": 0}
    q0 = out["package"]["questions"][0]
    assert q0["kind"] == "choice" and q0["text"] not in [q["text"] for q in pa["questions"]]
    assert sum(o["correct"] for o in q0["options"]) == 1
    assert out["package"]["questions"][1:] == pa["questions"][1:], "only that question changes"
    assert regen(client, b, {"kind": "question", "index": 0}).json()["package"]["questions"][0] == q0, "deterministic"

    ex = len(pa["questions"]) - 1
    r = regen(client, a, {"kind": "question", "index": ex})
    assert r.status_code == 200 and r.json()["package"]["questions"][ex]["kind"] == "explain"
    assert r.json()["package"]["questions"][ex]["text"] != pa["questions"][ex]["text"]

    fc = act(pa, "flashcards")
    r = regen(client, a, {"kind": "item", "activity_id": fc["activity_id"], "item_id": fc["items"][0]["item_id"]})
    new = act(r.json()["package"], "flashcards")["items"]
    assert new[0]["item_id"] == fc["items"][0]["item_id"] and new[0]["front"] != fc["items"][0]["front"]
    assert new[0]["front"] not in [it["front"] for it in fc["items"]] and new[1:] == fc["items"][1:]

    # Again and again on one matching pair: never repeats a term, then a friendly 409.
    m = act(pa, "matching")
    item_id, seen = m["items"][0]["item_id"], {it["term"].lower() for it in m["items"]}
    for _ in range(200):
        r = regen(client, a, {"kind": "item", "activity_id": m["activity_id"], "item_id": item_id})
        if r.status_code != 200:
            break
        term = next(it for it in act(r.json()["package"], "matching")["items"] if it["item_id"] == item_id)["term"]
        assert term.lower() not in seen
        seen.add(term.lower())
    assert r.status_code == 409 and "No more no-AI suggestions for this matching pair" in r.json()["detail"]
    assert len(seen) > len(m["items"]) + 3

    assert regen(client, a, {"kind": "question", "index": 99}).status_code == 404
    assert regen(client, a, {"kind": "item", "activity_id": fc["activity_id"], "item_id": "nope"}).status_code == 404
    assert regen(client, a, {"kind": "question"}).status_code == 422
    decide(client, a, "reject")
    decide(client, b, "reject")
    assert regen(client, a, {"kind": "question", "index": 0}).status_code == 409
    assert patch(client, a, {"settings": {"title": "x"}}).json()["detail"].startswith("This package is already rejected")


def test_regenerate_model_path_and_fallback(client, filed, monkeypatch):
    pid = make_package(client, title="Regen model", card_count=6, mc_count=1, explain_count=1)   # no keys: no-AI draft
    p = get(client, pid)
    fc = act(p, "flashcards")
    target = fc["items"][2]["item_id"]
    calls = []

    def fake_generate(sources, unit, need, *, avoid=None, rejected=None):
        calls.append({"need": need, "avoid": avoid, "rejected": rejected})
        return {"flashcards": [{"front": "Cytoskeleton", "back": "Gives the cell its shape.", "source": "q"}],
                "fill_in": [], "questions": []}

    monkeypatch.setattr(ai, "models_ready", lambda: True)
    monkeypatch.setattr(ai, "generator_name", lambda: "fake-gen")
    monkeypatch.setattr(ai, "generate_package", fake_generate)
    r = regen(client, pid, {"kind": "item", "activity_id": fc["activity_id"], "item_id": target})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["generated_by"] == "fake-gen" and out["note"] is None
    assert calls[0]["need"] == {"flashcards": 1} and fc["items"][0]["front"] in calls[0]["avoid"]
    assert calls[0]["rejected"][0]["item"] == {"front": fc["items"][2]["front"]}
    item = act(out["package"], "flashcards")["items"][2]
    assert item == {"item_id": target, "front": "Cytoskeleton", "back": "Gives the cell its shape.", "source": "q"}

    def boom(*_, **__):
        raise RuntimeError("provider down")

    monkeypatch.setattr(ai, "generate_package", boom)
    r = regen(client, pid, {"kind": "question", "index": 0})
    assert r.status_code == 200 and r.json()["generated_by"] == "offline"
    assert "AI regeneration failed (RuntimeError)" in r.json()["note"]

    monkeypatch.setattr(ai, "generate_package", lambda *_, **__: pytest.fail("offline=true must not call a model"))
    r = regen(client, pid, {"kind": "item", "activity_id": fc["activity_id"], "item_id": target, "offline": True})
    assert r.status_code == 200 and r.json()["generated_by"] == "offline"
    decide(client, pid, "reject")
