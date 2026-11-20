import json
from types import SimpleNamespace

import pytest
import langsmith
from datetime import datetime, timezone

from app.shared.db import connect
from app.agents.scheduler.calendar import TermSettings, save_term, validate_events
from app.agents.scheduler.tools import propose_events, publish_calendar
from app.agents.misconceptions import pipeline

TERM = {"term_start": "2026-09-01", "term_end": "2026-12-18", "holidays": [], "max_per_day": 2}


@pytest.fixture
def calendar_class(client):
    with connect() as conn:
        row = conn.execute("SELECT * FROM term_calendar WHERE class_id = 2").fetchone()
        backup = dict(row) if row else None
    yield 2
    with connect() as conn:
        conn.execute("DELETE FROM calendar_events WHERE class_id = 2")
        conn.execute("DELETE FROM term_calendar WHERE class_id = 2")
        if backup:
            conn.execute("INSERT INTO term_calendar VALUES (?, ?, ?, ?, ?)", tuple(backup.values()))


def test_term_round_trip_and_validation(client, calendar_class):
    assert client.get('/agents/scheduler/term?class_id=2').json()['term'] is None
    assert client.post('/agents/scheduler/run', json={"class_id": 2}).status_code == 409
    assert client.put('/agents/scheduler/term?class_id=2', json=TERM).status_code == 200
    assert client.get('/agents/scheduler/term?class_id=2').json()['term'] == TERM
    for changes in [
        {"term_end": "2026-08-01"}, {"max_per_day": 0},
        {"holidays": [{"date": "2027-01-01", "label": "Outside"}]},
        {"holidays": [{"date": "2026-10-01"}, {"date": "2026-10-01"}]},
    ]:
        assert client.put('/agents/scheduler/term?class_id=2', json={**TERM, **changes}).status_code == 422
    assert client.get('/agents/scheduler/term?class_id=2').json()['term'] == TERM


def test_conflicts_cover_invalid_dates_weekends_holidays_and_capacity():
    term = {**TERM, "holidays": [{"date": "2026-11-26", "label": "Break"}]}
    cases = [("2026-08-31", "outside"), ("2026-09-05", "weekend"),
             ("2026-11-26", "holiday"), ("2026-02-30", "YYYY-MM-DD")]
    for day, expected in cases:
        result = validate_events(term, [{"title": "Quiz", "date": day, "kind": "assessment"}])
        assert not result['ok'] and expected in str(result['problems'])
    e = {"title": "Quiz", "date": "2026-09-03", "kind": "assessment"}
    assert not validate_events(term, [e], [e, e])['ok']
    assert validate_events(term, [e])['ok']
    assert not validate_events(None, [e])['ok']


def test_proposal_and_stale_approval_cannot_bypass_rules(client, calendar_class):
    save_term(2, TermSettings(**TERM))
    bad = {"title": "Weekend", "date": "2026-09-05", "kind": "assessment"}
    rejected = json.loads(propose_events.invoke({"class_id": 2, "events": [bad]}))
    assert rejected['proposed_event_ids'] == []
    event = {"title": "Quiz", "date": "2026-09-03", "kind": "assessment"}
    ids = json.loads(propose_events.invoke({"class_id": 2, "events": [event]}))['proposed_event_ids']
    save_term(2, TermSettings(**{**TERM, "holidays": [{"date": event['date'], "label": "New holiday"}]}))
    result = json.loads(publish_calendar.invoke({"class_id": 2, "event_ids": ids}))
    assert result['published'] == 0
    assert 'holiday' in str(result['problems'])
    assert json.loads(publish_calendar.invoke({"class_id": 2, "event_ids": []}))['published'] == 0
    rows = client.get('/agents/scheduler/events?class_id=2&status=published').json()['events']
    assert rows == []


def test_approval_publishes_only_the_reviewed_ids(client, calendar_class):
    save_term(2, TermSettings(**TERM))
    demo = client.post('/agents/scheduler/demo?class_id=2').json()
    assert demo['status'] == 'waiting_for_approval'
    extra = {"title": "Later draft", "date": "2026-09-04", "kind": "reading"}
    ids = json.loads(propose_events.invoke({"class_id": 2, "events": [extra]}))['proposed_event_ids']
    approval = client.get('/agents/approvals?class_id=2&agent=scheduler').json()['approvals'][0]
    assert ids[0] not in approval['action_args']['event_ids']
    client.post(f"/agents/approvals/{approval['approval_id']}/decide", json={"type": "approve"})
    events = client.get('/agents/scheduler/events?class_id=2').json()['events']
    assert next(e for e in events if e['event_id'] == ids[0])['status'] == 'proposed'
    assert sum(e['status'] == 'published' for e in events) == 2


