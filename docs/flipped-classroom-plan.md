# Flipped classroom plan

**Status:** built (2026-11-24), ready for team review. See *Build status* at the end · **Replaces:** the "assignment graded on accuracy, AI Dependency score" model

## Why we're changing it

Today the student assignment is graded on correctness, and the AI Dependency score marks heavy tutor use as bad. Both push students the wrong way: if the points depend on being right, the easy move is to open another tab and ask a different AI. Then the student learns less and the teacher gets no data.

We want the opposite. Students should *want* to use our tutor, because:
- it actually helps them (it knows the unit's material and the teacher's rules), and
- every question they ask tells the teacher what to reteach.

So the assessment stops being a test and becomes a **check-in**: full credit for honestly working through every question, with the tutor right there. The learning happens in the **games** before it, and the teaching happens in **class**, aimed at what the check-ins revealed.

## Decisions (from the planning interview)

| Question | Decision |
|---|---|
| Where it happens | **Both parts at home, before class.** The teacher walks in knowing what the class is stuck on. |
| What the work is built from | **The teacher picks a unit.** The agents pull everything filed under that unit in the Library. No more uploading PDFs per assignment. |
| Games | **Flashcards, matching, fill in the blank.** Fun comes from **points, streaks, levels**, and **missed cards coming back** until they're right. |
| Gate | The check-in **unlocks at a mastery bar** (default 80% of the unit's cards mastered). |
| Check-in questions | **Mix of multiple choice and short "explain why" answers.** |
| What "complete" means | **Every question attempted, and every miss fixed with the tutor.** Correctness never lowers the grade. |
| How far the tutor goes | **Teacher setting per assignment:** *hints only* (never the answer) or *answer after honest tries* (then the student explains it back). |
| Correctness | **Shown to students as feedback and to the teacher in reports.** Not part of the grade. |
| AI Dependency score | **Replaced by learning signals:** what each student struggled with, how much help they needed, and whether they got there. |
| Teacher view before class | **Class misconceptions, per-student struggles, who hasn't finished, and a suggested warm-up.** |

## The new flow

```
TEACHER                                   STUDENT (at home, before class)            TEACHER (before class)
-------                                   -------------------------------            ----------------------
Pick "Unit 3" + lesson date
  -> agents build a unit package:
     games (flashcards, matching, fill-in)
     + check-in questions (MC + explain)
  -> one approval in Approvals            1. PRACTICE: play games
  -> due date lands on the calendar          points, streaks, levels
                                             missed cards come back
                                             mastery bar fills to 80%  --unlocks-->
                                          2. CHECK-IN: answer every question
                                             right  -> done
                                             missed -> fix it with the tutor
                                             all resolved -> COMPLETE (full credit)
                                                                                     Briefing: who's done, top
                                                                                     misconceptions, per-student
                                                                                     struggles, suggested warm-up
```

## What changes, area by area

### 1. Teacher: build a unit package instead of uploading PDFs

**Today:** `AssignmentEditor.tsx` uploads PDFs from disk → `POST /api/ai/extract-pdf-text` → `POST /api/ai/generate-questions` (one OpenAI call, raw JSON). The Library is not used.

**New: "New unit check-in"** in the Assignments tab:
1. Pick a **unit** (from `GET /agents/filing/units`) and a **lesson date**. The due date defaults to the evening before the lesson, and the scheduler can suggest it from the class calendar.
2. Settings: **tutor mode** (`hints_only` | `answer_after_tries`, with N tries, default 2), **mastery threshold** (default 80%), and the number of check-in questions (default 6: 4 MC + 2 explain).
3. **Generate** runs a new `POST /agents/games/unit-package` that:
   - pulls the unit's chunks from the Library (`library.list_files(class_id)` filtered by `unit`, plus `library.search` scoped to the unit for coverage),
   - builds the three game activities (existing generate → review loop),
   - builds the check-in questions from the same chunks (MC with distractors + short "explain why" with a model answer and grading notes),
   - saves everything as **draft** and sends **one** approval ("Publish Unit 3 practice + check-in?"), with a preview like the scheduler's `PublishPreview`.
4. On approval: the assignment row, its questions and the activities are published together. A calendar event "Unit 3 practice + check-in due" is added.

The old PDF flow stays reachable as "Build from files" for anything outside the Library, but it's no longer the main path.

**Why the games agent owns this:** it already has the graph (retrieve → generate → review → save draft → approval), and an independent reviewer is exactly what check-in questions need too. The Express question generator stays for the legacy flow.

### 2. Data model

`backend/db/schema.sql` is applied fresh (no migrations), so after these land everyone runs `npm run db:reset` once. Agent tables use their own `schema.sql` plus `ADDED_COLUMNS` in `agents/app/shared/db.py`.

**`assignments`** (new columns)
| column | meaning |
|---|---|
| `unit` | the Library unit it was built from (null for legacy assignments) |
| `mode` | `checkin` (new) or `graded` (legacy). Everything below only applies to `checkin` |
| `tutor_mode` | `hints_only` or `answer_after_tries` |
| `tutor_reveal_after` | honest tries before the answer can be explained (default 2) |
| `mastery_threshold` | share of game items that must be mastered to unlock (default 0.8) |
| `lesson_date` | the class the check-in prepares for |

**`assignment_questions`**: add `explain_rubric` (what a good explanation must mention, for the explain-back judge). The short-answer model answer stays in `assignment_question_options` but **is never sent to the browser** (see fixes below).

**`study_activities`** (games): actually set `assignment_id` and the real `unit` (today `save_draft` stores the topic). Give every item a stable `item_id` inside `items_json` so progress can point at it.

**New `game_item_progress`**, one row per student per game item:
`student_id, activity_id, item_id, times_seen, times_correct, last_correct (0/1), box (1-3, for replaying misses), updated_at`.
An item is **mastered** when the student's latest answer to it was right. Mastery = mastered items / all items in the assignment's activities.

**New `game_sessions`**: `student_id, assignment_id, points, best_streak, level, started_at, ended_at`. These are just for the fun parts and for "who's practicing" in the briefing.

**New `checkin_item_status`**, one row per student per check-in question:
| column | meaning |
|---|---|
| `status` | `unanswered` → `correct` (right first time) or `needs_fix` → `fixed` |
| `first_answer`, `first_correct` | the student's first try and whether it was right |
| `tries` | honest tries so far |
| `tutor_turns` | tutor messages on this question |
| `help_level` | `none` / `hint` / `explained` (did the tutor have to give the answer?) |
| `explain_back` | the student's own-words explanation that resolved it |
| `resolved_at` | when it became `correct` or `fixed` |

**`student_chat_messages`**: add `question_id`, and **stop deleting transcripts on submit** (`student.ts:738-748` deletes them today). Without them there is no briefing and no misconceptions. Retention: keep them for the term. The misconception finder already redacts before any model sees them.

**`student_grades` / `student_metrics`**: replace `ai_dependency_score` with the learning signals in section 6. Keep the old column until the metrics screens are switched, then drop it.

### 3. Student: practice (the games)

New **`StudentPractice.tsx`** (plus `games/Flashcards.tsx`, `Matching.tsx`, `FillIn.tsx`) on the student assignment page, shown as step 1 of 2.

- **Points:** +10 for a correct answer, and a streak multiplier (x2 at 5 in a row, x3 at 10). A miss resets the streak, never the points.
- **Levels:** each unit has levels (e.g. one per 25% of mastery). Level-ups get a short celebration. No timers that punish slow readers, except an optional "beat your time" on matching.
- **Missed cards come back:** a missed item goes into box 1 and returns 3 cards later. Getting it right moves it up a box, and box 3 = mastered. Simple Leitner, no AI.
- **Mastery bar** across the top, with the unlock line drawn at the teacher's threshold. Crossing it unlocks step 2 with a clear "Check-in unlocked" moment. Students can keep playing after that.
- **Fill in the blank** checks answers with forgiving matching (case, extra spaces, small typos within an edit distance of 1-2, accepted alternates from the generator). No model call per answer.
- Progress is saved after every answer, so leaving and coming back loses nothing.

Endpoints (Express, because students are already authenticated there):
- `GET /api/student/assignments/:classId/:assignmentId/practice`: activities (without review notes), the student's progress, and mastery
- `POST /api/student/assignments/:classId/:assignmentId/practice/answer` `{activityId, itemId, correct}`: updates progress, returns points, streak, level, mastery and unlocked

The browser decides whether a card was right (the answers are in the cards anyway: it's practice, not a test). Points can be faked by a determined student, but they don't count for anything except the mastery gate, and the gate only lets them reach the ungraded-for-correctness check-in sooner. That's an acceptable trade for zero per-answer model calls.

### 4. Student: the check-in

Step 2 of the student assignment page, once unlocked. One question at a time, with a progress row ("4 of 6 resolved").

1. **Answer.** MC is checked exactly, as today. "Explain why" answers are judged by the model (lenient rubric: does it show the key idea from `explain_rubric`?). The student sees right or not right immediately (correctness is feedback, not grade).
2. **Right the first time** → `correct`, next question.
3. **Missed** → `needs_fix`, and the **tutor panel opens scoped to that question**: "Let's figure this one out together." The tutor knows the question, the student's answer, the unit's material, and the teacher's tutor mode.
   - **Hints only:** the tutor asks questions and gives hints, never the answer. The existing answer-blocker (Dice similarity ≥ 0.72) stays on.
   - **Answer after tries:** after `tutor_reveal_after` honest tries, the tutor may walk through the answer.
4. **Fixing it** takes two things: the right answer (for MC, pick again; for explain, rewrite) **plus a one-to-two sentence explanation in their own words**. The tutor's explain-back judge checks the explanation and marks the question `fixed`. This is what stops brute-forcing MC: each retry needs a reason.
5. **Complete** when every question is `correct` or `fixed`. Grade = **full points**. If the due date passes first, partial credit = resolved questions / total questions.

**What counts as an "honest try"**: a non-empty answer that isn't a copy of the previous one and isn't filler ("idk", "?", one word on an explain question). This is deterministic and cheap, and the judge only runs on real attempts.

The end screen shows what they got right first time, what they fixed, and a "what was hardest?" box (optional, feeds the briefing).

### 5. The tutor moves to the agents service

The tutor TODO in `agents/app/agents/tutor/router.py` becomes required work, because the check-in needs a tutor that knows which question it's on and can mark it fixed.

- **`create_agent`** with read-only tools: `search_unit(query)` (Library search scoped to the assignment's unit), `get_question(question_id)` (text, options, and the student's attempts; never the model answer in hints-only mode), and `judge_explanation(question_id, explanation)` (structured output: `{accepted, missing_idea}`). That last one is the only tool that changes anything, and it can only move a question from `needs_fix` to `fixed`.
- **Middleware:** answer blocker (ported from `ai.ts:50`), `PIIMiddleware`, `ModelCallLimitMiddleware`, `BlockedActionsMiddleware`. **Tutor mode is enforced in code, not just the prompt:** in `hints_only` the model answer is never in the context at all.
- **Student auth:** the FastAPI service verifies the same student JWT Express signs (`STUDENT_JWT_SECRET`, `backend/auth/studentToken.ts`). Today `POST /api/ai/chat` is unauthenticated and trusts `studentId` from the body.
- **Transcripts:** written to `student_chat_messages` with `question_id`, and kept.
- The Express `/api/ai/chat` route stays only for legacy `graded` assignments, then is retired.

### 6. Learning signals (replacing AI Dependency)

All deterministic, computed from `checkin_item_status` and `game_item_progress`. No model call, and every number can be explained to a parent.

| Signal | Definition | Read it as |
|---|---|---|
| **Practice mastery** | % of game items mastered | did they practice |
| **First-try accuracy** | % of check-in questions right the first time | what they knew walking in |
| **Fixed with help** | % of misses they resolved with the tutor | did they push through |
| **Help needed** | per question: none / hint / explained | how hard it was for them |
| **Still shaky** | questions fixed only after the tutor explained, plus game items still in box 1 | what to check in class |

Weekly `student_metrics` becomes **Practice**, **First-try accuracy** and **Fixed with help**. **Understanding** is redefined as first-try accuracy plus half credit for misses fixed without the answer being explained. The `TeacherMetrics.tsx` explanation text, the admin views, `seed-metrics.ts` and the landing page copy all change with it.

### 7. Teacher: the before-class briefing

A new **Briefing** view per check-in assignment (an extension of the Insights tab), meant to be read the morning of the lesson:

1. **Who's where:** not started / practicing (with mastery %) / check-in in progress / complete. Pure SQL, live.
2. **Class misconceptions:** the misconception finder, changed to:
   - run **before** the due date (today per-assignment runs only open after it),
   - read check-in transcripts grouped by `question_id` (better clusters than raw messages),
   - add deterministic signals: most-missed check-in questions and most-missed game items. No model needed for those.
   - Still redacted, still local model first, still quotes with names hidden.
3. **Per-student struggles:** for each student, the questions they missed, help level, and their explain-back in their own words. Teacher-only. This replaces the AI Dependency column.
4. **Suggested warm-up:** 3-5 minutes for the start of class built from the top 2 misconceptions: one or two questions to put on the board and a 2-sentence reteach. Generated once, cached, and editable. Handing it to the materials agent ("make this a slide") reuses the existing `POST /insights/{id}/draft` hand-off.

### 8. Fixes we need regardless (found while mapping the code)

| Problem | Where | Fix |
|---|---|---|
| Chat transcripts are deleted on submit, so the misconception finder can only ever see students who never submitted | `backend/routes/student.ts:738-748` | stop deleting; keep for the term |
| Short-answer model answers are sent to the browser and put in the tutor's context | `student.ts:479` (options), the frontend's `assignmentContext` | never send `is_correct=1` short-answer options; the tutor gets them server-side only, and only in `answer_after_tries` mode |
| Tutor chat has no auth and trusts `studentId` from the body | `backend/routes/ai.ts:60` | student JWT required (Python tutor), Express route retired |
| The current message is sent twice in the tutor prompt | `frontend/services/aiService.ts` / `ai.ts` | goes away with the new tutor |
| Teacher preview skips the answer blocker (no `assignmentId`) | `TeacherStudentPreview.tsx:71` | preview uses the new tutor with the real assignment |
| UI allows 1-70 questions, backend clamps to 30 | `AssignmentEditor.tsx:292` | match the limits |
| `StudentMetrics.tsx` and `StudentGrades.tsx` are unused mock components | `frontend/components/` | delete or replace with the student's own progress view |

## Build order

Each step ends in something demoable, so we can stop at any point with a working app.

| # | Step | Done when |
|---|---|---|
| 0 | **Foundations:** keep transcripts, add `question_id`, stop leaking answers, new columns and tables, `db:reset` | tests show transcripts survive submit and no answer reaches the browser |
| 1 | **Unit package:** real generate and review in the games agent, check-in question generation, one approval, publish creates the assignment and the calendar event | a teacher picks Unit 2 of the Biology sample course and approves a package |
| 2 | **Practice player:** three game types, points, streaks, levels, Leitner replays, mastery bar, unlock | a student reaches 80% and the check-in unlocks; refresh keeps progress |
| 3 | **Check-in + new tutor:** question-scoped tutor in the agents service, both tutor modes, honest-try rule, explain-back judge, completion grading | a student misses 2 questions, fixes them with the tutor, and gets full credit; brute-forcing MC doesn't work |
| 4 | **Learning signals:** new metrics, AI Dependency removed from screens, seed data and landing page updated | Metrics tab shows practice, first-try accuracy and fixed-with-help |
| 5 | **Briefing:** status board, misconceptions before the due date, per-student struggles, warm-up | the teacher opens the briefing the morning of the lesson and sees all four parts |
| 6 | **Evals and polish:** offline demos for every new path, eval sets (below), LangSmith projects, docs | `npm run test:agents` green, evals recorded in `agents/evals/results/` |

## Evals (for the write-up)

- **Explain-back judge:** about 60 hand-labeled student explanations (good / partly right / wrong / filler) across 2 units. Measure agreement with our labels and the false-accept rate. False accepts matter most: they let students skip learning.
- **Tutor mode compliance:** scripted student turns that beg for the answer in `hints_only` mode. Measure how often the answer leaks (target: 0, enforced by the blocker plus no answer in context).
- **Generated items:** reviewer acceptance rate, and our own spot check of 30 cards and 10 check-in questions against the source material.
- **Misconceptions with vs without `question_id`:** cluster quality on the same transcripts (does grouping by question help?).

## Model calls and the free tier

| Moment | Calls | Notes |
|---|---|---|
| Build a unit package | ~4-6 | generate and review the games, generate and review the questions. Once per unit |
| A student plays games | **0** | all checking is in code |
| Check-in answer, MC | **0** | exact check |
| Check-in answer, explain | 1 | judge |
| Fixing a miss with the tutor | ~2-6 | tutor turns plus one judge call |
| Briefing | ~2 | misconceptions (local model) plus warm-up |

A class of 30 with ~2 misses each is roughly **200-400 tutor and judge calls per check-in**. That's far past the 20 requests/day of Gemini free on `gemini-3.6-flash`. This is the biggest open decision (below).

## Open questions for the team

1. **Tutor model and quota.** Options: (a) a cheap paid model for the tutor only (the Express tutor already uses OpenAI); (b) Gemini `flash-lite` if its free quota is enough for a demo class; (c) a local Ollama model, like the misconception finder (free and private, but slower and weaker at holding back answers). Recommendation: (a) for the real tutor, plus an offline scripted tutor for demos and tests.
2. **Legacy graded assignments.** Keep `mode = graded` working, or convert everything to check-ins? Recommendation: keep it, but make check-in the default.
3. **Partial credit after the due date.** Resolved / total is proposed. Or should an unfinished check-in just be marked late and stay open?
4. **Leaderboard.** Not chosen (solo progress only). Revisit if students want competition; the data supports it.
5. **Who owns what.** Not split yet; this plan was written as one piece. The natural split follows the agent owners: games (steps 1-2), tutor (step 3), misconceptions/insights (step 5), with the shared foundations (step 0) done first by one person.

---

## Appendix: implementation contract

This is the contract the pieces were built against. The shared rules live in `agents/app/shared/checkin.py` (mastery, points, statuses, honest tries, learning signals, completion grade, weekly metrics). Student login for the agents service is `agents/app/shared/student_auth.py`: it verifies the Express student JWT, and endpoints use `Depends(current_student)` plus `checkin_for_student(...)`. Everything student-facing sends `Authorization: Bearer <token from the student session>`.

**Decisions taken on the open questions:**
- Legacy `graded` assignments keep working.
- The grade is kept current as the student works: points = max_points × resolved / total, so missing the due date means partial credit.
- No leaderboard.
- Every model-backed step has a no-AI path, used when its key is missing or when `offline: true` is set. That covers the unit package generator, the tutor, the explain judge and the warm-up.

### Games agent (`/agents/games`)

| Endpoint | Who | Body / query → response |
|---|---|---|
| `POST /unit-package` | teacher | `{class_id, unit, lesson_date, due_date?, title?, tutor_mode, tutor_reveal_after, mastery_threshold, mc_count=4, explain_count=2, card_count=10, offline=false}` → `{status:"waiting_for_approval", thread_id, approval_groups, package_id, summary:{flashcards, matching, fill_in, mc, explain, generated_by}}`. 409 if the unit has no filed text. `due_date` defaults to the day before `lesson_date`, 23:59. |
| `GET /unit-package/{package_id}` | teacher | the package: `{package_id, class_id, unit, status, settings, generated_by, activities:[{activity_id, kind, title, items}], questions:[{text, kind:"choice"\|"explain", options?:[{text, correct}], answer?, rubric?}], assignment_id}` |
| approval action `publish_unit_package` | teacher | args `{class_id, package_id}`; approve/reject. Approve publishes: an `assignments` row (`mode='checkin'`, settings, `max_points=10`), questions and options (explain questions are `short_answer`, model answer as the `is_correct` option, `explain_rubric` set), activities → `published` with `assignment_id`, plus a published calendar event `"<title> due"` (kind `assignment_due`) when the date passes the scheduler's rules. |
| `GET /practice/{assignment_id}` | student | `{assignment:{assignment_id, title, unit, lesson_date, due_date}, activities:[{activity_id, kind, title, items}], progress:{"<activity_id>:<item_id>":{times_seen, times_correct, last_correct, box}}, stats:<practice_stats>, replay_gap:{1:3, 2:8, 3:20}}` |
| `POST /practice/{assignment_id}/answer` | student | `{activity_id, item_id, correct}` → `record_practice_answer(...)` (stats + `points_awarded`, `multiplier`, `level_up`, `just_unlocked`) |

**Item shapes** (`items_json`; every item has a stable `item_id` string):
- flashcards: `{item_id, front, back}`
- matching: `{item_id, term, definition}`
- fill_in: `{item_id, sentence (contains "____"), answer, alternates:[]}`

**`practice_stats`** = `{mastered, total, mastery (0-1), threshold, unlocked, level, levels, points, streak, best_streak, answers, started}`

### Tutor agent (`/agents/tutor`), all student-facing

| Endpoint | Body → response |
|---|---|
| `GET /checkin/{assignment_id}` | `{assignment:{assignment_id, title, unit, tutor_mode, tutor_reveal_after, due_date, lesson_date, max_points, past_due}, practice:<practice_stats>, unlocked, questions:[Q] (empty until unlocked), signals:<learning_signals>}` |
| `POST /checkin/{assignment_id}/answer` | `{question_id, option_id? , text?}` (first answer) → `{question:Q, correct, feedback, signals}`. 422 `{detail}` if not an honest try. |
| `POST /checkin/{assignment_id}/fix` | `{question_id, option_id?, explanation}` → `{question:Q, accepted, feedback, signals}`. MC needs the right option **and** an accepted explanation. 422 if not an honest try. |
| `POST /checkin/{assignment_id}/chat` | `{question_id, message}` → `{reply, question:Q}`. Allowed while the question is `unanswered` or `needs_fix`. |
| `GET /checkin/{assignment_id}/chat/{question_id}` | `{messages:[{role, content}]}` |

**Q** = `{question_id, number, text, kind:"choice"|"explain", options?:[{option_id, text}], status, first_answer, tries, help_level, last_feedback, can_reveal}`. It never includes the right answer.

### Misconceptions agent: teacher briefing (`/agents/misconceptions`)

| Endpoint | Response |
|---|---|
| `GET /checkins?class_id` | `{checkins:[{assignment_id, title, unit, lesson_date, due_date}]}` |
| `GET /briefing?class_id&assignment_id` | `{assignment, roster:[{student_id, name, stage:"not_started"\|"practicing"\|"checkin"\|"complete", mastery, resolved, total}], counts:{...}, hardest_questions:[{question_id, text, answered, first_try_rate, explained}], hardest_items:[{activity_id, item_id, label, misses, seen}], students:[{student_id, name, signals, missed:[{question_id, text, first_answer, help_level, explain_back, status}]}], misconceptions:[...insights for this assignment], warmup:{...}\|null}` |
| `POST /briefing/warmup?class_id&assignment_id` | generates and stores the warm-up: `{questions:[...], reteach, based_on:[...]}` |
| `PUT /briefing/warmup?class_id&assignment_id` | the teacher's edited warm-up |

The misconception run is allowed **before** the due date for check-ins, and groups transcripts by `question_id`.

---

## Build status (2026-11-24)

Steps 0-5 of the build order are implemented on branch `plan/flipped-classroom`. `npm run test:agents` passes 133 tests, the backend typechecks clean, and the frontend has only the one known error in `AssignmentQuestionsEditorModal.tsx`.

**Where things are**

| Piece | Code |
|---|---|
| Shared rules (mastery, statuses, signals, grade) | `agents/app/shared/checkin.py`, `student_auth.py` |
| Unit package + practice API | `agents/app/agents/games/` (`extract.py` is the no-AI generator) |
| Check-in tutor, judge, answer guard | `agents/app/agents/tutor/` |
| Briefing | `agents/app/agents/misconceptions/briefing.py` |
| Teacher UI | `frontend/components/checkin/` (editor, approval preview, briefing) |
| Student UI | `frontend/components/student/checkin/` |
| Learning-signal metrics | `backend/routes/metricsPayload.ts`, `frontend/components/learningSignals.tsx` |

**Running it with a real model**

Only the Gemini key is set up today, so every agent runs its no-AI path:
- the no-AI generator
- the offline tutor and judge
- the deterministic warm-up

To use Gemini, put overrides in the agent's `.env`:
- `agents/app/agents/games/.env`: `MODEL_GENERATOR=google_genai:<model>` and `MODEL_REVIEWER=google_genai:<model>`
- `agents/app/agents/tutor/.env`: `MODEL_MAIN=google_genai:<model>`
- `GOOGLE_API_KEY` goes in each of those files, or in the project `.env`.

**Found in hand testing and fixed**
- **No-AI cards:** the generator made cards from cut-off fragments ("If.") and from worksheet instructions ("Factor completely: 1) ..."). It also capitalized math (`y` became `Y`), and it skipped lowercase glossary lines ("axis of symmetry: x = h").
- **Due day:** the calendar entry landed on the lesson day, because the due time is sent in UTC. The editor now also sends the teacher's local `due_day`.
- **Approvals:**
  - An approval stayed "approved" when its action failed. It now goes back to pending.
  - A no-AI draft couldn't be approved after a restart when the agent had no API key. Resuming now finishes with a one-line scripted model (test: `tests/test_approval_resume.py`).
- **Unlock:** it could switch off again after a practice miss. Unlocking is now permanent.
- **Student page:** the tutor panel was duplicated (a React key clash).
- **Briefing roster:** it counted students removed from the class.

**Known limits**
- **No-AI generator:** it needs definition-style notes (`term: definition`, `X is ...`). Sparse math units can fall below the 4-term minimum, which returns a clear 409 message. The AI path is meant for those.
- **Offline judge:** for multiple choice, a fix needs the right option plus at least a two-word reason, so a wrong reason still passes. Only the model judge checks the reasoning.
- **Practice points:** the browser reports right/wrong, so points can be faked. They only gate an ungraded-for-correctness check-in.
- **Agents service on Windows:** it can hang when it reloads after a code change, so restart `npm run dev` after editing Python.
