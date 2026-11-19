"""One package per agent.  Each exposes `router` (mounted at /agents/<name>).

Folder layout (copy this when adding an agent, and add it to config.yaml):
    __init__.py   from .router import router
    router.py     HTTP endpoints for the agent's dashboard panel
    agent.py      build_agent(): create_agent(...) or a LangGraph StateGraph
    tools.py      @tool functions the agent can call
    prompts.py    system prompts
    schema.sql    tables this agent owns (CREATE TABLE IF NOT EXISTS ...)
    README.md     owner, scope, definition of done
"""
