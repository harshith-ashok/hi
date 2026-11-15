"""The model layer: providers (Ollama on this machine or over Tailscale), tier registry with
fallbacks, reasoning probe, and retry/warm-up helpers.

Callers use `from hi import llm` for provider helpers (`llm.list_models`, `llm.ollama_host`, ...)
and import `hi.llm.registry` / `hi.llm.resilience` / `hi.llm.reasoning` for the rest.
"""

from hi.llm.providers import (  # noqa: F401
    OLLAMA_PORT,
    build_chat_model,
    describe,
    ensure_available,
    friendly_error,
    list_models,
    model_name,
    normalize_url,
    ollama_host,
    signature,
)
