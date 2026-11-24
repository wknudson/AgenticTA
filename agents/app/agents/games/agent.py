"""Study-games agent: generator + independent reviewer, as a hand-built LangGraph StateGraph.

Two flows share one graph (one HitlRunner, so the Approvals inbox can resume either):

  unit package (the flipped-classroom check-in, POST /unit-package):
    unit_sources -> draft_package -> review_package --(items rejected, attempts left)--> draft_package
                                                    +--(enough passed / out of attempts)--> save_package
    save_package -> request_package_publish (interrupt: publish_unit_package) -> END

  single activity (POST /run, /demo):
    retrieve -> generate -> review --(items rejected, attempts left)--> generate
                                   +--(all pass or out of attempts)--> save_draft -> request_publish -> END

Why a graph instead of create_agent: the control flow is fixed and auditable (Module 7
"graph engineering"), and the reviewer is a separate node on a DIFFERENT provider than the
generator, so it doesn't grade its own homework. Without keys (or with offline=true) the
package is built by the deterministic no-AI generator (extract.py) and checked by the same
deterministic checks; there is nothing to regenerate, so it goes straight to save.

Side effects live in the node BEFORE each interrupt (save_draft / save_package): a node that
calls interrupt() re-runs from the top when it resumes.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from langsmith import traceable

from app.shared import library
from app.shared.db import connect
from app.shared.hitl import HitlRunner, checkpointer, hitl_request

from . import models as ai
from . import package as pkg
from .extract import NotEnoughMaterial, Source, build_package, norm_term

MAX_ATTEMPTS = 3


class GamesState(TypedDict, total=False):
    class_id: int
    offline: bool
    sources: list[dict[str, Any]]
    review: Any
    attempts: int
    messages: list[Any]
    # single activity
    topic: str
    kind: str
    items: list[dict[str, Any]]
    activity_id: int
    published: bool
    # unit package
    unit: str
    settings: dict[str, Any]
    use_models: bool
    draft: dict[str, Any]
    rejected: list[dict[str, Any]]
    notes: list[str]
    generated_by: str
    package_id: int
    activity_ids: list[int]
    assignment_id: int
    calendar_note: str


def route_start(state: GamesState) -> str:
    return "unit_sources" if state.get("unit") else "retrieve"


# ================================================================ unit package
def _sources(state: GamesState) -> list[Source]:
    return [Source(**s) for s in state.get("sources", [])]


@traceable(name="games.unit_sources")
def unit_sources(state: GamesState) -> GamesState:
    sources, _ = pkg.unit_sources(state["class_id"], state["unit"])
    use_models = not state.get("offline") and ai.models_ready()
    return {"sources": [asdict(s) for s in sources], "attempts": 0, "use_models": use_models, "notes": [],
            "draft": {"flashcards": [], "fill_in": [], "questions": []}, "rejected": [], "review": []}


def _offline_draft(state: GamesState) -> dict[str, Any]:
    s = state["settings"]
    return build_package(_sources(state), card_count=s["card_count"], mc_count=s["mc_count"],
                         explain_count=s["explain_count"])


def _missing(state: GamesState) -> dict[str, int]:
    want, have = pkg.wanted(state["settings"]), pkg.counts(state.get("draft") or {})
    return {k: max(0, want[k] - have[k]) for k in want}


def _merge(kept: dict[str, Any], new: dict[str, Any], want: dict[str, int]) -> dict[str, Any]:
    terms = {norm_term(c["front"]) for c in kept["flashcards"]}
    cards = list(kept["flashcards"])
    for c in new.get("flashcards", []):
        if norm_term(c["front"]) not in terms and len(cards) < want["flashcards"]:
            cards.append(c)
            terms.add(norm_term(c["front"]))
    fill = (kept["fill_in"] + new.get("fill_in", []))[: want["fill_in"]]
    old_q, new_q = kept["questions"], new.get("questions", [])
    choice = ([q for q in old_q if q["kind"] == "choice"] + [q for q in new_q if q["kind"] == "choice"])[: want["choice"]]
    explain = ([q for q in old_q if q["kind"] == "explain"]
               + [q for q in new_q if q["kind"] == "explain"])[: want["explain"]]
    return {"flashcards": cards, "fill_in": fill, "questions": choice + explain}


@traceable(name="games.draft_package")
def draft_package(state: GamesState) -> GamesState:
    attempts = state.get("attempts", 0) + 1
    if not state.get("use_models"):
        return {"draft": _offline_draft(state), "attempts": attempts, "generated_by": "offline"}
    kept = state.get("draft") or {"flashcards": [], "fill_in": [], "questions": []}
    try:
        new = ai.generate_package(_sources(state), state["unit"], _missing(state),
                                  avoid=[c["front"] for c in kept["flashcards"]], rejected=state.get("rejected"))
    except NotEnoughMaterial:
        raise
    except Exception as exc:  # model outage, quota, bad output: fall back instead of failing the teacher
        notes = list(state.get("notes", []))
        if not any(kept.values()):
            notes.append(f"AI generation failed ({type(exc).__name__}); used the no-AI generator instead.")
            return {"draft": _offline_draft(state), "attempts": attempts, "generated_by": "offline",
                    "use_models": False, "notes": notes}
        notes.append(f"AI regeneration failed ({type(exc).__name__}); kept the items that passed review.")
        return {"attempts": MAX_ATTEMPTS, "notes": notes}
    return {"draft": _merge(kept, new, pkg.wanted(state["settings"])), "attempts": attempts,
            "generated_by": ai.generator_name()}


@traceable(name="games.review_package")
def review_package(state: GamesState) -> GamesState:
    """Deterministic checks always; the independent reviewer model too when models are on."""
    draft = state["draft"]
    verdicts = pkg.check_draft(draft, pkg.material_text(_sources(state)))
    notes = list(state.get("notes", []))
    if state.get("use_models"):
        try:
            verdicts += ai.review_package(_sources(state), draft)
        except Exception as exc:
            notes.append(f"AI review failed ({type(exc).__name__}); only the built-in checks ran.")
    merged = pkg.combine(verdicts)
    accepted, rejected = pkg.split_by_verdicts(draft, merged)
    log = list(state.get("review") or []) + [{"attempt": state.get("attempts", 1), **v} for v in merged.values()]
    return {"draft": accepted, "rejected": rejected, "review": log, "notes": notes}


def after_package_review(state: GamesState) -> str:
    if state.get("use_models") and any(_missing(state).values()) and state.get("attempts", 0) < MAX_ATTEMPTS:
        return "draft_package"
    return "save_package"


def save_package(state: GamesState) -> GamesState:
    review = {"generated_by": state.get("generated_by"), "attempts": state.get("attempts", 1),
              "verdicts": state.get("review") or [], "notes": state.get("notes", []),
              "dropped": [{"kind": r["kind"], "problem": r["problem"]} for r in state.get("rejected", [])]}
    package_id, activity_ids = pkg.save_draft_package(
        state["class_id"], state["unit"], state["settings"], state["draft"], review,
        state.get("generated_by") or "offline", state.get("attempts", 1))
    return {"package_id": package_id, "activity_ids": activity_ids, "sources": []}  # text isn't needed any more


def request_package_publish(state: GamesState) -> GamesState:
    """One approval for the whole package; publishing happens after the teacher decides."""
    package_id = state["package_id"]
    # Read from the DB every time: this node re-runs on resume, so publishing (and the message
    # below) use whatever the teacher edited while the approval was pending (editing.py).
    p = pkg.get_package(package_id)
    s, n = p["settings"], pkg.summary(p)
    description = pkg.approval_description(p)
    decisions = interrupt(hitl_request([{
        "name": "publish_unit_package",
        "args": {"class_id": state["class_id"], "package_id": package_id},
        "description": description,
        "allowed_decisions": ["approve", "reject"],
    }]))["decisions"]
    if decisions[0]["type"] == "reject":
        pkg.reject(package_id)
        return {"published": False, "messages": [AIMessage(f"Unit package {package_id} was rejected; nothing was "
                                                           "published.")]}
    out = pkg.publish(package_id)
    text = (f"Published \"{s['title']}\" as check-in assignment {out['assignment_id']} with {n['mc'] + n['explain']} "
            f"questions and {len(p['activities'])} games. {out['calendar_note']}")
    return {"published": True, "assignment_id": out["assignment_id"], "calendar_note": out["calendar_note"],
            "messages": [AIMessage(text)]}


# ================================================================ single activity (/run, /demo)
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
        items = ai.generate_activity(state.get("sources", []), state["topic"], state.get("kind", "flashcards"))
    return {"items": items, "attempts": state.get("attempts", 0) + 1}


@traceable(name="games.review")
def review(state: GamesState) -> GamesState:
    if state.get("offline"):
        source_text = " ".join(s["text"].lower() for s in state.get("sources", []))
        verdicts = [{"item": i, "ok": it["back"].lower().split()[-1] in source_text}
                    for i, it in enumerate(state["items"])]
    else:
        verdicts = ai.review_activity(state.get("sources", []), state["items"], state.get("kind", "flashcards"))
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
    # unit package
    g.add_node("unit_sources", unit_sources)
    g.add_node("draft_package", draft_package)
    g.add_node("review_package", review_package)
    g.add_node("save_package", save_package)
    g.add_node("request_package_publish", request_package_publish)
    # single activity
    g.add_node("retrieve", retrieve)
    g.add_node("generate", generate)
    g.add_node("review", review)
    g.add_node("save_draft", save_draft)
    g.add_node("request_publish", request_publish)

    g.add_conditional_edges(START, route_start, ["unit_sources", "retrieve"])
    g.add_edge("unit_sources", "draft_package")
    g.add_edge("draft_package", "review_package")
    g.add_conditional_edges("review_package", after_package_review, ["draft_package", "save_package"])
    g.add_edge("save_package", "request_package_publish")
    g.add_edge("request_package_publish", END)

    g.add_edge("retrieve", "generate")
    g.add_edge("generate", "review")
    g.add_conditional_edges("review", after_review, ["generate", "save_draft"])
    g.add_edge("save_draft", "request_publish")
    g.add_edge("request_publish", END)
    return g.compile(checkpointer=checkpointer(), name="games")


runner = HitlRunner("games", build_agent)
