"""The model path: a generator and an independent reviewer on a different provider, both with
structured output (Pydantic), so nothing is parsed out of free text.

    get_model("games", "generator").with_structured_output(PackageOut)
    get_model("games", "reviewer").with_structured_output(ReviewOut)

Used only when both roles have keys (models_ready) and the teacher didn't ask for offline;
otherwise the graph uses the no-AI generator in extract.py. Tests replace these functions.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from langsmith import traceable

from app.shared.agent_router import require_models
from app.shared.llm import MissingApiKey, get_model, model_spec

from .extract import Source, alternates

MAX_MATERIAL_CHARS = 24_000


def models_ready() -> bool:
    try:
        require_models("games", "generator", "reviewer")
        return True
    except MissingApiKey:
        return False


def generator_name() -> str:
    return model_spec("games", "generator")["model"]


# ---------------------------------------------------------------- structured outputs
class CardOut(BaseModel):
    term: str = Field(description="a key term of the unit, 1-4 words, written as the material writes it")
    definition: str = Field(description="what it is or does, one short sentence, using only the material")
    source_quote: str = Field(description="the sentence in the material this card comes from, copied exactly")


class FillInOut(BaseModel):
    sentence: str = Field(description="a sentence from the material with the key term replaced by ____")
    answer: str = Field(description="the term that goes in the blank")
    alternates: list[str] = Field(default_factory=list, description="other accepted answers (singular/plural)")


class ChoiceOut(BaseModel):
    question: str = Field(description="the question; it must not contain the answer")
    correct: str = Field(description="the one right answer, a few words")
    distractors: list[str] = Field(description="2 or 3 plausible wrong answers, ideally other terms of this unit")
    source_quote: str = Field(description="the sentence in the material that answers it, copied exactly")


class ExplainOut(BaseModel):
    question: str = Field(description='an "Explain why ..." or "Explain how ..." question about the material')
    model_answer: str = Field(description="a good answer a student could write in 1-3 sentences")
    rubric: str = Field(description="the key idea a good explanation must contain, one sentence from the material")


class PackageOut(BaseModel):
    cards: list[CardOut] = Field(default_factory=list)
    fill_in: list[FillInOut] = Field(default_factory=list)
    choice: list[ChoiceOut] = Field(default_factory=list)
    explain: list[ExplainOut] = Field(default_factory=list)


class Verdict(BaseModel):
    ref: str = Field(description="the item's ref exactly as given, e.g. 'flashcards 3'")
    ok: bool = Field(description="true if the item is accurate, clear and answerable from the material")
    problem: str = Field(default="", description="what is wrong, empty when ok")


class ReviewOut(BaseModel):
    verdicts: list[Verdict]


GENERATOR_PROMPT = """You write study games and a short check-in for a high-school class, from the teacher's own unit material.
Rules:
- Use only facts stated in the material. Never add outside facts.
- Write for students: short, clear, no trick wording.
- Don't copy quiz or test questions; teach the ideas behind them.
- Flashcard terms are distinct key terms of the unit.
- Each fill-in sentence has exactly one blank, written ____, and the blanked word is the answer.
- Multiple choice has exactly one defensible right answer; wrong answers are other real terms or ideas from this unit.
- Explain questions ask why or how, and can be answered in 1-3 sentences from the material."""

REVIEWER_PROMPT = """You are an independent reviewer. A different model wrote these study items for students; check each one against the unit material before the teacher sees it.
An item is ok only if it is accurate according to the material, unambiguous, answerable from the material, and right for high-school students. A multiple-choice item also needs exactly one defensible right option. An explain item's rubric must be the key idea from the material.
Return one verdict per ref, with a short problem when it is not ok."""


def _material(sources: list[Source]) -> str:
    parts, used = [], 0
    for s in sources:
        block = f"### {s.title} ({s.doc_type or 'document'})\n{s.text.strip()}\n"
        if used + len(block) > MAX_MATERIAL_CHARS:
            block = block[: max(0, MAX_MATERIAL_CHARS - used)]
        parts.append(block)
        used += len(block)
        if used >= MAX_MATERIAL_CHARS:
            break
    return "\n".join(parts)


@traceable(name="games.model_generate")
def generate_package(sources: list[Source], unit: str, need: dict[str, int], *, avoid: list[str] | None = None,
                     rejected: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Ask the generator for `need` items of each kind. Returns a draft (see package.py)."""
    model = get_model("games", "generator").with_structured_output(PackageOut)
    ask = (f"Unit: {unit}\n\nMaterial:\n{_material(sources)}\n\n"
           f"Write {need.get('flashcards', 0)} flashcards, {need.get('fill_in', 0)} fill-in sentences, "
           f"{need.get('choice', 0)} multiple-choice questions (3 or 4 options) and {need.get('explain', 0)} "
           "explain questions.")
    if avoid:
        ask += "\nDon't repeat these flashcard terms (they're already in the package): " + "; ".join(avoid)
    if rejected:
        ask += "\nThe reviewer rejected these items; write different ones and avoid the same problems:\n" + "\n".join(
            f"- {r['kind']}: {r['item'].get('front') or r['item'].get('sentence') or r['item'].get('text')} "
            f"-> {r['problem']}" for r in rejected[:20])
    out: PackageOut = model.invoke([("system", GENERATOR_PROMPT), ("user", ask)])
    material = "\n".join(s.text for s in sources)
    questions: list[dict[str, Any]] = []
    for c in out.choice[: need.get("choice", 0)]:
        options = [{"text": c.correct.strip(), "correct": True}]
        options += [{"text": d.strip(), "correct": False} for d in c.distractors[:3] if d.strip()]
        at = sum(map(ord, c.question)) % len(options)        # don't always put the right one first
        options.insert(at, options.pop(0))
        questions.append({"text": c.question.strip(), "kind": "choice", "options": options,
                          "source": c.source_quote.strip()})
    for e in out.explain[: need.get("explain", 0)]:
        questions.append({"text": e.question.strip(), "kind": "explain", "answer": e.model_answer.strip(),
                          "rubric": e.rubric.strip(), "source": e.rubric.strip()})
    return {
        "flashcards": [{"front": c.term.strip(), "back": c.definition.strip(), "source": c.source_quote.strip()}
                       for c in out.cards[: need.get("flashcards", 0)]],
        "fill_in": [{"sentence": f.sentence.strip(), "answer": f.answer.strip(),
                     "alternates": sorted({a.strip().lower() for a in f.alternates if a.strip()}
                                          | set(alternates(f.answer, material))),
                     "source": ""} for f in out.fill_in[: need.get("fill_in", 0)]],
        "questions": questions,
    }


