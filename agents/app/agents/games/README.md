# Study games: owner Teammate D

**What it does:** builds a **unit package** for a flipped-classroom check-in (docs/flipped-classroom-plan.md, sections 1-3): three games (flashcards, matching, fill in the blank) plus the check-in questions (multiple choice + "explain why"), all from what the teacher filed under one Library unit. The teacher approves the package once; publishing creates the check-in assignment, its questions, the games and a calendar event. Students then play the games (step 1 of 2) until the mastery bar unlocks the check-in.

**Kind of system:** generator + independent reviewer, as a **hand-built LangGraph StateGraph** (not `create_agent`). It's the team's example of graph engineering: fixed, auditable control flow.

**Models:** `gpt-6-luna` generates; `claude-sonnet-5-5` reviews. Using a different provider means the reviewer isn't grading its own work. Both use structured output (Pydantic: `PackageOut`, `ReviewOut` in `models.py`).

**No-AI path:** without keys for both roles, or with `offline: true`, the package comes from the deterministic generator in `extract.py`. It works on real course text (see below) and gives the same package for the same Library text.

## The graph (`agent.py`)

```
unit package:   unit_sources -> draft_package -> review_package --(rejected items, attempts left)--> draft_package
                                                                 +--(enough passed / MAX_ATTEMPTS)--> save_package
                save_package -> request_package_publish  (interrupt: publish_unit_package, approve | reject) -> END
single activity (legacy /run, /demo):  retrieve -> generate -> review -> save_draft -> request_publish -> END
```

