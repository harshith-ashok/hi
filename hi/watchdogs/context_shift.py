"""State-change watchdog (`BLOCKERS.md` -> "Ambient & real-time gaps" #2):
`hi` had no way to notice anything changing on its own, at all — every
perception tool is strictly one-shot and explicitly asked for. This adds
*state-change* detection only (app switched, or the same app has stayed
frontmost for a long time) — never content, never OCR, never a screenshot.
Built entirely on `hi/perception/privacy.py`'s existing
`frontmost_app_name()`, already proven correct (it's what
`sensitive_context_reason()` already calls reactively before every
perception-tool read) — this just polls it on an interval instead.

Two functions, two different call sites, deliberately:

- `poll_once()` is meant to be called often (every 30-60s, per
  `BLOCKERS.md`) — cheap (one AppleScript call), just updates persisted
  dwell-tracking state. No notification, no Suggestion, no side effect
  beyond that.
- `dwell_suggestion()` is a pure read of that persisted state, called by
  `hi/suggest/engine.py`'s `gather_suggestions()` at its own (coarser,
  ~30 min) cadence — the *only* place a state change actually becomes a
  user-visible `Suggestion`, going through that module's existing
  confidence-gate and per-day dedup rather than a parallel notification
  path of its own.

Splitting it this way is what lets `run_suggest_daemon()` poll this
tightly without also re-notifying every 30-60s — see its own poll loop
in engine.py.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from hi.perception.privacy import frontmost_app_name

STATE_PATH = Path.home() / ".hi" / "context_shift_state.json"

POLL_INTERVAL_SECONDS = 45  # within BLOCKERS.md's 30-60s window
DWELL_THRESHOLD_SECONDS = 20 * 60  # "gone idle N minutes" — 20min is a reasonable default


@dataclass
class _State:
    app: str | None
    since: float  # epoch seconds this app first became (continuously) frontmost


def _load_state() -> _State | None:
    if not STATE_PATH.exists():
        return None
    try:
        data = json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return _State(app=data.get("app"), since=data.get("since", 0.0))


def _save_state(state: _State) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"app": state.app, "since": state.since}))


def poll_once() -> None:
    """Check the frontmost app once and update persisted dwell-tracking
    state if it changed. State-change detection only — never reads
    content, never takes a screenshot. Safe (and intended) to call on a
    tight interval."""
    app = frontmost_app_name()
    state = _load_state()
    if state is None or state.app != app:
        _save_state(_State(app=app, since=time.time()))


def dwell_suggestion(threshold_seconds: int = DWELL_THRESHOLD_SECONDS) -> tuple[str, int] | None:
    """Returns (app_name, minutes) if poll_once()'s persisted state shows
    the current frontmost app has stayed frontmost, continuously, for at
    least `threshold_seconds` — else None. A pure read with no side
    effects; hi/suggest/engine.py is what turns this into an actual,
    gated Suggestion."""
    state = _load_state()
    if state is None or state.app is None:
        return None
    dwell = time.time() - state.since
    if dwell < threshold_seconds:
        return None
    return state.app, int(dwell // 60)
