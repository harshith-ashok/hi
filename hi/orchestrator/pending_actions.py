"""Pending-approval queue for destructive actions (TODO.md Phase 17):
`hi/action_tiers.py`'s `confirm_destructive()` (and the shell-command
confirm path it now shares) blocks on a synchronous `input()` call in
whatever terminal happens to be running it — meaningless for an
orchestrated subagent (TODO.md Phase 16) with no human watching that
specific pane, and the REPL's own terminal is itself synchronously
blocked waiting on the whole DAG at that moment, so it can't `input()`
there either.

`is_orchestrated_context()` is how `confirm_destructive()` tells the two
situations apart: `hi/orchestrator/graph.py`'s node function marks
itself active for the duration of each subagent call, so a destructive
tool invoked from inside that call routes here instead of `input()`
automatically — no caller has to know or care which situation it's in.
Uses a plain module-level counter (not `contextvars`, whose propagation
into a tool's worker thread isn't guaranteed) — correctness only
requires knowing "is *some* orchestrated subagent currently running",
not which one, since `hi`'s actual usage is one user driving one thing
at a time; the REPL's own blocking `asyncio.run()` call already rules
out a normal interactive tool call happening concurrently with an
orchestrated run in the same process.

`wait_for_approval()` uses a plain `threading.Event`, not
`asyncio.Event` — it needs to work correctly whether called from the
event loop's own thread or a tool's worker thread (LangChain runs a
sync tool's `_run()` via a thread-pool executor when invoked from an
async agent), and `threading.Event` is safe either way.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from uuid import uuid4

DEFAULT_TIMEOUT_SECONDS = 300.0  # an unattended run shouldn't hang forever
REMINDER_INTERVAL_SECONDS = 30.0  # how often the waiting side prints a fresh reminder

_lock = threading.Lock()
_pending: dict[str, "PendingAction"] = {}
_active_orchestrated_count = 0

# TODO.md Phase 20 ("approvals as generative UI"): the resolved value for
# every action ever resolved this process, decoupled from `_pending`'s own
# pop timing below. `wait_for_approval()`'s thread only pops an entry from
# `_pending` sometime after it wakes up from `resolve()`'s `_event.set()`
# — a separate poller (`hi/agui_adapter.py`'s `stream_orchestrated_as_agui()`,
# checking once per DAGEvent-queue tick) could easily race that pop and
# see neither "still pending" nor a resolution. Kept here instead, written
# the moment `resolve()` runs, so `resolution_of()` below is a reliable
# answer regardless of how fast the original waiter's thread gets
# scheduled. Small and unbounded only in the sense that this process
# doesn't run forever between restarts — the same trade-off `_pending`
# itself already makes.
_resolved: dict[str, bool] = {}


@dataclass
class PendingAction:
    id: str
    description: str
    created_at: float
    approved: bool | None = None
    _event: threading.Event = field(default_factory=threading.Event, repr=False)


def mark_orchestrated_active() -> None:
    """Called by graph.py right before invoking a subagent."""
    global _active_orchestrated_count
    with _lock:
        _active_orchestrated_count += 1


def mark_orchestrated_done() -> None:
    """Called by graph.py right after a subagent call returns (success
    or failure alike — always paired with mark_orchestrated_active() in
    a try/finally, so a crashed subagent can't leave the counter stuck
    above zero forever)."""
    global _active_orchestrated_count
    with _lock:
        _active_orchestrated_count = max(0, _active_orchestrated_count - 1)


def is_orchestrated_context() -> bool:
    with _lock:
        return _active_orchestrated_count > 0


def list_pending() -> list[PendingAction]:
    with _lock:
        return [a for a in _pending.values() if a.approved is None]


def resolve(action_id: str, approved: bool) -> bool:
    """Called by `POST /pending/{id}/approve|deny`. Returns False if
    `action_id` doesn't exist — already resolved (including timed out),
    or never existed."""
    with _lock:
        action = _pending.get(action_id)
        if action is None or action.approved is not None:
            return False
        action.approved = approved
        _resolved[action_id] = approved
    action._event.set()
    return True


def resolution_of(action_id: str) -> bool | None:
    """True/False if `action_id` has been resolved (approve/deny),
    else None (still pending, timed out, or never existed — a poller
    can't tell those apart from this alone, which is fine: it only
    needs to know whether ITS OWN earlier-seen pending action got a
    real answer)."""
    with _lock:
        return _resolved.get(action_id)


def wait_for_approval(
    description: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    reminder_interval: float = REMINDER_INTERVAL_SECONDS,
) -> bool:
    """Enqueues a pending action and blocks — thread-safe, works from
    either the event loop's own thread or a tool's worker thread —
    until a human resolves it via `resolve()`, or `timeout` elapses.
    Denies on timeout rather than hanging forever or silently
    proceeding — an unattended run should fail safe.

    Prints a periodic reminder with the exact `curl` commands to
    resolve it: the REPL's own terminal is synchronously blocked
    waiting on the whole orchestrated run at this point (that's the
    actual reason this queue exists), so it can't accept a plain "y"
    typed into the same prompt — the visible reminder is what makes
    this a real, usable indicator instead of a silent hang, per this
    phase's own requirement.
    """
    action = PendingAction(id=uuid4().hex[:8], description=description, created_at=time.time())
    with _lock:
        _pending[action.id] = action

    # Port 8766, not the voice companion's 8765 — wait_for_approval() is
    # only ever reached from inside the terminal REPL process (the only
    # place an orchestrated run currently happens), which is exactly
    # the process hi/orchestrator/pending_server.py's dedicated server
    # runs in — see that module's docstring for why the two are separate.
    print(f"\n[pending approval] {description}")
    print(f"  id: {action.id}")
    print(f"  approve: curl -X POST http://127.0.0.1:8766/pending/{action.id}/approve")
    print(f"  deny:    curl -X POST http://127.0.0.1:8766/pending/{action.id}/deny")

    elapsed = 0.0
    while elapsed < timeout:
        got_response = action._event.wait(min(reminder_interval, timeout - elapsed))
        if got_response:
            break
        elapsed += reminder_interval
        print(f"[pending approval] still waiting on {action.id} ({int(elapsed)}s) — {description}")

    with _lock:
        _pending.pop(action.id, None)

    if not action._event.is_set():
        print(f"[pending approval] {action.id} timed out after {timeout:.0f}s — denying.")
        with _lock:
            _resolved[action.id] = False
        return False
    return bool(action.approved)
