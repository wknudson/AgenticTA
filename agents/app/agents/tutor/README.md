# Tutor upgrade: owner Will

**What it does:** moves the student tutor from Express (`POST /api/ai/chat`) to this service. It gets real retrieval from the library, scoped to the assignment's unit, instead of stuffing the whole PDF summary into the prompt.

**Kind of system:** a conversational agent with **read-only** tools. It's the deliberate contrast with the other agents: an agent that is *not allowed to act*.

**Controls:**
- the existing deterministic answer-blocker (Dice similarity ≥ 0.72, `backend/routes/ai.ts`), ported as middleware
- `PIIMiddleware`
- `ModelCallLimitMiddleware`

This is part 2 of the two-part student assignment: the assessment with a tutor that gives hints but never answers.

See the TODO list in `router.py`.

## Done when
- [ ] a test set shows it still refuses assignment questions and answers concept questions
- [ ] answers cite library chunks
- [ ] chats still land in `student_chat_messages` (the misconception finder reads them)
