# Agents service

FastAPI + LangChain v1 (`create_agent`, middleware) + LangGraph, traced in LangSmith. It shares one SQLite file with the Express app (`data/agenticta.sqlite`).

```
agents/
  config.yaml                 provider + model per agent role (change models here)
  app/main.py                 mounts every agent at /agents/<name>, plus /agents/health and /agents/approvals
  app/shared/                 the ONLY way agents talk to each other
    library.py                search / get_file / list_files over filed documents   (owner: Will)
    approvals.py              the Approvals inbox                                     (shared)
    hitl.py                   HitlRunner: run a graph, turn HITL pauses into inbox rows, resume on decision
    guardrails.py             hard blocks (grades, deletes, outbound messages) + deterministic checks + who approves what
    llm.py                    get_model(agent, role); pass script=[...] for an offline scripted model
    tracing.py                agent_trace(agent): one LangSmith project per agent
    db.py, schema.sql         shared tables (library, approvals, agent_runs)
  app/agents/<name>/          one folder per agent; each has its own README with owner, scope and "done when"
  tests/test_skeleton.py      every offline demo end to end + guardrails
```

## How the pieces differ (on purpose)

| Agent | Built with | Shows |
|---|---|---|
| filing | plain functions + `@traceable` | not everything needs an agent (Phase 1) |
| scheduler | `create_agent` + HITL middleware | LLM reasons, deterministic tools compute |
| materials | `create_agent` + TodoList / Summarization / HITL | planning vs execution, multi-model |
| games | hand-built `StateGraph` + `interrupt()` | graph engineering, independent reviewer |
| misconceptions | pipeline on a local model | privacy-driven model choice |
| tutor | `create_agent`, read-only tools | an agent that is deliberately not allowed to act |

## Rules every agent follows

1. **Anything students see, or any change to dates or points, goes through approval.** For `create_agent`, put the tool in `HumanInTheLoopMiddleware(interrupt_on=...)`. For a StateGraph, call `interrupt(hitl_request([...]))`. Either way, run it through `HitlRunner` and the Approvals tab handles the rest.
2. **No tool may change grades, delete anything or send anything outside the app.** `assert_safe_toolset` + `BlockedActionsMiddleware` enforce this.
3. **Read other agents' data only through `app/shared`.** Don't import another agent's package.
4. **Keep an offline demo working** (`/demo` with a scripted model or canned data), so anyone can click through without keys and the tests stay green.
5. **New tables go in your agent's `schema.sql`** (`CREATE TABLE IF NOT EXISTS`). They're applied on startup.

## Commands (from the repo root)

```bash
npm run dev:agents      # just this service, http://localhost:8000/docs
npm run test:agents     # pytest
```
