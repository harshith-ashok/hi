"""Unified interrupt/cancellation (`BLOCKERS.md` → "Ambient & real-time
gaps" #3): one shared interrupt key and one shared check, instead of
three different (or missing) mechanisms. Before this: Ctrl-J only worked
while waiting on a shell command — its own private copy of exactly this
raw-terminal cbreak-mode check, local to
`hi/agents/term/shell_pane.py`; there was no way to cancel a
mid-generation LLM stream at all (`hi/streaming.py`'s `stream_and_print`
had no cancellation hook); and TTS doesn't exist yet in the terminal to
interrupt (that's Phase 11 — this primitive is what it will reuse, not
duplicate again).

`check_interrupt()` below is `shell_pane.py`'s original
`_check_interrupt` verbatim, generalized to a shared module rather than
reimplemented — that function was already proven live (Ctrl-J correctly
distinguished from Enter at the raw byte level, correctly falls back to
a plain sleep when stdin isn't a real TTY). `Throttle`/`CancellationToken`
are new: `stream_and_print` polls far more often (once per streamed
chunk, potentially dozens of times a second) than the shell-wait loop's
original ~0.2s cadence, and reconfiguring terminal modes on every single
token would be wasteful and risks visible disruption — `Throttle` caps
the actual raw-terminal check to that same proven-safe cadence,
regardless of how often the caller polls.
"""

from __future__ import annotations

import select
import sys
import termios
import time
import tty

# Same key the original shell-wait interrupt already used — distinct
# from Enter (\r) at the raw byte level.
INTERRUPT_KEY = "\x0a"

# The cadence hi/agents/term/shell_pane.py's original wait loop already
# used safely, live-tested, before this module existed.
DEFAULT_POLL_INTERVAL = 0.2


def check_interrupt(timeout: float) -> bool:
    """Waits up to `timeout` seconds for the interrupt key, returning
    True if it was pressed during that window. Needs the terminal in
    cbreak mode to see a single keystroke without waiting for Enter —
    set and restored every call, so a plain sleep (no real TTY, e.g. any
    non-interactive invocation) is the exact fallback, and terminal
    settings are never left altered regardless of whether this fires."""
    if not sys.stdin.isatty():
        time.sleep(timeout)
        return False

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if ready:
            return sys.stdin.read(1) == INTERRUPT_KEY
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return False


class Throttle:
    """Caps how often an expensive periodic check actually runs, so a
    tight loop can poll every iteration without the check itself firing
    that often."""

    def __init__(self, interval: float = DEFAULT_POLL_INTERVAL):
        self.interval = interval
        self._last = 0.0

    def ready(self) -> bool:
        now = time.monotonic()
        if now - self._last >= self.interval:
            self._last = now
            return True
        return False


class CancellationToken:
    """Set once the interrupt key is detected; checked by whichever of
    shell-wait / generation-streaming / (later) TTS playback is
    currently running. One flag, one meaning, regardless of what's in
    flight — callers should treat `cancelled` as sticky for the
    remainder of that one operation, not re-checked from scratch."""

    def __init__(self) -> None:
        self.cancelled = False

    def poll(self, throttle: Throttle) -> bool:
        """Call from inside a tight loop — only actually touches stdin
        when `throttle` says it's time to; otherwise returns the
        already-known state immediately, at effectively zero cost.
        Returns the (possibly newly-updated) cancelled state."""
        if not self.cancelled and throttle.ready() and check_interrupt(0):
            self.cancelled = True
        return self.cancelled
