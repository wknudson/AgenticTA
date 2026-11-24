"""Unit packages (games agent): the no-AI generator on the sample Biology course, one approval,
publishing the check-in + games + calendar event, rejecting, and the model regenerate loop
(with fake models). Tests have no keys, so POST /unit-package uses the no-AI generator."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from app.agents.games import models as ai
from app.agents.games import package as pkg
from app.agents.games.extract import NotEnoughMaterial, Source, _Extractor, _dedupe, alternates, build_package
from app.shared.db import connect
from app.shared.student_auth import issue_student_token

BIO = 3
UNIT = "Unit 2: Cell Structure"
STUDENT_KEYS = {"flashcards": {"item_id", "front", "back"}, "matching": {"item_id", "term", "definition"},
                "fill_in": {"item_id", "sentence", "answer", "alternates"}}


def weekday_on_or_after(d: date, weekday: int) -> date:
    return d + timedelta(days=(weekday - d.weekday()) % 7)


# Far-future dates so the check-in is never past due, inside a term set by the `term` fixture.
TERM_START, TERM_END = date(2099, 1, 5), date(2099, 6, 12)
WED = weekday_on_or_after(date(2099, 3, 2), 2)          # lesson on a Wednesday -> due Tuesday


@pytest.fixture(scope="module")
def filed(client):
    client.post("/agents/filing/demo", params={"class_id": BIO})


@pytest.fixture
def term(client):
    """A term for class 3 (restored afterwards, other tests may have their own)."""
    with connect() as conn:
        before = conn.execute("SELECT * FROM term_calendar WHERE class_id = ?", (BIO,)).fetchone()
        before = dict(before) if before else None
        holiday = (WED + timedelta(days=7)).isoformat()
        conn.execute("INSERT OR REPLACE INTO term_calendar (class_id, term_start, term_end, holidays_json, "
                     "max_assessments_per_day) VALUES (?, ?, ?, ?, 2)",
                     (BIO, TERM_START.isoformat(), TERM_END.isoformat(),
                      json.dumps([{"date": holiday, "label": "Spring holiday"}])))
    yield {"holiday": holiday}
    with connect() as conn:
        conn.execute("DELETE FROM term_calendar WHERE class_id = ?", (BIO,))
        if before:
            conn.execute("INSERT INTO term_calendar (class_id, term_start, term_end, holidays_json, "
                         "max_assessments_per_day) VALUES (:class_id, :term_start, :term_end, :holidays_json, "
                         ":max_assessments_per_day)", before)


def make_package(client, **overrides) -> dict:
    body = {"class_id": BIO, "unit": UNIT, "lesson_date": WED.isoformat(), **overrides}
    r = client.post("/agents/games/unit-package", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def approval_for(client, package_id: int) -> dict:
    rows = client.get("/agents/approvals", params={"class_id": BIO, "agent": "games"}).json()["approvals"]
    return next(r for r in rows if r["action_name"] == "publish_unit_package"
                and r["action_args"].get("package_id") == package_id)


def decide(client, package_id: int, decision: str) -> dict:
    row = approval_for(client, package_id)
    r = client.post(f"/agents/approvals/{row['approval_id']}/decide",
                    json={"type": decision, "decided_by": "teacher", "role": "teacher"})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- the no-AI generator
def test_offline_generator_on_the_sample_unit(filed):
    sources, _ = pkg.unit_sources(BIO, UNIT)
    assert sources and all(s.text for s in sources)
    draft = build_package(sources)
    assert draft == build_package(sources), "deterministic"
    material = pkg.material_text(sources)
    stems = pkg._stems(material)

    cards = draft["flashcards"]
    fronts = {c["front"] for c in cards}
    assert len(cards) == 10 and len(fronts) == 10, "card_count cards, no duplicate terms"
    assert {"Nucleus", "Ribosomes", "Prokaryotes", "Eukaryotes"} <= fronts
    assert next(c for c in cards if c["front"] == "Ribosomes")["back"] == "Build proteins."
    assert all(pkg.grounded(c["back"], stems) for c in cards), "every definition comes from the unit's text"

    assert 4 <= len(draft["fill_in"]) <= 8
    for f in draft["fill_in"]:
        assert "____" in f["sentence"] and f["answer"].lower() not in f["sentence"].lower()
    nucleus = next(f for f in draft["fill_in"] if f["answer"] == "Nucleus")
    assert nucleus["sentence"] == "____ stores DNA and controls the cell." and "nuclei" in nucleus["alternates"]

    choice = [q for q in draft["questions"] if q["kind"] == "choice"]
    explain = [q for q in draft["questions"] if q["kind"] == "explain"]
    assert len(choice) == 4 and len(explain) == 2
    for q in choice:
        assert len(q["options"]) in (3, 4) and sum(o["correct"] for o in q["options"]) == 1
        right = next(o["text"] for o in q["options"] if o["correct"])
        assert right.lower() not in q["text"].lower()
        assert len({o["text"] for o in q["options"]}) == len(q["options"])
    assert explain[0]["text"] == "Explain why active transport uses ATP."
    for q in explain:
        assert q["text"].startswith("Explain") and q["answer"] and q["rubric"]
        assert pkg.grounded(q["rubric"], stems)
    assert pkg.check_draft(draft, material) and all(v["ok"] for v in pkg.check_draft(draft, material))


def test_extractor_patterns_on_messy_notes():
    text = """# Glossary