One compiled graph holds both flows because `HitlRunner` registers one resumer per agent. `review_package` always runs the deterministic checks (`package.check_draft`: grounded in the unit's text, no answer given away, one right MC option, blanks present...) and, on the model path, the reviewer model too. Rejected items go back to the generator with the reviewer's reason; only the missing items are regenerated. If a model call fails, the package falls back to the no-AI generator (noted in the package's `review.notes`).

> Gotcha already handled: a node that calls `interrupt()` re-runs from the top when it resumes. That's why the DB inserts live in `save_package` / `save_draft`, the nodes before the interrupts, and publishing happens only after the decision.

## Endpoints (`/agents/games`)

| Endpoint | Who | What |
|---|---|---|
| `POST /unit-package` | teacher | `{class_id, unit, lesson_date, due_date?, title?, tutor_mode="hints_only", tutor_reveal_after=2, mastery_threshold=0.8, mc_count=4, explain_count=2, card_count=10, offline=false}` → `{status:"waiting_for_approval", thread_id, approval_groups, package_id, summary:{flashcards, matching, fill_in, mc, explain, generated_by}}`. 404 unknown class, 409 no filed text in the unit or too few terms (< 4), 422 bad settings. `due_date` (YYYY-MM-DD or ISO) defaults to the day before the lesson, `T23:59:00.000Z`. `mastery_threshold` also accepts a percent (80). |
| `GET /unit-package/{package_id}` | teacher | `{package_id, class_id, unit, status, settings, generated_by, activities:[{activity_id, kind, title, items}], questions:[{text, kind, options?:[{text, correct}], answer?, rubric?, source}], assignment_id, review, created_at}`. Items and questions also carry `source` (file title, or the model's quote). |
| `PATCH /unit-package/{package_id}` | teacher | Edit a **draft** before approving (`editing.py`). Body (all optional): `questions` (the full list, GET's shape: `{text, kind:"choice", options:[{text, correct}]}` or `{text, kind:"explain", answer, rubric}`), `activities:[{activity_id, items:[...]}]` (a game's full item list in the contract shapes; an `item_id` the game already has is kept with its `source`, anything else gets a fresh never-used id like `fc11`), `settings:{title, lesson_date, due_date, due_day, tutor_mode, tutor_reveal_after, mastery_threshold}` (a new lesson date without a due date moves the due date to its default). Hard rules → **422** with one readable message: question text; MC ≥ 2 options, none empty, exactly one right; explain has a model answer; fill-in sentence has `____` (3+ underscores are normalized); ≥ 1 question; ≥ 4 practice cards across the games; due ≤ lesson. **409** if not a draft, 404 unknown package. → `{package, warnings:[{target:"question"\|"item"\|"activity", index?, activity_id?, item_id?, label, note}]}`: `check_draft` on the result plus duplicate terms/questions and emptied games, also kept in `review.edit_warnings`. The pending approval's description is refreshed. |
| `POST /unit-package/{package_id}/regenerate` | teacher | `{kind:"question", index}` or `{kind:"item", activity_id, item_id}` (+ `offline?`) → replaces that one with a new one of the same kind and returns `{package, warnings, replaced, generated_by, note}`. Model path (one generator call) when keys are set and the package wasn't drafted offline; on any model error or without keys, the next unused candidate from `extract.candidate_pool` (deterministic; skips current items and everything replaced before, kept in `review.replaced`). **409** with a friendly message when none is left or the package isn't a draft. Items keep their `item_id`. |
| approval `publish_unit_package` | teacher | args `{class_id, package_id}`. Approve: `assignments` row (`mode='checkin'`, unit, lesson date, tutor settings, threshold, due date, `max_points=10`, type `Homework`), questions (MC = `multiple_choice` + options, `correct_answer` = the right option id as text, like `backend/routes/classes.ts`; explain = `short_answer` with the model answer as the single `is_correct` option and `explain_rubric`), points split evenly to 10, activities and package → `published` with `assignment_id`, and a published `calendar_events` row `"<title> due"` (kind `assignment_due`, source `unit package`) **only if** the due date is a weekday and, when the class has a term, inside it, not a holiday and under the per-day limit. Otherwise the run output says why it was skipped. Reject: package and activities → `rejected`. |
| `GET /practice/{assignment_id}` | student (Bearer JWT) | `{assignment:{assignment_id, title, unit, lesson_date, due_date}, activities:[{activity_id, kind, title, items}], progress:{"<activity_id>:<item_id>":{times_seen, times_correct, last_correct, box}}, stats, replay_gap}`. Items carry only the contract fields (no sources or review notes). |
| `POST /practice/{assignment_id}/answer` | student | `{activity_id, item_id, correct}` → `record_practice_answer(...)`: stats + `points_awarded, multiplier, level_up, just_unlocked`. 400 unknown card, 401 no/bad token, 403 not enrolled or past due, 404 not a check-in. |
| `POST /run` `{class_id, topic, kind}` | teacher | legacy single activity with the real models (503 without keys) |
| `POST /demo?class_id=1` | teacher | legacy offline demo: canned items, keyword reviewer, real graph + approval |
| `GET /activities?class_id=1[&status=published]` | teacher | all activities (legacy and package ones) |

**Item shapes** (every item has a stable `item_id`: `fc1..`, `m1..`, `f1..`): flashcards `{item_id, front, back}`, matching `{item_id, term, definition}` (made from the reviewed flashcards with the shortest definitions, up to 8), fill_in `{item_id, sentence (with ____), answer, alternates}`.

## How the no-AI generator finds terms (`extract.py`)

Per sentence, after stripping bullets, numbering and `**bold**`:

| Pattern | Example |
|---|---|
| glossary line (`:`, ` - `, ` – `) | `Hypotonic solution: cell gains water and swells.` |
| table row (header names the columns) | `\| Lipids \| fatty acids and glycerol \| long-term energy \|` |
| `X is/are/means ...` | `Respiration is how cells release energy stored in glucose.` |
| `X <defining verb> ...` (short subject that agrees with the verb) | `Ribosomes build proteins.` / `Nucleus stores DNA and controls the cell.` |
| parentheses | `..., osmosis (water moving across a membrane), ...` |
| slide heading + next line | `The Calvin cycle` / `Happens in the stroma.` |

Quizzes, tests, rubrics, syllabi and schedules are skipped; worksheets and labs only fill in when notes and readings run out. Labels (`Day 1:`, `Analysis:`), questions and blanks are ignored. Terms are deduped, then picked best-pattern first, taking turns between files. Fill-ins blank the term in its own sentence when possible (else `____: definition`), with alternates for irregular plurals and partial answers (`mitochondrion`, `nuclei`, `hypotonic`, `Krebs`). MC = "Which term matches this description?" with 2-3 distractors from the unit's other terms. Explain questions come from sentences with a reason (`because`, `, so`, `which is why`, `This is why`, `which lets`, `X uses Y to Z`), then contrast pairs (`hypotonic / hypertonic`, `prokaryotes / eukaryotes`), then `X: explain what it does and why it matters`. The rubric is always the source sentence(s).

## Files you own
`agents/app/agents/games/*` (`agent.py` graph, `extract.py` no-AI generator, `models.py` model calls, `package.py` checks/save/publish, `editing.py` draft edits + regenerate, `router.py`), `agents/tests/test_unit_package.py`, `agents/tests/test_package_editing.py`, `agents/tests/test_practice_api.py`, `frontend/components/agents/GamesPanel.tsx`, plus the student game player.

## Done when
- [x] real generator and reviewer with structured outputs (`models.py`), with a no-AI fallback
- [x] unit package: games + check-in questions, one approval, publish creates the assignment and calendar event
- [x] student practice endpoints (games progress, points, mastery gate)
- [ ] measured item error rate **with vs without** the reviewer (LangSmith dataset + evaluator)
- [ ] students can play published games from the assignment page (frontend)
