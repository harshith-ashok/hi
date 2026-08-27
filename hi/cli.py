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


CAPTURE_DAEMON_MARKER = "capture-daemon"
SUGGEST_DAEMON_MARKER = "suggest-daemon"
VOICE_DAEMON_MARKER = "voice-daemon"
WAKE_DAEMON_MARKER = "wake-daemon"


def parse_persona(argv: list[str]) -> str | None:
    """Returns the requested persona name, None for auto-routing mode (no
    flag given), or one of the *_DAEMON_MARKER constants for a standalone
    background process (not a persona — see hi/capture/hotkey.py and
    hi/suggest/engine.py)."""
    parser = argparse.ArgumentParser(prog="hi", description="Launch a terminal assistant.")
    group = parser.add_mutually_exclusive_group(required=False)
    for name in PERSONAS:
        group.add_argument(f"--{name}", action="store_true", help=f"launch the {name} assistant")
    group.add_argument(
        "--capture-daemon",
        action="store_true",
        help="run the global quick-capture hotkey listener (standalone, no tmux)",
    )
    group.add_argument(
        "--suggest-daemon",
        action="store_true",
        help="run the continuous suggestion engine (standalone, no tmux)",
    )
    group.add_argument(
        "--voice-daemon",
        action="store_true",
        help="run the local backend for the native voice companion app (standalone, no tmux)",
    )
    group.add_argument(
        "--wake-daemon",
        action="store_true",
        help='run the ambient wake-word listener ("Hey Jarvis") + voice output (standalone, no tmux)',
    )
    args = parser.parse_args(argv)
    if args.capture_daemon:
        return CAPTURE_DAEMON_MARKER
    if args.suggest_daemon:
        return SUGGEST_DAEMON_MARKER
    if args.voice_daemon:
        return VOICE_DAEMON_MARKER
    if args.wake_daemon:
        return WAKE_DAEMON_MARKER
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

    if persona == CAPTURE_DAEMON_MARKER:
        from hi.capture.hotkey import run_capture_daemon

        run_capture_daemon()
        return

    if persona == SUGGEST_DAEMON_MARKER:
        from hi.suggest.engine import run_suggest_daemon

        run_suggest_daemon()
        return

    if persona == VOICE_DAEMON_MARKER:
        from hi.ipc.server import run_ipc_daemon

        run_ipc_daemon()
        return

    if persona == WAKE_DAEMON_MARKER:
        from hi.wake import run_wake_daemon

        run_wake_daemon()
        return

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
