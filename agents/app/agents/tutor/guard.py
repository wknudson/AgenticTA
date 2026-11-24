"""The answer guard: deterministic, so a tutor reply can't hand over the answer while the
student is still meant to work it out.

Ported from the Express tutor (backend/routes/ai.ts, messageMatchesAssignmentQuestion): the
same normalisation and Sørensen-Dice coefficient on word sets, same 0.72 threshold. There it
blocked student messages that copied a question; here it checks the tutor's *reply* against
the answer key (right option text, model answer, explain rubric):

- the right answer appears verbatim (word-bounded), or
- some stretch of the reply (a sentence, or a window as long as the answer) has Dice >= 0.72
  with it, or
- multiple choice: the reply names the right option's distinctive words (the ones not in the
  question or any wrong option), e.g. "membrane" for "Cell membrane".

Used in hints_only mode always, and in answer_after_tries mode until may_reveal() is true.
"""
from __future__ import annotations

import re

from .questions import AnswerKey

DICE_THRESHOLD = 0.72  # same as ai.ts

# Option texts too generic to block on sight ("Is that true?"): only "the answer is X" phrasings.
GENERIC_ANSWERS = {"true", "false", "yes", "no", "both", "neither", "none", "all", "all of the above",
                   "none of the above", "both a and b"}

STOPWORDS = frozenset("""a an and are as at be been being but by can could did do does doing for from had has have
how i if in into is it its it's me my of on or our so such than that the their them then there these they this
those to too was we were what when where which while who whom why will with would you your yours about also
because just like more most much not only other over same some very should something thing things get gets got
make makes made many may might must need needs one ones out up down use used using way well yes no""".split())


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())).strip()


def _words(text: str) -> list[str]:
    return [w for w in normalize(text).split(" ") if len(w) > 1]


def word_dice(a: str, b: str) -> float:
    """Sørensen-Dice coefficient on word sets (0-1), exactly as wordDiceSimilarity in ai.ts."""
    wa, wb = set(_words(a)), set(_words(b))
    if not wa or not wb:
        return 0.0
    return 2 * len(wa & wb) / (len(wa) + len(wb))


def stem(word: str) -> str:
    """Crude stem: drop a common suffix, keep the first 5 letters. 'controls' ~ 'controlled'."""
    for suf in ("ing", "edly", "ed", "es", "ly", "s"):
        if len(word) > len(suf) + 3 and word.endswith(suf):
            word = word[: -len(suf)]
            break
    return word[:5]


def content_words(text: str) -> list[str]:
    """Meaningful words in order, no duplicates (lowercase, stopwords and 1-2 letter words dropped)."""
    seen, out = set(), []
    for w in normalize(text).split(" "):
        if len(w) > 2 and w not in STOPWORDS and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def content_stems(text: str) -> set[str]:
    return {stem(w) for w in content_words(text)}


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def _contains_phrase(reply_norm: str, phrase: str) -> bool:
    p = normalize(phrase)
    return bool(p) and re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", reply_norm) is not None


def distinctive_words(key: AnswerKey) -> list[str]:
    """MC only: words of the right option that the question and the wrong options don't use."""
    if key.kind != "choice":
        return []
    others = content_stems(key.question_text)
    for w in key.wrong_texts:
        others |= content_stems(w)
    out = []
    for text in key.correct_texts:
        if normalize(text) in GENERIC_ANSWERS:
            continue
        out += [w for w in content_words(text) if stem(w) not in others]
    return out


def _generic_reveal(reply_norm: str, answer: str) -> bool:
    a = re.escape(normalize(answer))
    return re.search(rf"\b(answer|statement|it|that|this|option)( is| s|s| would be)( definitely| actually)? {a}\b|"
                     rf"\b{a} is (the )?(right|correct)\b|\bpick {a}\b|\bchoose {a}\b", reply_norm) is not None


def leaks_answer(reply: str, key: AnswerKey) -> bool:
    """Does this text give away the answer?"""
    nr = normalize(reply)
    if not nr:
        return False
    for secret in key.secrets():
        ns = normalize(secret)
        if not ns:
            continue
        if ns in GENERIC_ANSWERS:
            if _generic_reveal(nr, secret):
                return True
            continue
        if len(ns) >= 3 and _contains_phrase(nr, secret):
            return True
        sw = _words(secret)
        if len(sw) < 2:
            continue
        if any(word_dice(s, secret) >= DICE_THRESHOLD for s in _sentences(reply)):
            return True
        rw = _words(reply)
        n = len(sw)
        for i in range(max(1, len(rw) - n + 1)):
            if word_dice(" ".join(rw[i:i + n]), secret) >= DICE_THRESHOLD:
                return True
    distinct = distinctive_words(key)
    reply_stems = {stem(w) for w in nr.split(" ")}
    return bool(distinct) and all(stem(w) in reply_stems for w in distinct)


def mask_answer(text: str, key: AnswerKey) -> tuple[str, bool]:
    """Blank out the answer (and MC distinctive words) in a snippet from the notes: a fill-in hint."""
    out, masked = text, False
    patterns = []
    for phrase in sorted((s for s in key.secrets() if normalize(s) not in GENERIC_ANSWERS), key=len, reverse=True):
        words = [re.escape(w) for w in re.findall(r"[A-Za-z0-9]+", phrase)]
        if words:
            patterns.append(r"[^A-Za-z0-9]+".join(words) + r"\w*")
    for w in distinctive_words(key):  # any form of the word: mitochondria, mitochondrion
        st = stem(w)
        patterns.append(re.escape(st if len(st) >= 5 else w) + r"\w*")
    for pat in patterns:
        out, n = re.subn(r"(?<![A-Za-z0-9])" + pat, "____", out, flags=re.IGNORECASE)
        masked = masked or n > 0
    return out, masked


def hint_message(key: AnswerKey) -> str:
    """What the student gets instead of a reply that would give the answer away."""
    if key.kind == "choice":
        nudge = "Try ruling the options out one at a time: which ones can you show are wrong, and why?"
    else:
        nudge = "Try putting the main idea into one sentence of your own, and I'll tell you what to add."
    return f"I can't give you the answer, but you can get there. {nudge} Check your notes for this unit if you get stuck."


def guard_reply(reply: str, key: AnswerKey, *, allow_reveal: bool) -> tuple[str, bool]:
    """(text to send, blocked?). allow_reveal = may_reveal() in answer_after_tries mode."""
    if allow_reveal or not leaks_answer(reply, key):
        return reply, False
    return hint_message(key), True
