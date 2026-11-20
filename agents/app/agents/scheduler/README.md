# Scheduler: owner Merrick

**What it does:** builds the student calendar from dates in filed documents and assignments, and flags conflicts.

**Kind of system:** semi-autonomous single agent (`create_agent`). Pattern: handoff with a decision point. Clean schedule → propose; conflict → explain to the teacher.

**Model:** `claude-haiku-5-5` (fast, reliable tool calling).

**Why it's different from the other agents:** every date and rule check is deterministic code exposed as a tool. The LLM reasons; code computes. Dates can't be hallucinated, and each check shows up in LangSmith.

**Controls:** `BlockedActionsMiddleware`, `ToolCallLimitMiddleware(run_limit=15)`, and `HumanInTheLoopMiddleware` on `publish_calendar` (it shows up in the Approvals tab). Rules in `check_conflicts`: inside the term, not on a weekend or holiday, at most N assessments per day.

## Files you own
`agents/app/agents/scheduler/*`, `frontend/components/agents/SchedulerPanel.tsx`

## Implemented
- Teacher form saves term dates, holidays, and the maximum number of assessments or due dates per day to `term_calendar`.
- Deterministic validation rejects dates outside the term, weekends, holidays, invalid event kinds, and over-capacity days. Publishing rechecks the current rules.
- `POST /agents/scheduler/demo?class_id=1` runs offline with real tools and waits for teacher approval before publishing. It uses a clearly labeled synthetic term if no settings exist.
- `POST /agents/scheduler/run` runs the configured model (needs `ANTHROPIC_API_KEY`).
- `GET /agents/scheduler/events?class_id=1[&status=published]`, `GET/PUT /agents/scheduler/term`, and `GET /agents/scheduler/conflicts` support the teacher panel and student calendar.
- Students see published events on their assignment page; `GET /agents/scheduler/calendar.ics?class_id=1` exports approved events.

## Remaining verification
- [ ] Verify date extraction against a seeded syllabus and a planted conflict in the project demo data.
- [ ] Run the scheduler approval and calendar checks in `agents/tests/test_merrick_agents.py` when ready to verify.
