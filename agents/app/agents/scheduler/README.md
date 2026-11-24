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

## Calendar build-out (no AI needed)
- **Fill from syllabus:** `GET /agents/scheduler/term/suggest?class_id=1` reads the dates the Library already found ("First day", "Last day", "no school", "break") and returns term settings plus holidays. A break listed as a start and end date is filled in day by day. Nothing is saved until the teacher clicks Save.
- **Draft from documents:** `POST /agents/scheduler/draft?class_id=1` (`drafting.py`) turns Library dates and assignment due dates into events.
  - **Kinds:** sorted by keywords (quiz/test → assessment, "due" → due date, reading, otherwise class event).
  - **Duplicates:** the same event in several files becomes one event, named by the course calendar or syllabus, with every file listed as its source.
  - **Rule breakers:** dates that break a rule come back as `skipped` with the reason. Events already on the calendar are skipped too.
  - **Approval:** the rest are proposed, then the same `check_conflicts` and `publish_calendar` calls run through `HitlRunner`, so they wait in Approvals like an AI-built calendar.
- **Teacher edits:** `POST /events`, `PATCH /events/{id}` and `DELETE /events/{id}` let the teacher add, move, retitle or remove events from the month view.
  - **Same rules as the agent:** every add and move passes `validate_events`.
  - **Teacher additions publish at once:** the teacher is the approver.
  - **Remove is a soft delete:** the event's status becomes `removed`.
- **UI:** `frontend/components/agents/calendar/`.
  - `MonthCalendar` is the month grid used by both the teacher and student views.
  - `DayEditor` is the teacher's side panel.
  - `PublishPreview` shows the events behind a `publish_calendar` approval, instead of bare ids.
- **Tests:** `agents/tests/test_scheduler_calendar.py`.

## Month calendar feed and check-in suggestions (no AI, `feed.py`)
- **Feed:** `GET /agents/scheduler/feed?class_id=1[&start=YYYY-MM-DD&end=YYYY-MM-DD]` returns everything the month view shows that overlaps the range (default: the term, else today-30 to today+120; 422 if `end` is before `start`).
  - `term`: same as `GET /term`.
  - `events`: published and proposed calendar events. Rows tied to a check-in are left out, because `checkins` covers them.
  - `checkins`: each check-in with `due_day` (its calendar entry's day, else the UTC day of `due_date`) and `open_day` (the day its `publish_unit_package` approval was approved; else the lesson day minus 7 days; never after `due_day`). Also `status` (`live`, `due_soon` or `closed`), stage `counts` for active students, and `calendar_event_id`. The status and count rules are copied from the misconceptions briefing, so keep the two in step.
  - `drafts`: unit packages still waiting for approval, with their lesson day and due day.
  - `assignments`: graded (non check-in) assignments with a due date in the range.
- **Check-in suggestions:** `GET /agents/scheduler/checkin-suggestions?class_id=1` suggests one check-in per filed Library unit.
  - **Anchor:** the unit's next quiz or test after today. Assessment events on the calendar are checked first, then dated labels in the Library ("Unit 3 quiz"). The match uses the unit's number, so Unit 3 doesn't match "Unit 30".
  - **Lesson day:** the 2nd school day before the anchor (a weekday inside the term, and not a holiday), as long as it's still after today. Otherwise it's the 1st school day before.
  - **Due day:** the day before the lesson.
  - **Skipped units:** a unit is skipped, with the reason, if it already has a check-in that isn't closed, has a draft package, has no upcoming quiz or test, or the anchor is too soon. Nothing is saved.
- **Tests:** `agents/tests/test_scheduler_feed.py`.

## Remaining verification
- [ ] Verify date extraction against a seeded syllabus and a planted conflict in the project demo data.
- [ ] Run the scheduler approval and calendar checks in `agents/tests/test_merrick_agents.py` when ready to verify.