def test_raw_chats_and_redaction_are_not_traceable():
    assert not hasattr(pipeline.load_chats, '__langsmith_traceable__')
    assert not hasattr(pipeline.redact, '__langsmith_traceable__')
    text = pipeline.scrub('Alice Johnson alice@school.edu +1 (801) 555-1212; 801.555.1234', ['Alice', 'Johnson'])
    assert 'Alice' not in text and 'Johnson' not in text and '@' not in text and '555' not in text


def test_analysis_opens_only_after_assignment_due_date():
    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    assert pipeline.due_date_status("2026-11-20T11:59:00Z", now=now) == "eligible"
    assert pipeline.due_date_status("2026-11-20T12:00:00Z", now=now) == "upcoming"
    assert pipeline.due_date_status("2026-11-21", now=now) == "upcoming"
    assert pipeline.due_date_status(None, now=now) == "no_due_date"


def test_run_rejects_assignment_before_due_date(client):
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO assignments (class_id, assignment_name, due_date) VALUES (?, ?, ?)",
            (1, "Future evidence check", "2099-01-01T00:00:00.000Z"),
        )
        assignment_id = cur.lastrowid
    try:
        response = client.post("/agents/misconceptions/run", params={"class_id": 1, "assignment_id": assignment_id})
        assert response.status_code == 409
        assert "after the assignment due date" in response.json()["detail"]
        with pytest.raises(pipeline.AssignmentNotDue):
            pipeline.run(1, assignment_id, offline=True)
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM assignments WHERE assignment_id = ?", (assignment_id,))


def test_manual_course_run_does_not_require_assignment(client, monkeypatch):
    from importlib import import_module

    router = import_module("app.agents.misconceptions.router")
    calls = []
    monkeypatch.setattr(router, "require_models", lambda *args: None)
    monkeypatch.setattr(router, "run_pipeline", lambda class_id, assignment_id: calls.append((class_id, assignment_id)) or {
        "questions_analyzed": 0, "chats_read": 0, "insights_found": 0, "insights_suppressed": 0,
    })
    response = client.post("/agents/misconceptions/run", params={"class_id": 1})
    assert response.status_code == 200
    assert calls == [(1, None)]


def test_offline_course_demo_does_not_require_assignment(client):
    response = client.post("/agents/misconceptions/demo", params={"class_id": 1})
    assert response.status_code == 200
    assert "questions_analyzed" in response.json()


def test_weak_evidence_is_held_back(client, monkeypatch):
    monkeypatch.setattr(pipeline, "load_chats", lambda *args: [
        {"chat_message_id": 1, "student_id": 1, "assignment_id": 1, "content": "Does mitosis make two cells?"},
        {"chat_message_id": 2, "student_id": 2, "assignment_id": 1, "content": "Does meiosis make two cells?"},
    ])
    monkeypatch.setattr(pipeline, "cluster", lambda *args, **kwargs: [{
        "topic": "Cell division", "question_ids": [1, 2], "explanation": "Possible confusion",
        "material_update": "Add a comparison.", "reteaching_activity": "Use a card sort.",
    }])
    result = pipeline.run(1, 1, offline=True)
    assert result["insights_found"] == 0
    assert result["insights_suppressed"] == 1
    cards = client.get("/agents/misconceptions/insights", params={"class_id": 1}).json()["insights"]
    assert not any(card["topic"] == "Cell division" for card in cards)


