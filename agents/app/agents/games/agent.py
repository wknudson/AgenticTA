"""Study-games agent: generator + independent reviewer, as a hand-built LangGraph StateGraph.

    retrieve -> generate -> review --(items rejected, attempts left)--> generate
                                   +--(all pass or out of attempts)--> save_draft -> request_publish -> END

Why a graph instead of create_agent: the control flow is fixed and auditable (Module 7
"graph engineering"), and the reviewer is a separate node on a DIFFERENT provider than the
generator, so it doesn't grade its own homework.  Owner: Teammate D.

TODO(Teammate D):
  - generate(): get_model("games", "generator").with_structured_output(GameItems)
  - review():   get_model("games", "reviewer").with_structured_output(ReviewVerdicts),
                checking each item against its source chunk + grade level
  - evaluation: error rate with vs without the reviewer (LangSmith dataset + evaluator)
"""
from __future__ import annotations

import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from langsmith import traceable

from app.shared import library
from app.shared.db import connect
from app.shared.hitl import HitlRunner, checkpointer, hitl_request

MAX_ATTEMPTS = 3


class GamesState(TypedDict, total=False):
    class_id: int
    topic: str
    kind: str
    offline: bool
    sources: list[dict[str, Any]]
    items: list[dict[str, Any]]
    review: list[dict[str, Any]]
    attempts: int
    activity_id: int
    published: bool


@traceable(name="games.retrieve")
def retrieve(state: GamesState) -> GamesState:
    chunks = library.search(state["topic"], state["class_id"], k=6)
    return {"sources": [c.to_dict() for c in chunks], "attempts": 0}


@traceable(name="games.generate")
def generate(state: GamesState) -> GamesState:
    if state.get("offline"):
        items = [
            {"front": "What makes ATP?", "back": "The mitochondria"},
            {"front": "Where is DNA stored?", "back": "The nucleus"},
            {"front": "What builds proteins?", "back": "Ribosomes"},
        ]
    else:
        raise NotImplementedError("TODO(Teammate D): generator model call (see module docstring)")
    return {"items": items, "attempts": state.get("attempts", 0) + 1}


@traceable(name="games.review")
def review(state: GamesState) -> GamesState:
    if state.get("offline"):
        source_text = " ".join(s["text"].lower() for s in state.get("sources", []))
        verdicts = [{"item": i, "ok": it["back"].lower().split()[-1] in source_text}
                    for i, it in enumerate(state["items"])]
    else:
        raise NotImplementedError("TODO(Teammate D): reviewer model call (see module docstring)")
    return {"review": verdicts}


def after_review(state: GamesState) -> str:
    all_ok = all(v["ok"] for v in state["review"])
    return "save_draft" if all_ok or state["attempts"] >= MAX_ATTEMPTS else "generate"


def save_draft(state: GamesState) -> GamesState:
    """Separate node on purpose: a node that calls interrupt() is re-run from the top on
    resume, so side effects must happen in the node BEFORE it."""
    with connect() as conn:
        activity_id = conn.execute(
            "INSERT INTO study_activities (class_id, unit, kind, title, items_json, review_json, attempts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (state["class_id"], state["topic"], state.get("kind", "flashcards"), f"{state['topic']} practice",
             json.dumps(state["items"]), json.dumps(state["review"]), state["attempts"]),
        ).lastrowid
    return {"activity_id": activity_id}


def request_publish(state: GamesState) -> GamesState:
    """Pause for the teacher (Approvals inbox), then publish or reject."""
    activity_id = state["activity_id"]
    decisions = interrupt(hitl_request([{
        "name": "publish_activity",
        "args": {"activity_id": activity_id, "title": f"{state['topic']} practice", "items": state["items"]},
        "description": f"Publish {len(state['items'])} {state.get('kind', 'flashcards')} to students?",
        "allowed_decisions": ["approve", "edit", "reject"],
    }]))["decisions"]
    d = decisions[0]
    items = d["edited_action"]["args"].get("items", state["items"]) if d["type"] == "edit" else state["items"]
    status = "rejected" if d["type"] == "reject" else "published"
    with connect() as conn:
        conn.execute("UPDATE study_activities SET status = ?, items_json = ? WHERE activity_id = ?",
                     (status, json.dumps(items), activity_id))
    return {"activity_id": activity_id, "items": items, "published": status == "published"}


def build_agent(**_: Any):
    g = StateGraph(GamesState)
    g.add_node("retrieve", retrieve)
    g.add_node("generate", generate)
    g.add_node("review", review)
    g.add_node("save_draft", save_draft)
    g.add_node("request_publish", request_publish)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", "review")
    g.add_conditional_edges("review", after_review, ["generate", "save_draft"])
    g.add_edge("save_draft", "request_publish")
    g.add_edge("request_publish", END)
    return g.compile(checkpointer=checkpointer(), name="games")


runner = HitlRunner("games", build_agent)
