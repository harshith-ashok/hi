"""Shared helper for launching tmux layouts.

Chooses `new-window` when already inside tmux and `new-session` otherwise,
so callers never need to duplicate that detection logic.
"""

import os
import subprocess


def run_tmux(args: list[str]) -> str | None:
    """Run `tmux (new-window|new-session) <args>`.

    Returns an error string on failure, or None on success.
    """
    new_target = "new-window" if os.environ.get("TMUX") else "new-session"
    result = subprocess.run(
        ["tmux", new_target, *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return result.stderr.strip() or f"tmux exited with status {result.returncode}"
    return None
