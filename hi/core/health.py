"""Which outside dependencies (Ollama, the Mac bridge, the sandbox, ...) are working right now.

A dependency that fails is marked down for a cooldown, so callers skip it instead of timing out
on every turn (a small circuit breaker). `snapshot()` is what GET /health serves.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

DEFAULT_COOLDOWN_S = 30.0


@dataclass
class _State:
    ok: bool = True
    error: str = ""
    since: float = 0.0
    retry_at: float = 0.0


_states: dict[str, _State] = {}
_lock = threading.Lock()


def mark_ok(dep: str) -> None:
    with _lock:
        _states[dep] = _State(ok=True, since=time.time())


def mark_down(dep: str, error: Exception | str, cooldown_s: float = DEFAULT_COOLDOWN_S) -> None:
    now = time.time()
    message = str(error) or type(error).__name__
    with _lock:
        _states[dep] = _State(ok=False, error=message, since=now, retry_at=now + cooldown_s)


def is_up(dep: str) -> bool:
    """False only while `dep` is marked down and its cooldown has not passed. Unknown means up."""
    with _lock:
        state = _states.get(dep)
    return state is None or state.ok or time.time() >= state.retry_at


def snapshot() -> dict[str, dict]:
    with _lock:
        items = list(_states.items())
    return {
        dep: {"ok": state.ok, "error": state.error, "since": state.since}
        for dep, state in sorted(items)
    }


def reset() -> None:
    with _lock:
        _states.clear()
