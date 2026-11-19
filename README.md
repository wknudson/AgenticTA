# AgenticTA

AgenticTA is a teacher-focused LMS with AI agents. It started as **LyrningLMS**: AI-assisted assignment authoring, student assignment delivery, an AI tutor that won't hand out answers, and teacher/admin analytics. For the *AI and Agentic Systems* (Fall 2026) term project it adds a teacher dashboard of agents that work on the teacher's behalf, **with the teacher's approval**:

| Tab | What it does | Kind of system |
|---|---|---|
| **Library** | drop every file in one bucket; it's auto-labeled and searchable by meaning | Phase 1: fixed pipeline, not an agent |
| **Scheduler** | builds the student calendar from dates in documents and assignments | single agent + deterministic tools |
| **Update materials** | one instruction → every affected file and assignment, as reviewable diffs | planner + workers |
| **Study games** | flashcards and matching games from a unit's materials | generator + independent reviewer (LangGraph) |
| **Insights** | what students keep getting confused about (from tutor chats) | workflow on a local model (privacy) |
| **Approvals** | every consequential action waits here for the teacher | HITL inbox shared by all agents |

**Get started:** [SETUP.md](SETUP.md) · **Agents architecture:** [agents/README.md](agents/README.md) · **Team workflow:** [CONTRIBUTING.md](CONTRIBUTING.md)

## Tech stack

- **Frontend:** React + TypeScript + Vite (Tailwind)
- **API:** Node.js + Express + TypeScript
- **Agents:** Python, FastAPI, LangChain v1 (`create_agent` + middleware), LangGraph, LangSmith tracing
- **Database:** one local SQLite file (`data/agenticta.sqlite`) shared by Express and the agents, with `sqlite-vec` for vector search
- **Models:** OpenAI, Anthropic and Gemini APIs plus a local Ollama model, chosen per agent in `agents/config.yaml`

## Project structure

```text
backend/            Express API (routes/, db/schema.sql + seed.sql, ai/client.ts)
frontend/           React app; agent panels in components/agents/ (registry.tsx lists the tabs)
agents/             Python agents service (see agents/README.md)
scripts/            cross-platform dev/uv helpers used by npm scripts
data/               local SQLite DBs + uploaded files (gitignored)
```

## What was already implemented (LyrningLMS)

### Teacher flow

- Teacher login and class selection
- Create, edit, and delete classes
- Add existing students to a class, create new students in a class, and remove students from a class
- Create assignments with a due date, max points, allowed submission attempts, an attempt scoring policy (`latest`, `highest`, `average`) and AI tutor instructions
- Upload PDFs for assignment generation context
- AI-generated questions (multiple choice, true/false, short answer, select-all-that-apply)
- Teacher grades view and per-class / per-student metrics (weekly snapshots)

### Student flow

- Student login via shared assignment link; JWT-authenticated assignment access and submission
- Multi-attempt submissions, auto-grading, AI-assisted grading fallback for short answers
- AI tutor chat that refuses direct/near-verbatim assignment-question answering
- Per-attempt and aggregate scoring: points, percentage, letter grade, understanding, AI dependency, engagement

### Admin flow

- Dedicated admin login (`/admin`), read-only cross-class analytics with cascading filters (subject, semester, period, teacher)

## API surface (high level)

- `/api/auth`: teacher/student/admin login and student password management
- `/api/classes`: class CRUD, enrollment, assignment CRUD, grades, class metrics
- `/api/ai`: tutor chat, PDF text extraction, question generation, batch question updates
- `/api/student`: JWT-protected student assignment payload + submission
- `/api/admin`: JWT-protected read-only admin analytics
- `/agents/*`: the Python agents service (interactive docs at http://localhost:8000/docs)

## Data and grading notes

- Assignments support multiple attempts with configurable keep policy (`latest`, `highest`, `average`).
- Per-attempt results are stored in `student_assignment_attempt_grades`; aggregate grades in `student_grades`; weekly snapshots in `student_metrics`.
- Timestamps are stored as ISO-8601 UTC text.

## Known limitations

- The assignment PDF download endpoint intentionally returns 404 (`/api/classes/assignments/:assignmentId/pdf`).
- Some analytics values (for example engagement) use simplified scoring.
- `npm run typecheck` reports one existing error in `AssignmentQuestionsEditorModal.tsx`.
