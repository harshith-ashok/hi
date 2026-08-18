"""Command-line entry point for the `hi` terminal assistant.

Running `hi --code` / `--butler` / `--docs` / `--web` / `--term` opens a
dedicated tmux workspace: the user's existing shell stays in the left
pane, and the chosen assistant runs in a new right-hand pane. The user
never loses their shell. Running `hi` with no flag opens the same
workspace in auto-routing mode instead — each prompt is classified and
routed to a persona automatically (see hi/router.py).
"""

import argparse
import os
import sys

from hi.personas import PERSONAS
from hi.tmux_util import run_tmux

PANE_ENV_VAR = "HI_PERSONA_PANE"
LAUNCH_CWD_ENV_VAR = "HI_LAUNCH_CWD"
ROUTER_MARKER = "router"


def parse_persona(argv: list[str]) -> str | None:
    """Returns the requested persona name, or None for auto-routing mode
    (no flag given)."""
    parser = argparse.ArgumentParser(prog="hi", description="Launch a terminal assistant.")
    group = parser.add_mutually_exclusive_group(required=False)
    for name in PERSONAS:
        group.add_argument(f"--{name}", action="store_true", help=f"launch the {name} assistant")
    args = parser.parse_args(argv)
    return next((name for name in PERSONAS if getattr(args, name)), None)


def launch_tmux(persona: str | None) -> None:
    """Open the persona (or auto-routing mode, if None) in a right-hand
    tmux pane, leaving the user's shell untouched."""
    flag = f" --{persona}" if persona else ""
    # The left pane inherits the launch directory naturally (tmux's own
    # cwd inheritance), but the right pane's Python process needs it
    # passed explicitly — env vars, not cwd, cross the `env VAR=val hi`
    # boundary — so `term` can be aware of "the project" without the user
    # having to say so.
    inner_command = (
        f"env {PANE_ENV_VAR}={persona or ROUTER_MARKER} "
        f'{LAUNCH_CWD_ENV_VAR}="{os.getcwd()}" hi{flag}'
    )
    error = run_tmux([";", "split-window", "-h", "-p", "25", inner_command])
    if error:
        sys.exit(f"tmux failed to launch {persona or 'hi'}: {error}")


def main() -> None:
    persona = parse_persona(sys.argv[1:])

    if os.environ.get(PANE_ENV_VAR) == (persona or ROUTER_MARKER):
        if persona:
            from hi.repl import run_repl

            run_repl(persona)
        else:
            from hi.repl import run_router_repl

            run_router_repl()
        return

    launch_tmux(persona)


if __name__ == "__main__":
    main()
