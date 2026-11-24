"""The check-in tutor: one conversation per question.

Model path: create_agent (LangChain v1) with two read-only tools, search_unit and get_attempts.
    Middleware, outermost first:
      BlockedActionsMiddleware   shared hard blocks (grades, deletes, outbound messages)
      PIIMiddleware x2           emails and phone numbers are redacted before the model sees them
      ModelCallLimitMiddleware   at most MAX_MODEL_CALLS model calls per student message
      AnswerGuardMiddleware      a reply that gives the answer away is swapped for a hint
    Tutor mode is enforced in code: the answer is only put in the prompt when may_reveal() is
    true (answer_after_tries mode, after N honest tries).

No-AI path (no key, AGENTICTA_TUTOR_OFFLINE=1, or the model call failed): a deterministic
Socratic nudge plus the most relevant line from the unit's notes, with the answer blanked out.
Same guard, same reveal rule.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import tool

from app.shared import library
from app.shared.guardrails import PHONE_RE, BlockedActionsMiddleware, assert_safe_toolset

from .guard import content_stems, guard_reply, mask_answer
from .models import offline_mode, tutor_model
from .questions import Question

log = logging.getLogger(__name__)

MAX_MODEL_CALLS = 4      # per student message (tool call + answer, with room for one more search)
HISTORY_TURNS = 12       # earlier messages on this question sent to the model
SNIPPET_CHARS = 320
EXPLAIN_BACK = "Now explain it back to me in your own words: why is that the answer?"


@dataclass
class TutorContext:
    """Everything one tutor turn needs, loaded before any model call (no DB lock held)."""
    assignment: dict[str, Any]
    question: Question
    status: dict[str, Any]
    reveal: bool                       # may_reveal(): answer_after_tries mode after N honest tries
    message: str
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def key(self):
        return self.question.key


@dataclass
class TutorReply:
    text: str
    help_level: str          # "hint" | "explained"
    source: str              # "model" | "offline" | "offline_fallback"
    blocked: bool = False    # the guard replaced an answer-revealing reply


# ---------------------------------------------------------------- library
def search_unit(ctx: TutorContext, query: str, k: int = 4) -> list[library.Chunk]:
    """Library search over the class, filtered to the check-in's unit."""
    a = ctx.assignment
    for mode in ("hybrid", "keyword"):  # an embedding outage falls back to keyword search
        try:
            return library.search(query, a["class_id"], k=k, unit=a.get("unit") or None, mode=mode)
        except Exception:
            log.warning("tutor: library search (%s) failed", mode, exc_info=True)
    return []


