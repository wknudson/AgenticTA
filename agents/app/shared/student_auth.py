"""Student login for the agents service: verifies the same JWT that Express issues.

Express signs student tokens in backend/auth/studentToken.ts with HS256 and
STUDENT_JWT_SECRET (or JWT_SECRET, or a dev default). The project .env is loaded into the
environment by settings.py, so both services see the same secret.

HS256 verification is a few lines of stdlib (hmac + base64), so there's no new dependency.

    @router.get("/checkin/{assignment_id}")
    def state(assignment_id: int, student_id: int = Depends(current_student)): ...
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import Header, HTTPException

from .db import connect

DEV_SECRET = "dev-student-secret-change-me"  # same fallback as backend/auth/studentToken.ts


def _secret() -> bytes:
    return (os.getenv("STUDENT_JWT_SECRET") or os.getenv("JWT_SECRET") or DEV_SECRET).encode()


def _b64decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class InvalidToken(Exception):
    pass


def verify_student_token(token: str) -> int:
    """Return the student id, or raise InvalidToken."""
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        header = json.loads(_b64decode(header_b64))
        payload = json.loads(_b64decode(payload_b64))
        signature = _b64decode(sig_b64)
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidToken("malformed token") from exc
    if header.get("alg") != "HS256":  # never accept "none" or an algorithm we didn't sign with
        raise InvalidToken("unexpected algorithm")
    expected = hmac.new(_secret(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, signature):
        raise InvalidToken("bad signature")
    if "exp" in payload and time.time() >= float(payload["exp"]):
        raise InvalidToken("expired")
    if payload.get("role") != "student" or not isinstance(payload.get("studentId"), int):
        raise InvalidToken("not a student token")
    return payload["studentId"]


def issue_student_token(student_id: int, ttl_seconds: int = 3600) -> str:
    """For tests and offline demos only; real tokens come from Express (/api/auth/student/login)."""
    now = int(time.time())
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64encode(json.dumps({"role": "student", "studentId": student_id, "iat": now,
                                     "exp": now + ttl_seconds}).encode())
    sig = _b64encode(hmac.new(_secret(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def current_student(authorization: str | None = Header(default=None)) -> int:
    """FastAPI dependency: the logged-in student's id (401 otherwise)."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Missing student auth token")
    try:
        return verify_student_token(token.strip())
    except InvalidToken as exc:
        raise HTTPException(401, "Invalid or expired student token") from exc


def _past(iso: str | None) -> bool:
    if not iso:
        return False
    try:
        due = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) > due


def checkin_for_student(student_id: int, assignment_id: int, *, writing: bool = False) -> dict[str, Any]:
    """The check-in assignment row, after checking the student may use it.

    404 if it isn't a check-in, 403 if the student isn't enrolled, and 403 for writes after
    the due date (same rule as Express's ensureStudentCanAccess). Reading stays allowed after
    the due date so students can see what they did.
    """
    with connect() as conn:
        row = conn.execute("SELECT * FROM assignments WHERE assignment_id = ? AND mode = 'checkin'",
                           (assignment_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Check-in not found")
        # Removing a student from a class sets status 'inactive'; they lose access (same as Express).
        enrolled = conn.execute("SELECT 1 FROM student_classes WHERE student_id = ? AND class_id = ? "
                                "AND LOWER(TRIM(status)) = 'active'", (student_id, row["class_id"])).fetchone()
    if not enrolled:
        raise HTTPException(403, "You are not enrolled in this class")
    if writing and _past(row["due_date"]):
        raise HTTPException(403, "This check-in can no longer be changed because the due date has passed.")
    return dict(row)
