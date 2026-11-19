# Study games: owner Teammate D

**What it does:** builds Quizlet-style flashcards, matching and fill-in games from a unit's filed material. Students play them before the assessment, which is part 1 of the two-part student assignment.

**Kind of system:** generator + independent reviewer, as a **hand-built LangGraph StateGraph** (not `create_agent`). It's the team's example of graph engineering: fixed, auditable control flow.

**Models:** `gpt-6-luna` generates; `claude-sonnet-5-5` reviews. Using a different provider means the reviewer isn't grading its own work.

**Controls:** the reviewer node is a model-based guardrail (accuracy against the source, grade level). Rejected items are regenerated, with `MAX_ATTEMPTS` capping the retries. **Teacher approval before publishing** uses `interrupt()` in the `request_publish` node, and the Approvals tab handles it like any other approval.

> Gotcha already handled: a node that calls `interrupt()` re-runs from the top when it resumes. That's why the DB insert lives in `save_draft`, the node before it. Keep side effects out of interrupting nodes.

## Files you own
`agents/app/agents/games/*`, `frontend/components/agents/GamesPanel.tsx`, plus a new student game player component

## Already working (skeleton)
- `POST /agents/games/demo?class_id=1` (offline: canned items, keyword reviewer, real graph + approval)
- `POST /agents/games/run` with `{class_id, topic}` raises NotImplementedError until you add the model calls
- `GET /agents/games/activities?class_id=1[&status=published]`

## Done when
- [ ] real generator and reviewer with structured outputs
- [ ] measured item error rate **with vs without** the reviewer (LangSmith dataset + evaluator)
- [ ] students can play published games from the assignment page
