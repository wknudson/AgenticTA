# AgenticTA: Setup (Windows and Mac, VS Code)

Setup takes about 10 minutes the first time. You don't need any outside database or server; everything runs on your laptop.

## 1. Install once

| Tool | Why | Check |
|---|---|---|
| **VS Code** | editor; the repo ships a ready-made workspace | `code --version` |
| **Node.js 20+** | frontend + Express API | `node --version` |
| **Python 3.12+** | the agents service | `python --version` (Mac: `python3 --version`) |
| **uv** | installs and runs the Python side | `pip install uv` (Mac: `pip3 install uv` or `brew install uv`) |
| Ollama *(only for the misconception finder)* | local model | install from ollama.com, then `ollama pull phi3` |

## 2. Get the code and set up

```bash
git clone https://github.com/wknudson/AgenticTA.git
cd AgenticTA
npm run setup     # npm install, create every .env file, create the SQLite DB, install Python packages
```

## 3. Open it in VS Code

Open **`AgenticTA.code-workspace`**, not the folder. Use **File → Open Workspace from File…**, or run `code AgenticTA.code-workspace`. If you opened the folder instead, VS Code offers to open the workspace; click **Open Workspace**.

- **Extensions:** accept the "install recommended extensions" prompt (Python, Pylance, debugger, Ruff, .env highlighting, YAML/TOML, SQLite viewer).
- **Two folders:** the sidebar shows **AgenticTA** (everything, including the Node side) and **agents (Python)**. The second one is what lets VS Code use `agents/.venv` and run the tests from the right place.
- **Python interpreter:** VS Code should pick up `agents/.venv` on its own. If the status bar doesn't show it, press Ctrl/Cmd+Shift+P → **Python: Select Interpreter** → choose the one in `agents/.venv`.
- **Tests:** in the **Testing** sidebar (beaker icon), click the play button to run all Python tests, or run one test with its play icon.

| To… | Do this |
|---|---|
| Run everything | Ctrl/Cmd+Shift+B (the default build task, `npm run dev`) |
| Debug everything with breakpoints | Run and Debug → **Full stack (debug)** |
| Debug just your agent's API | Run and Debug → **Agents API** |
| Debug the Python tests | Run and Debug → **Agents tests** |
| Other jobs (set up, check .env files, reset DB, typecheck) | Ctrl/Cmd+Shift+P → **Tasks: Run Task** |
| Look inside the database | open `data/agenticta.sqlite` (SQLite viewer extension) |

## 4. Your .env files

There's one project file, plus one file per agent. `npm run setup` creates them all from their `.env.example` templates, and git ignores them, so keys never get committed.

| File | What goes in it |
|---|---|
| `.env` (project) | **LangSmith** key (shared team workspace), app settings, and the OpenAI key for the original Express AI features |
| `agents/app/agents/<agent>/.env` | **your agent's model keys**, and optionally a personal model override |

- **Where your keys go:** only fill in **your own agent's** file. Each template lists exactly the keys that agent's models need.
- **Fallback:** if an agent's key is blank, it falls back to the same key in the project `.env`. Putting one key there works for everyone.
- **Experiments:** you can try a different model without touching the shared `agents/config.yaml`. Put `MODEL_<ROLE>=provider:model` in your agent's `.env`, e.g. `MODEL_MAIN=anthropic:claude-sonnet-5-5`. To keep experiment traces separate, set `LANGSMITH_PROJECT=...` there too.
- **Check your keys:** `npm run env` (task: *env: create / check .env files*) shows which keys are set or missing in every file. It never prints the values.
- **After editing a `.env`,** restart the agents service.

For LangSmith, accept the invite to the team workspace, create an API key there, and put it in the **project** `.env`.

**Every agent has an offline demo that needs no key**, so you can start before you have any.

## 5. Run

`npm run dev` (or Ctrl/Cmd+Shift+B in VS Code). Open **http://localhost:5173**, log in as a teacher (`sarah_b` / `password123`), and pick a class. The agent tabs are on the right of the class tab bar: **Library, Scheduler, Update materials, Study games, Insights, Approvals**.

Try the whole loop without any API key:
1. **Library** → *File the sample course* (32 sample Biology files. Without a Gemini key they get rule-based labels, and the photos and scans wait in Needs review.)
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
| `npm run env` | create missing .env files and show which keys are blank |
| `npm run test:agents` | Python tests (offline demos, approvals, guardrails, env scoping) |
| `npm run typecheck` | TypeScript checks (one error in `AssignmentQuestionsEditorModal.tsx` predates the agents work) |
| `npm run db:reset` | delete the database, agent state and uploaded files, then recreate the seed data |
| `npm run db:seed-metrics` | optional: 6 more students + 8 weeks of grades for the metrics pages |
| `npm run setup:agents` | reinstall Python packages (run after pulling if `agents/pyproject.toml` changed) |
| `npm run eval:filing` | filing eval with real models on its own saved library: label accuracy + keyword vs meaning vs hybrid search. It reuses AI labels between runs to save free-tier quota (`-- --search-only` makes no labeling calls) |
| `npm run sample-course` | regenerate the sample Biology course files (already committed) |

## Accounts (seed data)

- Teachers: `sarah_b`, `james_ob`, `priya_s`, password `password123`
- Admin: `/admin`, `admin` / `adminMetrics!`
- Students get random passwords at first start. Teachers can see them under **Class Info**.

## Troubleshooting

- **"The agents service is not running"** in a panel: check the `agents` lines in the `npm run dev` output. Most often `uv` isn't installed, or `npm run setup` wasn't run.
- **`uv` not found on Windows** after `pip install uv`: that's fine, the npm scripts fall back to `python -m uv`.
- **A panel shows amber model badges:** that agent's key isn't set. Run `npm run env` to see which file needs it. The offline demo still works.
- **VS Code says "import could not be resolved"** in Python files: the interpreter isn't `agents/.venv`. Select it (section 3).
- **Breakpoints aren't hit in the agents:** start them with **Agents API** from Run and Debug, not `npm run dev`. The dev server reloads on save, and that detaches the debugger.
- **New Python code doesn't seem to take effect** (an endpoint gives 404, old behavior keeps happening): on Windows the agents service sometimes gets stuck mid-reload. The `agents` log says "Reloading…" but never "Application startup complete". Stop `npm run dev` (Ctrl+C) and start it again.
- **AI labels say "daily free-tier limit":** a free Gemini key allows only about 20 labeling requests per day. Use **Re-check with AI** in the Library once it resets, or enable billing on the key.
- **Weird data:** `npm run db:reset` (this wipes your local DB, including filed documents).
