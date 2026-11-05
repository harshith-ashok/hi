"""Constructs `ChatOllama` instances with automatic `thinking`/reasoning
support (`BLOCKERS.md` -> "Suggested feature improvements" D, TODO.md
Phase 14): Ollama's reasoning-capable models (gpt-oss, nemotron-3, ...)
stream a separate `thinking` field that `langchain_ollama` only surfaces
if `reasoning=True` is passed — but that kwarg fails outright on a model
that doesn't support thinking at all (confirmed by reading the sibling
`sage/backend` project's own `app/router.py`, which found and fixed the
exact same gap against the exact same underlying Ollama models earlier
in this build), so it can't be one fixed setting for every model.

Probed once per model name with a real, cheap "Hi" call — not assumed —
and cached, so every later construction of an already-probed model is
instant. Live-verified against `gpt-oss:20b-cloud` (HAIKU_MODEL):
`reasoning=True` genuinely streams `chunk.additional_kwargs
["reasoning_content"]` chunks alongside the normal `chunk.content`, both
during a real `.stream()` call.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_core.language_models import BaseChatModel

from hi import llm

_PROBE_MESSAGE = [HumanMessage("Hi")]
_NOT_SUPPORTED_MARKER = "does not support thinking"

# model_name -> whether reasoning=True actually works for it. Only ever
# populated with a definite answer (a real success, or the specific
# "does not support thinking" failure) — a different, unrelated failure
# (a network hiccup, a transient 5xx) is never cached, so a later call
# gets a fresh chance to probe again instead of being stuck on a false
# negative forever.
_reasoning_supported: dict[str, bool] = {}

# Persisted across runs: whether a model supports thinking doesn't change,
# so a fresh process shouldn't pay a blocking network call per model just
# to rediscover it at import time.
_CACHE_PATH = Path.home() / ".hi" / "reasoning_support.json"


def _load_cache() -> None:
    try:
        _reasoning_supported.update(json.loads(_CACHE_PATH.read_text()))
    except (OSError, ValueError):
        pass


def _save_cache() -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(_reasoning_supported))
    except OSError:
        pass


_load_cache()


def make_chat_model(model_name: str, **kwargs) -> BaseChatModel:
    """Build a chat model for `model_name` on the active provider, with
    streamed reasoning enabled if (and only if) it actually works. OpenRouter
    ignores reasoning on models that lack it, so only Ollama needs a probe.
    `**kwargs` are passed through as-is (e.g. temperature, keep_alive)."""
    if llm.is_openrouter():
        return llm.build_chat_model(model_name, thinking=True, **kwargs)

    supported = _reasoning_supported.get(model_name)
    if supported is None:
        supported = _probe_reasoning_support(model_name, kwargs)
    return llm.build_chat_model(model_name, thinking=supported, **kwargs)


def _probe_reasoning_support(model_name: str, kwargs: dict) -> bool:
    probe = llm.build_chat_model(model_name, thinking=True, **kwargs)
    try:
        probe.invoke(_PROBE_MESSAGE)
    except Exception as e:
        if _NOT_SUPPORTED_MARKER in str(e).lower():
            _reasoning_supported[model_name] = False
            _save_cache()
        return False
    _reasoning_supported[model_name] = True
    _save_cache()
    return True
