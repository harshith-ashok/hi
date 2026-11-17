"""What a run is allowed to do, and the live state of the run that is happening on this thread.

An interactive turn has no policy: the user is watching and the usual confirmation gates apply. A background
run (a schedule, a heartbeat, a dropped file) uses `UNATTENDED`: reads are free, and any other tool call is
turned into a proposal for the user to approve later (see hi/agents/guard.py). `run_scope` makes a policy the
current one for the code that runs inside it, including the tools the agent calls on worker threads.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from collections.abc import Iterable, Iterator


@dataclass(frozen=True)
class RunPolicy:
    name: str
    interactive: bool = True
    allowed: frozenset[str] = frozenset()  # tools beyond the read-only ones that may run without approval
    max_tool_calls: int = 0  # 0 = no limit
    timeout_s: float = 0.0  # 0 = no limit
    allow_web: bool = True
    allow_screen: bool = False

    def with_allowed(self, tools: Iterable[str] = ()) -> "RunPolicy":
        return replace(self, allowed=self.allowed | frozenset(tools))

# Where a turn came from. Background origins are runs nobody asked for in the moment: they never join the chat
# history and never teach the assistant about you (a prompt written by a schedule is not something you said).
CHAT_ORIGINS = frozenset({"ui", "island", "voice"})
BACKGROUND_ORIGINS = frozenset({"schedule", "heartbeat", "drop"})
ORIGINS = CHAT_ORIGINS | BACKGROUND_ORIGINS

INTERACTIVE = RunPolicy("interactive")
UNATTENDED = RunPolicy(
    "unattended", interactive=False, allowed=frozenset({"write_report"}), max_tool_calls=15, timeout_s=300.0,
)


@dataclass
class RunState:
    """One run in progress: its policy, how many tools it has called, and the proposals it created."""
    policy: RunPolicy
    origin: str = ""
    persona: str = ""
    tool_calls: int = 0
    proposals: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # things to show in the run log, e.g. "screen left out"


_current: contextvars.ContextVar[RunState | None] = contextvars.ContextVar("hi_run_state", default=None)


def current() -> RunState | None:
    return _current.get()


def is_unattended() -> bool:
    state = _current.get()
    return state is not None and not state.policy.interactive


@contextmanager
def run_scope(policy: RunPolicy, origin: str = "") -> Iterator[RunState]:
    state = RunState(policy, origin)
    token = _current.set(state)
    try:
        yield state
    finally:
        _current.reset(token)


_pre_approved: contextvars.ContextVar[bool] = contextvars.ContextVar("hi_pre_approved", default=False)


def is_pre_approved() -> bool:
    """True while running something the user already approved with its exact arguments in front of them."""
    return _pre_approved.get()


@contextmanager
def pre_approved() -> Iterator[None]:
    """Inside this scope `confirm_destructive` says yes: the user approved this very action (a proposal), so the
    tool must not ask a second time and wait for an answer nobody will give."""
    token = _pre_approved.set(True)
    try:
        yield
    finally:
        _pre_approved.reset(token)