def _describe(ref: str, item: dict[str, Any]) -> str:
    if "front" in item:
        return f"[{ref}] flashcard: {item['front']} -> {item['back']}"
    if "sentence" in item:
        return f"[{ref}] fill in: {item['sentence']} (answer: {item['answer']})"
    if item.get("kind") == "choice":
        opts = ", ".join(f"{o['text']}{' (right)' if o['correct'] else ''}" for o in item["options"])
        return f"[{ref}] multiple choice: {item['text']} Options: {opts}"
    return f"[{ref}] explain: {item['text']} Model answer: {item.get('answer')} Rubric: {item.get('rubric')}"


@traceable(name="games.model_review")
def review_package(sources: list[Source], draft: dict[str, Any]) -> list[dict[str, Any]]:
    """The independent reviewer: one verdict per item ref ({ref, ok, note, by})."""
    lines = [_describe(f"{kind} {i}", item) for kind in ("flashcards", "fill_in", "questions")
             for i, item in enumerate(draft.get(kind, []), 1)]
    if not lines:
        return []
    model = get_model("games", "reviewer").with_structured_output(ReviewOut)
    out: ReviewOut = model.invoke([("system", REVIEWER_PROMPT),
                                   ("user", f"Material:\n{_material(sources)}\n\nItems:\n" + "\n".join(lines))])
    return [{"ref": v.ref.strip(), "ok": v.ok, "note": v.problem.strip(), "by": "reviewer"} for v in out.verdicts]


# ---------------------------------------------------------------- the single-activity flow (/run)
@traceable(name="games.model_generate_activity")
def generate_activity(sources: list[dict[str, Any]], topic: str, kind: str, count: int = 8) -> list[dict[str, Any]]:
    """Legacy /run: one activity for a topic from library.search hits."""
    srcs = [Source(s.get("file_id", 0), s.get("file_title", ""), s.get("doc_type"), s.get("text", "")) for s in sources]
    need = {"flashcards": count} if kind != "fill_in" else {"fill_in": count}
    draft = generate_package(srcs, topic, need)
    if kind == "fill_in":
        return [{k: f[k] for k in ("sentence", "answer", "alternates")} for f in draft["fill_in"]]
    if kind == "matching":
        return [{"term": c["front"], "definition": c["back"]} for c in draft["flashcards"]]
    return [{"front": c["front"], "back": c["back"]} for c in draft["flashcards"]]


@traceable(name="games.model_review_activity")
def review_activity(sources: list[dict[str, Any]], items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    srcs = [Source(s.get("file_id", 0), s.get("file_title", ""), s.get("doc_type"), s.get("text", "")) for s in sources]
    if kind == "fill_in":
        draft = {"fill_in": items}
        key = "fill_in"
    else:
        draft = {"flashcards": [{"front": it.get("front") or it.get("term", ""),
                                 "back": it.get("back") or it.get("definition", "")} for it in items]}
        key = "flashcards"
    verdicts = {v["ref"]: v for v in review_package(srcs, draft)}
    return [{"item": i, "ok": verdicts.get(f"{key} {i + 1}", {"ok": True})["ok"],
             "note": verdicts.get(f"{key} {i + 1}", {}).get("note", "")} for i in range(len(items))]
