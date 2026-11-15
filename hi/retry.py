"""One retry policy for every agent: a failed model call is re-attempted up to
MAX_ATTEMPTS times (with backoff) before the error surfaces. Orchestrated tasks
(hi/orchestrator/graph.py) use the same limit for whole-task re-attempts.

Tool calls are deliberately not retried here: a tool that raised may already have
half-done something (a push, a deleted file), and repeating it blindly is worse
than letting the model see the error and choose.
"""

from __future__ import annotations

from langchain.agents.middleware import ModelRetryMiddleware

MAX_ATTEMPTS = 5


def retry_middleware() -> ModelRetryMiddleware:
    return ModelRetryMiddleware(max_retries=MAX_ATTEMPTS, initial_delay=1.0, backoff_factor=2.0, max_delay=15.0)
