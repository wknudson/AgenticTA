# AgenticTA: Setup (Windows and Mac)

Setup takes about 10 minutes the first time. You don't need any outside database or server; everything runs on your laptop.

## 1. Install once

| Tool | Why | Check |
|---|---|---|
| **Node.js 20+** | frontend + Express API | `node --version` |
| **Python 3.12+** | the agents service | `python --version` (Mac: `python3 --version`) |
| **uv** | installs and runs the Python side | `pip install uv` (Mac: `pip3 install uv` or `brew install uv`) |
| Ollama *(only for the misconception finder)* | local model | install from ollama.com, then `ollama pull phi3` |

## 2. Get the code and set up

```bash
git clone https://github.com/wknudson/AgenticTA.git
cd AgenticTA
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env
npm run setup               # npm install + create the SQLite DB + install Python packages
```

Fill in `.env` with whatever API keys you have. **Every agent has an offline demo that needs no key**, so you can start right away. For LangSmith, accept the invite to the team workspace, create an API key there, and set `LANGSMITH_API_KEY`.

## 3. Run

```bash
npm run dev
```

Open **http://localhost:5173**, log in as a teacher (`sarah_b` / `password123`), and pick a class. The agent tabs are on the right of the class tab bar: **Library, Scheduler, Update materials, Study games, Insights, Approvals**.

Try the whole loop without any API key:
1. **Library** → *Run offline demo* (files a sample syllabus)
2. **Scheduler** → *Run offline demo* → it pauses for approval
3. **Approvals** → *Approve* → back on **Scheduler** the events are `published`

| Process | URL |
|---|---|
| Frontend (Vite) | http://localhost:5173 |
| Express API | http://localhost:3001 |
| Agents API + interactive docs | http://localhost:8000/docs |

## Useful commands

| Command | What it does |
|---|---|
| `npm run dev` | start all three processes |
| `npm run test:agents` | Python tests (offline demos, approvals, guardrails) |
| `npm run typecheck` | TypeScript checks (one error in `AssignmentQuestionsEditorModal.tsx` predates the agents work) |
| `npm run db:reset` | delete the database and recreate it from `backend/db/schema.sql` + `seed.sql` |
| `npm run db:seed-metrics` | optional: 6 more students + 8 weeks of grades for the metrics pages |

## Accounts (seed data)

- Teachers: `sarah_b`, `james_ob`, `priya_s`, password `password123`
- Admin: `/admin`, `admin` / `adminMetrics!`
- Students get random passwords at first start. Teachers can see them under **Class Info**.

## Troubleshooting

- **"The agents service is not running"** in a panel: check the `agents` lines in the `npm run dev` output. Most often `uv` isn't installed, or `npm run setup` wasn't run.
- **`uv` not found on Windows** after `pip install uv`: that's fine, the npm scripts fall back to `python -m uv`.
- **A panel shows amber model badges:** that agent's API key isn't in `.env`. The offline demo still works.
- **Weird data:** `npm run db:reset` (this wipes your local DB, including filed documents).
