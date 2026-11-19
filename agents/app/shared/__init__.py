"""Shared building blocks every agent uses.  Agents talk to each other ONLY through these:

- settings    paths, env vars, config.yaml
- db          the shared SQLite file (same one the Express app uses)
- llm         get_model(agent, role) -> a LangChain chat model from config.yaml
- library     search / get_file / list_files over the teacher's filed documents
- approvals   the Approvals inbox (create, list, decide)
- hitl        run an agent and turn HumanInTheLoopMiddleware pauses into inbox items
- guardrails  hard-blocked actions + reusable deterministic checks
- tracing     one LangSmith project per agent
"""
