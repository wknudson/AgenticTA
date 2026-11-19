# Materials update: owner Teammate C

**What it does:** turns one teacher instruction ("push Unit 3 back a week; add a section on X") into every file and assignment change it requires.

**Kind of system:** planner + workers. Pattern: hierarchical task decomposition.

**Models:** `claude-sonnet-5-5` plans; `gpt-6-luna` (cheap) edits each file. The skeleton has the planner do everything. Splitting the work out to workers is your main task, and the cost and latency difference is your evaluation story.

**Controls:**
- `HumanInTheLoopMiddleware` on `apply_revision` (approve/reject) and `update_assignment` (approve/edit/reject)
- `TodoListMiddleware` makes the plan visible
- `SummarizationMiddleware` handles long documents
- `ModelCallLimitMiddleware`
- Revisions are **new versions**; originals are archived, never overwritten. Points and grades are out of scope.

## Files you own
`agents/app/agents/materials/*`, `frontend/components/agents/MaterialsPanel.tsx`

## Already working (skeleton)
- `POST /agents/materials/demo?class_id=1` (run the Filing demo first) drafts a revision, pauses, and on approval makes the draft current and archives the original
- `POST /agents/materials/run` with `{class_id, instruction}` is the real agent

## Done when
- [ ] one instruction produces correct multi-file changes
- [ ] a rejected diff never applies (test)
- [ ] the plan and the worker edits are visible as separate steps in LangSmith
- [ ] UI: instruction box, plan view, side-by-side diff per revision, `.docx` download of new versions
