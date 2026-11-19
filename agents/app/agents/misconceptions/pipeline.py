"""Misconception finder: a workflow over student tutor chats.  Owner: Teammate B.

    load chats -> redact (deterministic) -> cluster (LOCAL model) -> summarize -> suggest

Privacy design: the redaction step runs BEFORE any model sees the text, and the default
model is a local Ollama model, so student chats never leave the machine.  The
'baseline' API model exists only to measure what that privacy costs in quality/latency.

TODO(Teammate B):
  - cluster(): get_model("misconceptions", "local") -> group questions by underlying confusion
    (structured output: [{topic, question_ids}]); run the same input through "baseline"
    and compare in LangSmith (quality + latency table for the write-up)
  - suggest(): one teacher-facing suggestion per cluster; the panel's buttons hand it to
    the games or materials agent (nothing runs without the teacher's click)
  - seed some realistic chats with planted misconceptions for the evaluation
"""
from __future__ import annotations

import re
from typing import Any

from langsmith import traceable

from app.shared.db import connect
from app.shared.guardrails import EMAIL_RE, PHONE_RE
from app.shared.tracing import agent_trace


@traceable(name="misconceptions.load_chats")
def load_chats(class_id: int, assignment_id: int | None = None) -> list[dict[str, Any]]:
    sql = """SELECT m.chat_message_id, m.student_id, m.assignment_id, m.content
             FROM student_chat_messages m JOIN assignments a ON a.assignment_id = m.assignment_id
             WHERE a.class_id = ? AND m.role = 'user'"""
    params: list[Any] = [class_id]
    if assignment_id:
        sql += " AND m.assignment_id = ?"
        params.append(assignment_id)
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _student_names(class_id: int) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT s.first_name, s.last_name FROM students s
               JOIN student_classes sc ON sc.student_id = s.student_id WHERE sc.class_id = ?""",
            (class_id,),
        ).fetchall()
    return [n for r in rows for n in (r["first_name"], r["last_name"]) if n and len(n) > 1]


@traceable(name="misconceptions.redact")
def redact(class_id: int, chats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic guardrail: emails, phone numbers and enrolled students' names are masked
    and student ids are dropped before anything reaches a model."""
    names = _student_names(class_id)
    name_re = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b", re.IGNORECASE) if names else None
    out = []
    for c in chats:
        text = EMAIL_RE.sub("[email]", c["content"])
        text = PHONE_RE.sub("[phone]", text)
        if name_re:
            text = name_re.sub("[student]", text)
        out.append({"id": c["chat_message_id"], "assignment_id": c["assignment_id"], "text": text})
    return out


@traceable(name="misconceptions.cluster")
def cluster(questions: list[dict[str, Any]], *, offline: bool = False) -> list[dict[str, Any]]:
    if offline or not questions:
        return [{"topic": "(offline demo) not clustered yet", "question_ids": [q["id"] for q in questions[:5]]}]
    raise NotImplementedError("TODO(Teammate B): local-model clustering (see module docstring)")


def run(class_id: int, assignment_id: int | None = None, *, offline: bool = False) -> dict[str, Any]:
    with agent_trace("misconceptions", class_id=class_id):
        chats = load_chats(class_id, assignment_id)
        redacted = redact(class_id, chats)
        clusters = cluster(redacted, offline=offline)
    return {"chats_read": len(chats), "clusters": clusters,
            "sample_redacted": [q["text"] for q in redacted[:3]]}
