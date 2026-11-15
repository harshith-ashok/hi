"""Single-instance lock for the menu bar app. No AppKit here, so the launcher and the suggestion engine can
ask "is it running?" without loading the UI libraries."""

from __future__ import annotations

import fcntl
from pathlib import Path

LOCK_PATH = Path.home() / ".hi" / "menubar.lock"
_held = None


def already_running() -> bool:
    """True if another menu bar app holds the lock. Taking it here keeps it for this process's lifetime."""
    global _held
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _held = open(LOCK_PATH, "w")
    try:
        fcntl.flock(_held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    return False


def lock_is_free() -> bool:
    """True when no menu bar app is running. Does not keep the lock."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True