def _best_lines(text: str, query_stems: set[str], limit: int = SNIPPET_CHARS) -> tuple[str, int]:
    """The sentence (plus the next, if it fits) that shares the most meaningful words with the query."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]
    if not sentences:
        return "", 0
    scored = [(len(content_stems(s) & query_stems), i) for i, s in enumerate(sentences)]
    score, i = max(scored, key=lambda t: (t[0], -t[1]))
    out = sentences[i]
    if i + 1 < len(sentences) and len(out) + len(sentences[i + 1]) < limit:
        out += " " + sentences[i + 1]
    if len(out) > limit:
        out = out[: limit - 3].rsplit(" ", 1)[0] + "..."
    return out, score


def note_snippet(ctx: TutorContext, chunks: list[library.Chunk], *, mask: bool) -> tuple[str, str, bool] | None:
    """(file title, snippet, masked?) from the notes, safe to show. None if nothing relevant passes the guard."""
    query = content_stems(f"{ctx.question.text} {ctx.message}")
    best = sorted(((*_best_lines(c.text, query), c) for c in chunks), key=lambda t: -t[1])
    for snippet, score, chunk in best:
        if not snippet or score == 0:
            continue
        masked = False
        if mask:
            snippet, masked = mask_answer(snippet, ctx.key)
            if guard_reply(snippet, ctx.key, allow_reveal=False)[1]:
                continue  # the notes spell out the answer even with it blanked: don't use this one
        return chunk.file_title, snippet, masked
    return None


def _snippets_for_model(chunks: list[library.Chunk], query: str) -> str:
    stems = content_stems(query)
    lines = [f"[{c.file_title}] {_best_lines(c.text, stems, 500)[0]}" for c in chunks]
    return "\n".join(line for line in lines if line.strip()) or "No matches in this unit's notes."


# ---------------------------------------------------------------- no-AI tutor
ASKS_FOR_ANSWER = re.compile(r"\b(answer|tell me|just say|give me|which one|what is it|is it)\b", re.IGNORECASE)


def _nudge(q: Question) -> str:
    if q.kind == "choice":
        return "What does that tell you about the question? Which option fits best, and why?"
    text = q.text.strip().rstrip(".?!")
    if text.lower().startswith("explain"):
        return f"How does that help you {text[0].lower()}{text[1:]}?"
    return "How would you put that idea into one or two sentences of your own?"


def offline_reply(ctx: TutorContext) -> TutorReply:
    q, st = ctx.question, ctx.status
    chunks = search_unit(ctx, f"{q.text} {ctx.message}")
    if ctx.reveal:
        parts = [f"You've given this {st['tries']} honest tries, so let's walk through it.",
                 f"The answer: {ctx.key.answer_text()}."]
        if ctx.key.rubric and ctx.key.rubric.strip() != ctx.key.answer_text():
            parts.append(f"The key idea: {ctx.key.rubric.strip()}")
        found = note_snippet(ctx, chunks, mask=False)
        if found:
            parts.append(f"Your notes ({found[0]}) say: \"{found[1]}\"")
        parts.append(EXPLAIN_BACK + " Then use Fix it to send your explanation.")
        return TutorReply(" ".join(parts), "explained", "offline")

    parts = ["I can't give you the answer, but I can help you get there." if ASKS_FOR_ANSWER.search(ctx.message)
             else "Let's think it through."]
    if st["status"] == "needs_fix" and st.get("first_answer"):
        parts.append(f"You first answered \"{st['first_answer']}\". What made that seem right?")
    found = note_snippet(ctx, chunks, mask=True)
    if found:
        title, snippet, masked = found
        parts.append(f"Here's what your notes say ({title}): \"{snippet}\""
                     + (" (I blanked out the part that gives it away.)" if masked else ""))
    else:
        parts.append("I couldn't find this in your unit's notes, so let's reason it out.")
    parts.append(_nudge(q))
    text, blocked = guard_reply(" ".join(parts), ctx.key, allow_reveal=False)
    return TutorReply(text, "hint", "offline", blocked)


# ---------------------------------------------------------------- model tutor
class AnswerGuardMiddleware(AgentMiddleware):
    """Output guard (ported from ai.ts): a final reply that gives the answer away is replaced
    with a hint before it leaves the agent. Off only when may_reveal() is true."""

    def __init__(self, ctx: TutorContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.blocked = False

    def _guard(self, msg: BaseMessage) -> BaseMessage:
        if not isinstance(msg, AIMessage) or msg.tool_calls:
            return msg
        text, blocked = guard_reply(_text(msg), self.ctx.key, allow_reveal=self.ctx.reveal)
        if not blocked:
            return msg
        self.blocked = True
        return AIMessage(content=text, id=msg.id)

    def wrap_model_call(self, request, handler: Callable):  # type: ignore[override]
        response = handler(request)
        if isinstance(response, AIMessage):
            return self._guard(response)
        if hasattr(response, "result"):
            response.result = [self._guard(m) for m in response.result]
        return response


def _text(msg: BaseMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content or [])


def _pii_middleware() -> list[AgentMiddleware]:
    try:
        from langchain.agents.middleware import PIIMiddleware
    except ImportError:  # older LangChain: skip, the guardrails' contains_pii still exists
        return []
    return [PIIMiddleware("email", strategy="redact", apply_to_input=True),
            PIIMiddleware("phone_number", detector=PHONE_RE.pattern, strategy="redact", apply_to_input=True)]


def system_prompt(ctx: TutorContext) -> str:
    a, q, st = ctx.assignment, ctx.question, ctx.status
    lines = [
        "You are the AgenticTA tutor. You help ONE student with ONE check-in question, before class.",
        f"Unit: {a.get('unit') or 'this unit'}.",
        "",
        "How to help:",
        "- Be warm and brief: 2 to 5 sentences, plain language for a high-school student.",
        "- Be Socratic: ask one guiding question, give one hint, and point to the class notes.",
        "- Use search_unit to look things up in this unit's notes; name the file you used, e.g. (Cell Organelles Slides).",
        "- Use get_attempts to see what the student has tried so far.",
        "- Stay on this question and this unit. Politely steer anything else back.",
    ]
    if ctx.reveal:
        lines += [
            "",
            f"The student has made {st['tries']} honest tries, so the teacher allows you to walk through the answer now.",
            f"The answer: {ctx.key.answer_text()}",
            *([f"The key idea: {ctx.key.rubric}"] if ctx.key.rubric else []),
            "Explain briefly why it is the answer, using the notes. Then END your reply by asking the student to "
            "explain it back to you in their own words.",
        ]
    else:
        lines += [
            "",
            "Never state the correct answer, never say which option is right or wrong, and never write an "
            "explanation they could copy. If they ask for the answer, kindly say you can't and give a hint instead.",
        ]
    if (a.get("ai_params") or "").strip():
        lines += ["", f"The teacher's instructions (follow them): {a['ai_params'].strip()}"]
    lines += ["", f"The question: {q.text}"]
    if q.kind == "choice":
        lines.append("Options: " + "; ".join(o["option_text"] for o in q.options))
    else:
        lines.append("It's a short \"explain why\" question.")
    if st["status"] == "unanswered":
        lines.append("The student hasn't answered yet.")
    else:
        lines.append(f"The student's first answer (not right): {st.get('first_answer')!r}. Honest tries since: {st['tries']}.")
    return "\n".join(lines)


def build_agent(ctx: TutorContext, model=None):
    """create_agent for this one question. Tools are read-only closures over the context."""

    @tool("search_unit")
    def search_unit_notes(query: str) -> str:
        """Search this unit's class notes (lectures, readings, worksheets). Returns short snippets with the file title."""
        return _snippets_for_model(search_unit(ctx, query), query)

    @tool
    def get_attempts() -> str:
        """What the student has tried on this question: first answer, honest tries, last feedback."""
        st = ctx.status
        return json.dumps({"status": st["status"], "first_answer": st.get("first_answer"), "tries": st["tries"],
                           "last_explanation": st.get("explain_back"), "last_feedback": st.get("last_feedback"),
                           "help_so_far": st["help_level"]})

    tools = [search_unit_notes, get_attempts]
    assert_safe_toolset(tools)
    guard = AnswerGuardMiddleware(ctx)
    agent = create_agent(
        model=model or tutor_model(),
        tools=tools,
        system_prompt=system_prompt(ctx),
        middleware=[BlockedActionsMiddleware(), *_pii_middleware(),
                    ModelCallLimitMiddleware(run_limit=MAX_MODEL_CALLS, exit_behavior="error"), guard],
        name="tutor",
    )
    return agent, guard


