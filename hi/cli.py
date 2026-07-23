"""Command-line entry point for the `hi` terminal assistant.

Running `hi --code` / `--butler` / `--docs` / `--web` opens a dedicated tmux
workspace: the user's existing shell stays in the left pane, and the chosen
assistant runs in a new right-hand pane. The user never loses their shell.
"""

import argparse
import os
import sys

from hi.personas import PERSONAS
from hi.tmux_util import run_tmux

PANE_ENV_VAR = "HI_PERSONA_PANE"


def parse_persona(argv: list[str]) -> str:
    parser = argparse.ArgumentParser(prog="hi", description="Launch a terminal assistant.")
    group = parser.add_mutually_exclusive_group(required=True)
    for name in PERSONAS:
        group.add_argument(f"--{name}", action="store_true", help=f"launch the {name} assistant")
    args = parser.parse_args(argv)
    return next(name for name in PERSONAS if getattr(args, name))


def launch_tmux(persona: str) -> None:
    """Open the persona in a right-hand tmux pane, leaving the user's shell untouched."""
    inner_command = f"env {PANE_ENV_VAR}={persona} hi --{persona}"
    error = run_tmux([";", "split-window", "-h", "-p", "25", inner_command])
    if error:
        sys.exit(f"tmux failed to launch {persona}: {error}")


def main() -> None:
    persona = parse_persona(sys.argv[1:])

    if os.environ.get(PANE_ENV_VAR) == persona:
        from hi.repl import run_repl

        run_repl(persona)
        return

    launch_tmux(persona)


if __name__ == "__main__":
    main()
