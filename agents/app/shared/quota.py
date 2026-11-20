"""Make sense of provider rate-limit errors (written for Gemini's free tier, works for any 429).

Gemini free tier, as hit while building the filing pipeline:
  gemini-3.6-flash      20 generate requests PER DAY
  gemini-embedding-2    100 embed requests PER MINUTE
So the right reaction depends on which limit it was:
  per-minute  -> wait the retry delay Google sends (capped) and try again
  per-day     -> stop calling that model for the rest of the window, move on to the fallback
  503 / high demand -> try the next model now

    from app.shared import quota
    kind, wait_s = quota.classify(err)
    if quota.blocked("gemini-3.6-flash"): ...
"""
from __future__ import annotations

import re
import threading
import time
from typing import Literal

Kind = Literal["minute", "daily", "overload", "other"]
MAX_WAIT_S = 65  # never sleep longer than this inside a request

_blocked_until: dict[str, float] = {}
_lock = threading.Lock()


def _seconds(text: str) -> float | None:
    """'43s', '43.9s', '8h18m11.05s' -> seconds."""
    m = re.search(r"retryDelay'?:?\s*'?(\d+(?:\.\d+)?)s", text) or re.search(r"retry in ((?:\d+h)?(?:\d+m)?[\d.]+s)", text)
    if not m:
        return None
    raw = m.group(1)
    if re.fullmatch(r"[\d.]+", raw):
        return float(raw)
    total = 0.0
    for num, unit in re.findall(r"([\d.]+)([hms])", raw):
        total += float(num) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


def classify(err: BaseException) -> tuple[Kind, float | None]:
    text = f"{type(err).__name__} {err}"
    if "429" in text or "RESOURCE_EXHAUSTED" in text or "RateLimit" in text:
        if re.search(r"PerDay|per day", text, re.IGNORECASE):
            return "daily", _seconds(text)
        return "minute", _seconds(text) or 30.0
    if re.search(r"\b503\b|UNAVAILABLE|high demand|overloaded|\b504\b|DEADLINE_EXCEEDED|Timeout", text, re.IGNORECASE):
        return "overload", None
    return "other", None


def block(model: str, seconds: float | None) -> None:
    with _lock:
        _blocked_until[model] = time.time() + (seconds or 3600)


def blocked(model: str) -> bool:
    with _lock:
        until = _blocked_until.get(model)
        if until and until <= time.time():
            del _blocked_until[model]
            return False
        return bool(until)


def wait(seconds: float | None) -> None:
    time.sleep(min(seconds or 30.0, MAX_WAIT_S))


def friendly(kind: Kind, model: str) -> str:
    return {
        "daily": f"{model} hit its daily free-tier limit; use 'Re-check with AI' later",
        "minute": f"{model} hit its per-minute limit",
        "overload": f"{model} was overloaded",
        "other": f"{model} returned an error",
    }[kind]