def _messages(ctx: TutorContext) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for m in ctx.history[-HISTORY_TURNS:]:
        out.append(HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(m["content"]))
    out.append(HumanMessage(ctx.message))  # the new message, once (ai.ts sent it twice)
    return out


def model_reply(ctx: TutorContext, model=None) -> TutorReply:
    agent, guard = build_agent(ctx, model)
    result = agent.invoke({"messages": _messages(ctx)})
    final = next((m for m in reversed(result["messages"]) if isinstance(m, AIMessage) and not m.tool_calls), None)
    text = _text(final).strip() if final else ""
    if not text:
        raise RuntimeError("the tutor model returned no reply")
    text, blocked = guard_reply(text, ctx.key, allow_reveal=ctx.reveal)  # belt and braces
    if guard.blocked or blocked:
        hint = offline_reply(ctx)  # the no-AI hint is more useful than a bare refusal (and also guarded)
        return TutorReply(hint.text, "hint", "model", True)
    if ctx.reveal and "own words" not in text.lower():
        text = f"{text.rstrip()}\n\n{EXPLAIN_BACK}"
    return TutorReply(text, "explained" if ctx.reveal else "hint", "model")


def reply(ctx: TutorContext, *, offline: bool | None = None, model=None) -> TutorReply:
    """One tutor turn. Never raises for model problems: falls back to the no-AI tutor."""
    if offline is None:
        offline = offline_mode() and model is None
    if not offline:
        try:
            return model_reply(ctx, model)
        except Exception:
            log.warning("tutor: model call failed, using the no-AI tutor", exc_info=True)
            fallback = offline_reply(ctx)
            fallback.source = "offline_fallback"
            return fallback
    return offline_reply(ctx)