def test_live_pipeline_redacts_before_model_and_traces_counts_only(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(pipeline, 'load_chats', lambda *args: [
        {"chat_message_id": 999, "student_id": 1, "assignment_id": 1,
         "content": "Alice Johnson alice@school.edu (801) 555-1212: Is mitosis meiosis?"},
        {"chat_message_id": 1000, "student_id": 2, "assignment_id": 1,
         "content": "Is meiosis the same as mitosis?"},
        {"chat_message_id": 1001, "student_id": 1, "assignment_id": 1,
         "content": "Does mitosis work like meiosis?"},
    ])
    def fake_cluster(questions, **kwargs):
        captured['questions'] = questions
        assert langsmith.get_tracing_context()['enabled'] is False
        return [{"topic": "Mitosis versus meiosis", "question_ids": [1, 2, 3], "explanation": "Review cell division."}]
    monkeypatch.setattr(pipeline, 'cluster', fake_cluster)
    monkeypatch.setattr(pipeline, 'record_metrics', lambda metrics: captured.update(metrics=metrics))
    first = pipeline.run(1, 1)
    pipeline.run(1, 1)
    question = captured['questions'][0]
    assert set(question) == {'id', 'text'} and question['id'] == 1
    assert 'Alice' not in question['text'] and '@' not in question['text'] and '555' not in question['text']
    assert 'text' not in str(captured['metrics']) and 'Alice' not in str(captured['metrics'])
    cards = client.get('/agents/misconceptions/insights?class_id=1').json()['insights']
    matching = [c for c in cards if c['topic'] == 'Mitosis versus meiosis' and c['model_used'] == 'ollama:phi3']
    assert len(matching) == 1 and matching[0]['evidence_count'] == 3
    assert matching[0]['suggestion']['supporting_student_count'] == 2
    assert first['insights_found'] == 1


def test_cluster_rejects_fabricated_references(monkeypatch):
    class Model:
        def invoke(self, messages):
            assert langsmith.get_tracing_context()['enabled'] is False
            return SimpleNamespace(content=json.dumps({"clusters": [{"topic": "Cells", "question_ids": [999]}]}))
    monkeypatch.setattr(pipeline, 'get_model', lambda *args, **kwargs: Model())
    with pytest.raises(ValueError, match='unknown question ids'):
        pipeline.cluster([{"id": 1, "text": "What is mitosis?"}])
    assert pipeline.cluster([]) == []


def test_offline_groups_planted_confusion():
    questions = [{"id": 1, "text": "Mitosis makes sperm?"}, {"id": 2, "text": "Meiosis produces identical cells?"},
                 {"id": 3, "text": "Plants do not use respiration?"}]
    groups = pipeline.cluster(questions, offline=True)
    assert groups[0]['question_ids'] == [1, 2]
    assert groups[1]['question_ids'] == [3]


def test_approved_insight_handoff_sends_only_recommendations_and_waits_for_second_approval(client, monkeypatch):
    from importlib import import_module

    from app.agents.materials import agent as materials_agent
    misconceptions_router = import_module("app.agents.misconceptions.router")

    class StubMaterialsRunner:
        calls = []

        def run(self, state, *, class_id):
            self.calls.append((state, class_id))
            return {"status": "waiting_for_approval", "thread_id": "stub-thread", "approval_groups": ["stub"]}

    class_id = 2
    with connect() as conn:
        before_ids = {r["insight_id"] for r in conn.execute(
            "SELECT insight_id FROM misconception_insights WHERE class_id = ?", (class_id,))}
        library_count_before = conn.execute(
            "SELECT COUNT(*) FROM library_files WHERE class_id = ?", (class_id,)).fetchone()[0]

    created_ids = set()
    try:
        pipeline.run(class_id, 4, offline=True)
        with connect() as conn:
            created_ids = {r["insight_id"] for r in conn.execute(
                "SELECT insight_id FROM misconception_insights WHERE class_id = ?", (class_id,))} - before_ids
        cards = client.get("/agents/misconceptions/insights", params={"class_id": class_id}).json()["insights"]
        insight = next(card for card in cards if card["insight_id"] in created_ids)
        assert insight["suggestion"]["material_update"]
        assert insight["suggestion"]["reteaching_activity"]
        assert insight["examples"]

        stub = StubMaterialsRunner()
        monkeypatch.setattr(misconceptions_router, "require_models", lambda *args: None)
        monkeypatch.setattr(materials_agent, "runner", stub)
        response = client.post(
            f"/agents/misconceptions/insights/{insight['insight_id']}/draft",
            params={"class_id": class_id},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "waiting_for_approval"
        sent_text = str(stub.calls[0][0])
        assert insight["topic"] in sent_text
        assert insight["suggestion"]["material_update"] in sent_text
        assert insight["suggestion"]["reteaching_activity"] in sent_text
        assert all(example not in sent_text for example in insight["examples"])
        assert stub.calls[0][1] == class_id

        with connect() as conn:
            status = conn.execute("SELECT status FROM misconception_insights WHERE insight_id = ?",
                                  (insight["insight_id"],)).fetchone()["status"]
            library_count_after = conn.execute(
                "SELECT COUNT(*) FROM library_files WHERE class_id = ?", (class_id,)).fetchone()[0]
        assert status == "sent_to_materials"
        assert library_count_after == library_count_before
        repeated = client.post(
            f"/agents/misconceptions/insights/{insight['insight_id']}/draft",
            params={"class_id": class_id},
        )
        assert repeated.status_code == 409
        assert len(stub.calls) == 1
    finally:
        if created_ids:
            marks = ",".join("?" for _ in created_ids)
            with connect() as conn:
                conn.execute(f"DELETE FROM misconception_insights WHERE insight_id IN ({marks})", sorted(created_ids))
