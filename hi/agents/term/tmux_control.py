"""Lets `term` grow the current tmux workspace beyond the fixed left/right
layout — splitting a new pane for something like a dev server or a log
tail, so it doesn't have to share (or tie up) the pane run_shell_command
also operates in.
"""

from langchain_core.tools import tool

from hi.agents.term.shell_pane import left_pane_id
from hi.tmux_util import keep_alive, run_tmux_raw


def _add_pane(command: str | None = None, split: str = "horizontal") -> str:
    """Plain-function core of the add_pane tool below — also called
    directly by run_shell_command (hi/agents/term/term.py) to transparently
    redirect a command that looks long-running, without going through the
    tool-invocation interface for an internal call."""
    if split not in ("horizontal", "vertical"):
        return f"Invalid split '{split}'. Use 'horizontal' or 'vertical'."

    pane_id = left_pane_id()
    flag = "-h" if split == "horizontal" else "-v"
    args = ["split-window", flag, "-t", pane_id]
    if command:
        # keep_alive, not the raw command: a command that fails fast (wrong
        # directory, missing dependency) would otherwise close its own pane
        # before anyone can see why — verified live, `npm run dev` from a
        # directory with no package.json vanished in under a second without
        # this.
        args.append(keep_alive(command))

    result = run_tmux_raw(args)
    if result.returncode != 0:
        return f"Failed to add pane: {result.stderr.strip()}"

    suffix = f" running: {command}" if command else ""
    return f"Added a new {split} pane{suffix}."


@tool
def add_pane(command: str | None = None, split: str = "horizontal") -> str:
    """Split a new tmux pane in the current workspace (not a new window),
    optionally running a command in it immediately — useful for something
    you want running alongside your shell work (a dev server, a log
    tail) without tying up the pane run_shell_command operates in.

    Args:
        command: Command to run in the new pane, e.g. "npm run dev".
            Optional — an empty pane is fine too.
        split: "horizontal" or "vertical".
    """
    return _add_pane(command, split)