**Osmosis** - water moving across a membrane
- Diffusion: particles spread from high to low concentration
| Term | Meaning |
|---|---|
| Enzyme | a protein that speeds up a reaction |
The sodium-potassium pump moves ions against the gradient.
Electron transport chain (inner membrane): makes most of the ATP.
Day 1: Soak the egg in vinegar.
Which organelle makes ATP?
Respiration is how cells release energy stored in glucose.
Oxygen pulls electrons harder than hydrogen, so water has partial charges."""
    ex = _Extractor([Source(1, "Notes", "lecture", text)]).run()
    facts = {f.term: f.definition for f in _dedupe(ex.facts)}
    assert facts["Osmosis"] == "Water moving across a membrane."
    assert facts["Diffusion"] == "Particles spread from high to low concentration."
    assert facts["Enzyme"] == "A protein that speeds up a reaction."
    assert facts["sodium-potassium pump"] == "Moves ions against the gradient."
    assert facts["Electron transport chain"].startswith("Makes most of the ATP")
    assert facts["Respiration"] == "How cells release energy stored in glucose."
    assert not any(t.lower().startswith(("day", "which")) for t in facts), "labels and questions are skipped"
    assert [r.question for r in ex.reasons] == ["Explain why water has partial charges."]


def test_fill_in_alternates():
    assert "mitochondrion" in alternates("Mitochondria")
    assert "nuclei" in alternates("Nucleus")
    assert "ribosome" in alternates("Ribosomes")
    assert "hypotonic" in alternates("Hypotonic solution")
    assert "krebs" in alternates("Krebs cycle", "The Krebs cycle releases CO2.")
    assert "cell" not in alternates("cell cycle", "the cell cycle")
    assert "light dependent reactions" in alternates("Light-dependent reactions")
    assert alternates("Homozygous") == []


def test_too_little_text_is_not_enough():
    with pytest.raises(NotEnoughMaterial):
        build_package([Source(1, "Tiny", "lecture", "Cells are small. Welcome back, everyone!")])


# ---------------------------------------------------------------- the endpoint + approval
def test_unit_package_waits_for_one_approval_then_publishes(client, filed, term):
    out = make_package(client, tutor_mode="answer_after_tries", tutor_reveal_after=3, mastery_threshold=0.75)
    assert out["status"] == "waiting_for_approval" and len(out["approval_groups"]) == 1
    s = out["summary"]
    assert (s["flashcards"], s["matching"], s["fill_in"], s["mc"], s["explain"], s["generated_by"]) == \
        (10, 8, 8, 4, 2, "offline")

    pid = out["package_id"]
    p = client.get(f"/agents/games/unit-package/{pid}").json()
    assert p["status"] == "draft" and p["assignment_id"] is None and p["unit"] == UNIT
    assert p["settings"]["due_date"] == f"{WED - timedelta(days=1)}T23:59:00.000Z", "evening before the lesson"
    assert p["settings"]["title"] == f"{UNIT} practice + check-in"
    assert [a["kind"] for a in p["activities"]] == ["flashcards", "matching", "fill_in"]
    for a in p["activities"]:
        ids = [it["item_id"] for it in a["items"]]
        assert len(set(ids)) == len(ids) and all(isinstance(i, str) and i for i in ids)
    assert [q["kind"] for q in p["questions"]] == ["choice"] * 4 + ["explain"] * 2

    row = approval_for(client, pid)
    assert row["allowed_decisions"] == ["approve", "reject"] and row["action_args"] == {"class_id": BIO, "package_id": pid}
    assert "Unit 2: Cell Structure" in row["description"] and "4 multiple choice" in row["description"]
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM study_activities WHERE package_id = ? AND status = 'draft'",
                            (pid,)).fetchone()[0] == 3, "nothing is published before approval"

    res = decide(client, pid, "approve")
    assert res["status"] == "resumed" and res["result"]["status"] == "done"
    assert "Calendar: added" in res["result"]["output"]

    p = client.get(f"/agents/games/unit-package/{pid}").json()
    aid = p["assignment_id"]
    assert p["status"] == "published" and aid
    with connect() as conn:
        a = dict(conn.execute("SELECT * FROM assignments WHERE assignment_id = ?", (aid,)).fetchone())
        assert (a["mode"], a["unit"], a["lesson_date"], a["tutor_mode"], a["tutor_reveal_after"], a["max_points"],
                a["type"], a["assignment_name"], a["class_id"]) == \
            ("checkin", UNIT, WED.isoformat(), "answer_after_tries", 3, 10, "Homework", p["settings"]["title"], BIO)
        assert a["mastery_threshold"] == 0.75 and a["due_date"] == p["settings"]["due_date"] and a["description"]
        qs = [dict(r) for r in conn.execute("SELECT * FROM assignment_questions WHERE assignment_id = ? "
                                            "ORDER BY sort_order", (aid,))]
        assert [q["question_type"] for q in qs] == ["multiple_choice"] * 4 + ["short_answer"] * 2
        assert round(sum(q["max_points"] for q in qs), 2) == 10
        for q, src in zip(qs, p["questions"]):
            opts = [dict(o) for o in conn.execute("SELECT * FROM assignment_question_options WHERE question_id = ? "
                                                  "ORDER BY option_id", (q["question_id"],))]
            right = [o for o in opts if o["is_correct"]]
            assert len(right) == 1 and q["correct_answer"] == str(right[0]["option_id"])
            if q["question_type"] == "multiple_choice":
                assert [o["option_text"] for o in opts] == [o["text"] for o in src["options"]]
                assert q["explain_rubric"] is None
            else:
                assert len(opts) == 1 and right[0]["option_text"] == src["answer"]
                assert q["explain_rubric"] == src["rubric"]
        acts = conn.execute("SELECT status, assignment_id FROM study_activities WHERE package_id = ?", (pid,)).fetchall()
        assert [tuple(r) for r in acts] == [("published", aid)] * 3
        ev = [dict(r) for r in conn.execute("SELECT * FROM calendar_events WHERE assignment_id = ?", (aid,))]
    assert len(ev) == 1
    assert (ev[0]["title"], ev[0]["kind"], ev[0]["date"], ev[0]["status"], ev[0]["source"], ev[0]["class_id"]) == \
        (f"{p['settings']['title']} due", "assignment_due", (WED - timedelta(days=1)).isoformat(), "published",
         "unit package", BIO)

    # The student sees the games, but nothing from the check-in's answer key.
    r = client.get(f"/agents/games/practice/{aid}", headers={"Authorization": f"Bearer {issue_student_token(2)}"})
    assert r.status_code == 200
    body = r.json()
    assert body["assignment"] == {"assignment_id": aid, "title": p["settings"]["title"], "unit": UNIT,
                                  "lesson_date": WED.isoformat(), "due_date": a["due_date"]}
    assert [x["kind"] for x in body["activities"]] == ["flashcards", "matching", "fill_in"]
    for act in body["activities"]:
        assert all(set(it) == STUDENT_KEYS[act["kind"]] for it in act["items"]), "no sources or review notes"
    assert body["stats"]["total"] == 26 and body["stats"]["threshold"] == 0.75 and body["progress"] == {}
    raw = json.dumps(body)
    for q in p["questions"]:
        assert q["text"] not in raw
        if q["kind"] == "explain":
            assert q["answer"] not in raw and q["rubric"] not in raw
    assert "is_correct" not in raw and "rubric" not in raw and "review" not in raw


@pytest.mark.parametrize("case", ["weekend", "holiday", "outside the term", "busy day"])
def test_calendar_event_only_when_the_due_date_passes_the_rules(client, filed, term, case):
    lesson = {"weekend": weekday_on_or_after(date(2099, 4, 6), 0),            # Monday -> due Sunday
              "holiday": date.fromisoformat(term["holiday"]) + timedelta(days=1),
              "outside the term": weekday_on_or_after(TERM_END + timedelta(days=10), 2),
              "busy day": weekday_on_or_after(date(2099, 5, 3), 3)}[case]
    due = lesson - timedelta(days=1)
    if case == "busy day":
        with connect() as conn:
            for title in ("Quiz A", "Lab B"):
                conn.execute("INSERT INTO calendar_events (class_id, title, kind, date, status) "
                             "VALUES (?, ?, 'assessment', ?, 'published')", (BIO, title, due.isoformat()))
    out = make_package(client, lesson_date=lesson.isoformat(), title=f"Calendar case {case}")
    res = decide(client, out["package_id"], "approve")
    text = res["result"]["output"]
    assert "Calendar: no event added" in text
    assert {"weekend": "weekend", "holiday": "Spring holiday", "outside the term": "outside the term",
            "busy day": "max 2"}[case] in text
    aid = client.get(f"/agents/games/unit-package/{out['package_id']}").json()["assignment_id"]
    with connect() as conn:
        assert aid and conn.execute("SELECT COUNT(*) FROM calendar_events WHERE assignment_id = ?",
                                    (aid,)).fetchone()[0] == 0


def test_reject_publishes_nothing(client, filed):
    out = make_package(client, title="Rejected package", mc_count=2, explain_count=1, card_count=6)
    assert (out["summary"]["flashcards"], out["summary"]["mc"], out["summary"]["explain"]) == (6, 2, 1)
    res = decide(client, out["package_id"], "reject")
    assert res["result"]["status"] == "done" and "rejected" in res["result"]["output"]
    p = client.get(f"/agents/games/unit-package/{out['package_id']}").json()
    assert p["status"] == "rejected" and p["assignment_id"] is None
    with connect() as conn:
        statuses = {r[0] for r in conn.execute("SELECT status FROM study_activities WHERE package_id = ?",
                                               (out["package_id"],))}
        assert statuses == {"rejected"}
        assert conn.execute("SELECT COUNT(*) FROM assignments WHERE assignment_name = 'Rejected package'").fetchone()[0] == 0


def test_409_without_filed_text_or_enough_terms(client, filed):
    r = client.post("/agents/games/unit-package", json={"class_id": BIO, "unit": "Unit 42: Nothing Here",
                                                         "lesson_date": WED.isoformat()})
    assert r.status_code == 409 and "no filed text" in r.json()["detail"]
    with connect() as conn:
        fid = conn.execute("INSERT INTO library_files (class_id, original_name, stored_path, title, doc_type, unit, "
                           "status) VALUES (?, 'tiny.txt', 'test/tiny.txt', 'Tiny notes', 'lecture', 'Unit 9: Tiny', "
                           "'filed')", (BIO,)).lastrowid
        conn.execute("INSERT INTO library_chunks (file_id, chunk_idx, text) VALUES (?, 0, ?)",
                     (fid, "Cells are small. Welcome back, everyone!"))
    try:
        r = client.post("/agents/games/unit-package", json={"class_id": BIO, "unit": "Unit 9: Tiny",
                                                             "lesson_date": WED.isoformat()})
        assert r.status_code == 409 and "Only found" in r.json()["detail"]
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM library_chunks WHERE file_id = ?", (fid,))
            conn.execute("DELETE FROM library_files WHERE file_id = ?", (fid,))
    assert client.post("/agents/games/unit-package", json={"class_id": 999, "unit": UNIT,
                                                            "lesson_date": WED.isoformat()}).status_code == 404
    assert client.post("/agents/games/unit-package", json={"class_id": BIO, "unit": UNIT, "lesson_date": WED.isoformat(),
                                                            "mc_count": 0, "explain_count": 0}).status_code == 422


def test_explicit_due_date_and_percent_threshold(client, filed):
    out = make_package(client, due_date=(WED - timedelta(days=2)).isoformat(), mastery_threshold=90,
                       title="Explicit due date")
    p = client.get(f"/agents/games/unit-package/{out['package_id']}").json()
    assert p["settings"]["due_date"] == f"{WED - timedelta(days=2)}T23:59:00.000Z"
    assert p["settings"]["mastery_threshold"] == 0.9
    decide(client, out["package_id"], "reject")


# ---------------------------------------------------------------- the model path (fake models)
GOOD_CARDS = [("Nucleus", "Stores DNA and controls the cell."), ("Ribosomes", "Build proteins."),
              ("Mitochondria", "Release energy from food."), ("Chloroplasts", "Capture light energy in plants.")]
GOOD_FILL = [{"sentence": f"____ {back[0].lower()}{back[1:]}", "answer": term, "alternates": [], "source": ""}
             for term, back in GOOD_CARDS]
GOOD_QUESTIONS = [
    {"text": "Which organelle builds proteins?", "kind": "choice", "source": "q",
     "options": [{"text": "Nucleus", "correct": False}, {"text": "Ribosomes", "correct": True},
                 {"text": "Chloroplasts", "correct": False}]},
    {"text": "Explain why active transport needs ATP.", "kind": "explain", "source": "q",
     "answer": "It moves things against the concentration gradient, which takes energy.",
     "rubric": "Active transport uses ATP to move things against the concentration gradient."},
]


def test_model_path_regenerates_what_the_reviewer_rejects(client, filed, monkeypatch):
    calls = []

    def fake_generate(sources, unit, need, *, avoid=None, rejected=None):
        calls.append({"need": dict(need), "avoid": list(avoid or []), "rejected": list(rejected or [])})
        if len(calls) == 1:
            cards = [{"front": t, "back": b, "source": "q"} for t, b in GOOD_CARDS[:3]]
            cards.append({"front": "Golgi", "back": "Makes pizza for the cell.", "source": "made up"})
            return {"flashcards": cards, "fill_in": GOOD_FILL, "questions": GOOD_QUESTIONS}
        return {"flashcards": [{"front": GOOD_CARDS[3][0], "back": GOOD_CARDS[3][1], "source": "q"}],
                "fill_in": [], "questions": []}

    def fake_review(sources, draft):
        return [{"ref": f"flashcards {i}", "ok": c["front"] != "Golgi",
                 "note": "not in the material" if c["front"] == "Golgi" else "", "by": "reviewer"}
                for i, c in enumerate(draft["flashcards"], 1)]

    monkeypatch.setattr(ai, "models_ready", lambda: True)
    monkeypatch.setattr(ai, "generator_name", lambda: "fake-gen")
    monkeypatch.setattr(ai, "generate_package", fake_generate)
    monkeypatch.setattr(ai, "review_package", fake_review)
    out = make_package(client, card_count=4, mc_count=1, explain_count=1, title="Model path")
    assert out["summary"]["generated_by"] == "fake-gen"
    assert len(calls) == 2, "one regenerate round for the rejected card"
    assert calls[1]["need"] == {"flashcards": 1, "fill_in": 0, "choice": 0, "explain": 0}
    assert calls[1]["rejected"][0]["kind"] == "flashcards" and "Golgi" not in calls[1]["avoid"]
    p = client.get(f"/agents/games/unit-package/{out['package_id']}").json()
    fronts = [it["front"] for it in p["activities"][0]["items"]]
    assert fronts == ["Nucleus", "Ribosomes", "Mitochondria", "Chloroplasts"]
    assert p["review"]["attempts"] == 2 and p["review"]["dropped"] == []
    assert any(not v["ok"] and "Golgi" not in fronts for v in p["review"]["verdicts"])
    decide(client, out["package_id"], "reject")


def test_model_failure_falls_back_to_the_no_ai_generator(client, filed, monkeypatch):
    def boom(*_, **__):
        raise RuntimeError("provider down")

    monkeypatch.setattr(ai, "models_ready", lambda: True)
    monkeypatch.setattr(ai, "generate_package", boom)
    monkeypatch.setattr(ai, "review_package", lambda *_: pytest.fail("no AI review after falling back"))
    out = make_package(client, title="Fallback")
    assert out["summary"]["generated_by"] == "offline" and out["summary"]["flashcards"] == 10
    p = client.get(f"/agents/games/unit-package/{out['package_id']}").json()
    assert any("AI generation failed (RuntimeError)" in n for n in p["review"]["notes"])
    decide(client, out["package_id"], "reject")


def test_structured_outputs_become_the_draft_shape(monkeypatch):
    """models.py with a fake structured-output model: PackageOut / ReviewOut -> draft + verdicts."""
    prompts = []

    class Fake:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, messages):
            prompts.append(messages[-1][1])
            if self.schema is ai.ReviewOut:
                return ai.ReviewOut(verdicts=[ai.Verdict(ref="flashcards 1", ok=False, problem="too vague")])
            return ai.PackageOut(
                cards=[ai.CardOut(term="Ribosomes", definition="Build proteins.", source_quote="Ribosomes build proteins.")],
                fill_in=[ai.FillInOut(sentence="____ build proteins.", answer="Ribosomes")],
                choice=[ai.ChoiceOut(question="Which organelle builds proteins?", correct="Ribosomes",
                                     distractors=["Nucleus", "Chloroplasts"], source_quote="Ribosomes build proteins.")],
                explain=[ai.ExplainOut(question="Explain why cells need ribosomes.", model_answer="They build proteins.",
                                       rubric="Ribosomes build proteins.")])

    monkeypatch.setattr(ai, "get_model", lambda agent, role: type("M", (), {"with_structured_output":
                                                                           lambda self, schema: Fake(schema)})())
    src = [Source(1, "Slides", "lecture", "Ribosomes build proteins. Nucleus stores DNA.")]
    draft = ai.generate_package(src, UNIT, {"flashcards": 1, "fill_in": 1, "choice": 1, "explain": 1},
                                rejected=[{"kind": "flashcards", "item": {"front": "Golgi"}, "problem": "made up"}])
    assert "Golgi -> made up" in prompts[-1] and "Ribosomes build proteins." in prompts[-1]
    assert draft["flashcards"] == [{"front": "Ribosomes", "back": "Build proteins.", "source": "Ribosomes build proteins."}]
    assert draft["fill_in"][0]["alternates"] == ["ribosome"]
    mc, ex = draft["questions"]
    assert sorted(o["text"] for o in mc["options"]) == ["Chloroplasts", "Nucleus", "Ribosomes"]
    assert [o["text"] for o in mc["options"] if o["correct"]] == ["Ribosomes"]
    assert (ex["kind"], ex["answer"], ex["rubric"]) == ("explain", "They build proteins.", "Ribosomes build proteins.")
    assert all(v["ok"] for v in pkg.check_draft(draft, src[0].text))
    verdicts = ai.review_package(src, draft)
    assert verdicts == [{"ref": "flashcards 1", "ok": False, "note": "too vague", "by": "reviewer"}]
    merged = pkg.combine(pkg.check_draft(draft, src[0].text), verdicts)
    accepted, rejected = pkg.split_by_verdicts(draft, merged)
    assert accepted["flashcards"] == [] and rejected[0]["problem"] == "reviewer: too vague"


def test_offline_flag_skips_models_even_with_keys(client, filed, monkeypatch):
    monkeypatch.setattr(ai, "models_ready", lambda: True)
    monkeypatch.setattr(ai, "generate_package", lambda *_, **__: pytest.fail("offline=true must not call a model"))
    out = make_package(client, offline=True, title="Offline flag")
    assert out["summary"]["generated_by"] == "offline"
    decide(client, out["package_id"], "reject")
