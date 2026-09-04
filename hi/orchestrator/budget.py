"""A user-settable quick/thorough budget for orchestrated runs (TODO.md
Phase 20). "thorough" is today's existing behavior, unchanged, and stays
the default — "quick" trades plan depth for speed: fewer tasks, and a
cheaper default tier suggested to the planner for the tasks it does
create.

A plain module-level global, not per-session state threaded through
every call: there's exactly one interactive REPL process at a time, and
this mirrors the same "single mutable process-wide setting" shape
`hi/models.py`'s own model cache already uses. Set it from the REPL with
"budget quick" / "budget thorough" (see `hi/repl.py`); check the current
value with the bare word "budget".
"""

from __future__ import annotations

_MAX_TASKS = {"quick": 3, "thorough": 6}
_DEFAULT_TIER = {"quick": "haiku", "thorough": "sonnet"}

_budget = "thorough"


def set_budget(value: str) -> bool:
    """Sets the active budget. Returns whether `value` was recognized —
    an unrecognized value is left unchanged rather than silently
    defaulting, so a typo doesn't quietly reset it to something the
    user didn't ask for."""
    global _budget
    normalized = value.strip().lower()
    if normalized not in _MAX_TASKS:
        return False
    _budget = normalized
    return True


def get_budget() -> str:
    return _budget


def max_tasks() -> int:
    return _MAX_TASKS[_budget]


def default_tier() -> str:
    return _DEFAULT_TIER[_budget]
