# Scheduler: owner Teammate B

**What it does:** builds the student calendar from dates in filed documents and assignments, and flags conflicts.

**Kind of system:** semi-autonomous single agent (`create_agent`). Pattern: handoff with a decision point. Clean schedule → propose; conflict → explain to the teacher.

**Model:** `claude-haiku-5-5` (fast, reliable tool calling).

**Why it's different from the other agents:** every date and rule check is deterministic code exposed as a tool. The LLM reasons; code computes. Dates can't be hallucinated, and each check shows up in LangSmith.

**Controls:** `BlockedActionsMiddleware`, `ToolCallLimitMiddleware(run_limit=15)`, and `HumanInTheLoopMiddleware` on `publish_calendar` (it shows up in the Approvals tab). Rules in `check_conflicts`: inside the term, not on a weekend or holiday, at most N assessments per day.

## Files you own
`agents/app/agents/scheduler/*`, `frontend/components/agents/SchedulerPanel.tsx`

## Already working (skeleton)
- `POST /agents/scheduler/demo?class_id=1` runs offline with real tools, pauses for approval, and publishes on approval
- `POST /agents/scheduler/run` is the real agent (needs `ANTHROPIC_API_KEY`)
- `GET /agents/scheduler/events?class_id=1[&status=published]`

## Done when
- [ ] term and holidays form writes `term_calendar` (remove the default in `tools._term`)
- [ ] correct calendar from a seeded syllabus; a planted conflict gets caught
- [ ] a test proves publishing is blocked until approved (one exists in `tests/test_skeleton.py`; extend it)
- [ ] student calendar view, plus an optional `.ics` download
