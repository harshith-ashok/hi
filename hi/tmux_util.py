"""Shared helper for launching tmux layouts.

Chooses `new-window` when already inside tmux and `new-session` otherwise,
so callers never need to duplicate that detection logic.
"""

import os
import subprocess


def tmux_new_target() -> str:
    """'new-window' if already inside tmux, else 'new-session'."""
    return "new-window" if os.environ.get("TMUX") else "new-session"


def run_tmux_raw(args: list[str]) -> subprocess.CompletedProcess:
    """Run `tmux <args>` and return the completed process, stdout/stderr captured."""
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def run_tmux(args: list[str]) -> str | None:
    """Run `tmux (new-window|new-session) <args>`.

    Returns an error string on failure, or None on success.
    """
    result = run_tmux_raw([tmux_new_target(), *args])
    if result.returncode != 0:
        return result.stderr.strip() or f"tmux exited with status {result.returncode}"
    return None


def keep_alive(command: str) -> str:
    """Append a fallback to drop into an interactive shell once `command`
    finishes, instead of tmux closing the pane (and the window/session, if
    it's the last pane) the moment a short-lived command exits — a command
    that fails fast (wrong directory, missing dependency, typo) would
    otherwise vanish along with its own error output before anyone can see
    it. Verified live: `npm run dev` run from a directory with no
    package.json fails and closes its pane in under a second without this."""
    return f"{command}; exec $SHELL -l"
