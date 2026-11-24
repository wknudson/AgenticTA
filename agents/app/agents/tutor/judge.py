"""The explain-back judge: does the student's explanation show the key idea?

The key idea is assignment_questions.explain_rubric (fallback: the model answer, or the right
option's text for multiple choice). The judge only runs on honest tries (checkin.honest_try).

- Model path: one structured-output call, {accepted, missing_idea}, lenient on wording.
- No-AI path (no key, AGENTICTA_TUTOR_OFFLINE=1, or the model call failed): content-word
  overlap with the rubric. Words the question already uses don't count, so echoing the
  question isn't enough.

Either way, feedback goes through the answer guard so it never states the answer.
"""
from __future__ import annotations

import re

import logging
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .guard import DICE_THRESHOLD, content_stems, content_words, guard_reply, stem, word_dice
from .models import tutor_model
from .questions import AnswerKey

log = logging.getLogger(__name__)

MIN_COVERAGE = 0.4   # share of the rubric's key words the explanation must cover...
MIN_HITS = 2         # ...and at least this many of them (or all, if the rubric has fewer)
MIN_KEY_WORDS_TO_NAME = 3  # only name a missing word if that can't give the whole idea away
# Words that aren't a reason ("I think it's right, I guess").
NON_REASONS = {"think", "guess", "know", "answer", "right", "correct", "wrong", "yeah", "yep", "maybe", "probably",
               "sure", "option", "choice", "pick", "picked", "chose", "choose", "seems", "looks", "feel", "because",
               "idk", "dunno", "question", "true", "false"}


@dataclass
class Verdict:
    accepted: bool
    feedback: str
    source: str  # "model" | "offline" | "rule"


class JudgeOut(BaseModel):
    accepted: bool = Field(description="True if the explanation shows the key idea, even in informal or partial wording.")
    missing_idea: str | None = Field(
        default=None,
        description="If not accepted: a short nudge (under 15 words) toward what is missing, WITHOUT stating the answer.")


GOOD = "That explanation shows the key idea."
NOT_YET = "That doesn't show the key idea yet. Look back at your notes, talk it through with the tutor, and try again in your own words."
JUST_THE_QUESTION = "That mostly repeats the question. Say *why*, in your own words."


def copies_question(explanation: str, key: AnswerKey) -> bool:
    return word_dice(explanation, key.question_text) >= DICE_THRESHOLD


COPIED = "That's copied, not your own words. Explain it the way you'd tell a friend."


COPY_RUN = 8  # this many words in a row, straight from the answer, is a paste, not a paraphrase


def _longest_shared_run(a: str, b: str) -> int:
    wa, wb = _norm_words(a), _norm_words(b)
    best, prev = 0, [0] * (len(wb) + 1)
    for x in wa:
        cur = [0] * (len(wb) + 1)
        for j, y in enumerate(wb, 1):
            if x == y:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def _norm_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def copies_answer(explanation: str, key: AnswerKey) -> bool:
    """A near-verbatim paste of the model answer or rubric (e.g. from the tutor's reveal) isn't
    an explanation. Sharing key words is fine (that's what a good answer does); copying a long
    run of them, or almost the whole thing, isn't. Option texts are left out: naming the option
    you picked is fine."""
    for secret in (key.model_answer, key.rubric):
        if not secret:
            continue
        run = _longest_shared_run(explanation, secret)
        if run >= min(COPY_RUN, len(_norm_words(secret))) and run >= 4:
            return True
        if word_dice(explanation, secret) >= 0.9:
            return True
    return False


def offline_judge(explanation: str, key: AnswerKey) -> Verdict:
    """Deterministic: content-word overlap with the rubric (crude 5-letter stems)."""
    if copies_question(explanation, key):
        return Verdict(False, JUST_THE_QUESTION, "rule")
    target = key.judge_target()
    if not target:
        return Verdict(True, GOOD, "offline")  # nothing to check against: an honest try is enough
    question = content_stems(key.question_text)
    # Multiple choice: the right option is checked separately, so naming it ("my answer is
    # Mitochondria") is not a reason. Its words count for nothing here.
    option = {stem(w) for t in key.correct_texts for w in content_words(t)} if key.kind == "choice" else set()
    key_words = [w for w in content_words(target) if stem(w) not in question and stem(w) not in option]
    if not key_words and key.kind != "choice":
        key_words = content_words(target)
    # one entry per stem, keeping the first spelling (used to name a missing idea)
    by_stem: dict[str, str] = {}
    for w in key_words:
        by_stem.setdefault(stem(w), w)
    have = content_stems(explanation) - option
    if not by_stem and key.kind != "choice":
        return Verdict(True, GOOD, "offline")
    hits = [s for s in by_stem if s in have]
    need = min(MIN_HITS, len(by_stem))
    if by_stem and len(hits) >= need and len(hits) / len(by_stem) >= MIN_COVERAGE - 1e-9:
        return Verdict(True, GOOD, "offline")
    if key.kind == "choice" and not key.rubric:
        # MC without a rubric: the right option is already required, so an actual reason (two
        # meaningful words beyond the question, e.g. "they're the powerhouse, they make energy") is enough.
        reasons = have - question - {stem(w) for w in NON_REASONS}
        if len(reasons) >= MIN_HITS:
            return Verdict(True, GOOD, "offline")
    missing = [w for s, w in by_stem.items() if s not in have]
    if hits and len(by_stem) >= MIN_KEY_WORDS_TO_NAME and missing:
        feedback, blocked = guard_reply(f"You're close. Say more about \"{missing[0]}\".", key,
                                        allow_reveal=False)
        return Verdict(False, NOT_YET if blocked else feedback, "offline")
    return Verdict(False, NOT_YET, "offline")


JUDGE_PROMPT = """You check a student's short explanation on a check-in question. Be lenient about wording,
spelling and grammar: accept if the explanation shows the key idea, even partly or informally.
Reject if it is wrong, off-topic, only restates the question, or names an answer without any reason.
If you reject, missing_idea is a short nudge (under 15 words) toward what's missing. It must NOT state
the answer or the key idea itself, e.g. "Say more about what it controls." """


def model_judge(explanation: str, key: AnswerKey) -> Verdict:
    model = tutor_model().with_structured_output(JudgeOut)
    lines = [f"Question: {key.question_text}"]
    if key.kind == "choice":
        lines.append(f"Right answer: {', '.join(key.correct_texts)}")
    lines += [f"Key idea a good explanation shows: {key.judge_target()}", f"Student's explanation: {explanation}"]
    out = model.invoke([SystemMessage(JUDGE_PROMPT), HumanMessage("\n".join(lines))])
    if isinstance(out, dict):
        out = JudgeOut(**out)
    if out.accepted:
        return Verdict(True, GOOD, "model")
    feedback = (out.missing_idea or "").strip()
    feedback = f"Not quite yet. {feedback}" if feedback else NOT_YET
    feedback, blocked = guard_reply(feedback, key, allow_reveal=False)
    return Verdict(False, NOT_YET if blocked else feedback, "model")


def judge(explanation: str, key: AnswerKey, *, offline: bool) -> Verdict:
    if copies_question(explanation, key):
        return Verdict(False, JUST_THE_QUESTION, "rule")  # no model call for an echo
    if not offline:
        try:
            return model_judge(explanation, key)
        except Exception:  # missing key, quota, outage, bad output: never a 500
            log.warning("tutor judge: model call failed, using the offline judge", exc_info=True)
    return offline_judge(explanation, key)
