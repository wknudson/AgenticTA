"""Which model the tutor and the judge use, and when they run without one.

The model is the tutor's "main" role in agents/config.yaml, or MODEL_MAIN=provider:model in
agents/app/agents/tutor/.env (e.g. MODEL_MAIN=google_genai:gemini-3.5-flash-lite).
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from app.shared.llm import get_model, model_spec
from app.shared.settings import agent_setting, has_provider_key

AGENT = "tutor"
MODEL_TIMEOUT_S = 30   # a slow or rate-limited model falls back to the no-AI path instead of hanging
MODEL_RETRIES = 1


def offline_mode() -> bool:
    """No-AI tutor and judge: AGENTICTA_TUTOR_OFFLINE=1 (environment or the tutor's .env), or no key
    for the configured model's provider."""
    if (agent_setting(AGENT, "AGENTICTA_TUTOR_OFFLINE") or "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    try:
        return not has_provider_key(AGENT, model_spec(AGENT)["provider"])
    except Exception:
        return True


def tutor_model() -> BaseChatModel:
    """The tutor's chat model, with a short timeout and one retry for the hosted providers."""
    kwargs = {}
    if model_spec(AGENT)["provider"] in ("openai", "anthropic", "google_genai"):
        kwargs = {"max_retries": MODEL_RETRIES, "timeout": MODEL_TIMEOUT_S}
    return get_model(AGENT, **kwargs)
