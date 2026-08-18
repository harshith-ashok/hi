"""Runs commands visibly in the user's left-hand tmux pane (the one `hi`
never touches for any other persona) and captures their output, so `term`
can show the user real commands actually happening in their own shell
instead of running them invisibly in its own process.
"""

import os
import re
import time
import uuid

from hi.tmux_util import run_tmux_raw


def _own_pane_id() -> str:
    pane_id = os.environ.get("TMUX_PANE")
    if not pane_id:
        raise RuntimeError(
            "term needs to run inside a tmux pane with a sibling pane to "
            "control (launch it via `hi --term`, not directly)."
        )
    return pane_id


def _left_pane_id() -> str:
    own_pane = _own_pane_id()
    window = run_tmux_raw(
        ["display-message", "-p", "-t", own_pane, "#{window_id}"]
    ).stdout.strip()
    if not window:
        raise RuntimeError("Could not resolve the current tmux window.")

    panes = run_tmux_raw(["list-panes", "-t", window, "-F", "#{pane_id}"]).stdout.split()
    other_panes = [p for p in panes if p != own_pane]
    if not other_panes:
        raise RuntimeError(
            "No sibling pane found to run commands in — term needs the "
            "standard two-pane `hi` layout (left pane = your shell)."
        )
    return other_panes[0]


def _capture_pane_text(pane_id: str) -> str:
    return run_tmux_raw(["capture-pane", "-p", "-S", "-2000", "-t", pane_id]).stdout


def run_in_left_pane(command: str, timeout: float = 30.0) -> tuple[str, int | None]:
    """Run `command` in the left pane and return (output, exit_code).

    exit_code is None if the command didn't finish within `timeout` —
    the output returned in that case is just a note that it may still be
    running.
    """
    pane_id = _left_pane_id()

    # A start marker and an end marker (with the exit code) bracket the
    # command's real output. Sent as one atomic keystroke batch (not
    # separate send-keys calls) so the shell parses it as a single compound
    # command — separate calls race with the shell's own prompt redraw and
    # can interleave/garble the terminal before the first command finishes.
    # Line-count diffing (capture before, capture after, take the new
    # lines) doesn't work here: a long command wraps across pane-width
    # lines, which shifts line indices unpredictably. Marker strings found
    # by text position are immune to that.
    start_token = uuid.uuid4().hex[:8]
    end_token = uuid.uuid4().hex[:8]
    start_marker = f"__HI_START_{start_token}__"
    end_marker_re = re.compile(rf"__HI_DONE_{end_token}_(-?\d+)__")
    full_command = f'echo "{start_marker}"; {command}; echo "__HI_DONE_{end_token}_$?__"'
    run_tmux_raw(["send-keys", "-t", pane_id, full_command, "Enter"])

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = _capture_pane_text(pane_id)
        end_match = end_marker_re.search(text)
        if end_match:
            # rfind, not find: the compound command's own typed-echo also
            # contains this literal string, appearing before the shell has
            # actually run anything — the real output is the later copy.
            start_idx = text.rfind(start_marker)
            output_start = start_idx + len(start_marker) if start_idx != -1 else 0
            output = text[output_start : end_match.start()].strip()
            return output, int(end_match.group(1))
        time.sleep(0.2)

    return "(command may still be running — timed out waiting for output)", None
