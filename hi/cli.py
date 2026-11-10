"""Command-line entry point for the `hi` terminal assistant.

Running `hi` with no flag starts the Docker stack (backend + tinyui) if it
isn't already up and opens the web UI — the main interface. `hi --tui` is
the terminal equivalent. `hi --code` / `--butler` / `--docs` / `--web` /
`--term` open a dedicated tmux workspace (the user's shell stays in the
left pane, the assistant in a right-hand pane), and `hi --tmux` does the
same in auto-routing mode (see hi/router.py).
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import warnings
import webbrowser
from pathlib import Path

# langchain_core still imports pydantic.v1, which warns on Python 3.14+.
# Must run before anything imports langchain.
warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")

from hi.personas import PERSONAS
from hi.tmux_util import run_tmux

PANE_ENV_VAR = "HI_PERSONA_PANE"
LAUNCH_CWD_ENV_VAR = "HI_LAUNCH_CWD"
ROUTER_MARKER = "router"


CAPTURE_DAEMON_MARKER = "capture-daemon"
SUGGEST_DAEMON_MARKER = "suggest-daemon"
CONTEXT_DAEMON_MARKER = "context-daemon"
MENUBAR_MARKER = "menubar"
VOICE_DAEMON_MARKER = "voice-daemon"
WAKE_DAEMON_MARKER = "wake-daemon"
TUI_MARKER = "tui"
TMUX_MARKER = "tmux"

COMPOSE_FILE = Path(__file__).resolve().parent.parent / "docker-compose.yml"
BACKEND_URL = "http://127.0.0.1:8765/config"


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
        "--context-daemon",
        action="store_true",
        help="run the always-on screen/context agent (standalone, native on the Mac)",
    )
    group.add_argument("--menubar", action="store_true", help="menu bar prompt that uses your screen as context (macOS)")
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
    group.add_argument("--tui", action="store_true", help="minimal terminal UI (standalone, no tmux)")
    group.add_argument("--tmux", action="store_true", help="auto-routing REPL in a tmux pane (the old default)")
    args = parser.parse_args(argv)
    if args.tui:
        return TUI_MARKER
    if args.tmux:
        return TMUX_MARKER
    if args.capture_daemon:
        return CAPTURE_DAEMON_MARKER
    if args.suggest_daemon:
        return SUGGEST_DAEMON_MARKER
    if args.menubar:
        return MENUBAR_MARKER
    if args.context_daemon:
        return CONTEXT_DAEMON_MARKER
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


def backend_up() -> bool:
    try:
        with urllib.request.urlopen(BACKEND_URL, timeout=1):
            return True
    except OSError:
        return False


# Credentials the container can't read from the host's ~/.hi/.env itself.
FORWARDED_KEYS = ("GITHUB_PERSONAL_ACCESS_TOKEN", "N8N_MCP_URL", "N8N_MCP_TOKEN", "OPENROUTER_API_KEY", "TAILSCALE_OLLAMA_URL", "HF_TOKEN", "AI_MODE")


def _forwarded_settings() -> dict[str, str]:
    from hi.config import ENV_PATH, _parse_env

    saved = _parse_env(ENV_PATH)
    forwarded = {key: saved[key] for key in FORWARDED_KEYS if saved.get(key) and key not in os.environ}
    vault = saved.get("VAULT_PATH")  # the container reads/writes the real vault, mounted at /vault
    if vault and Path(vault).is_dir() and "HI_VAULT" not in os.environ:
        forwarded["HI_VAULT"] = Path(vault).as_posix()  # forward slashes: a Windows path's colons trip compose
    if forwarded.get("HI_VAULT"):
        # Remembered next to the compose file, so a plain `docker compose up` (or Docker
        # restarting the stack) still mounts the real vault, not an empty volume.
        from hi.env_file import write_env_var

        write_env_var("HI_VAULT", forwarded["HI_VAULT"], path=COMPOSE_FILE.parent / ".env")
    forwarded["HI_HOST_ROOT"] = Path.home().as_posix()
    return forwarded


def _ensure_mounted_files() -> None:
    """Docker would create a missing bind-mount source as a directory; these must be files."""
    for path in (Path.home() / ".gitconfig", Path.home() / ".hi" / ".env"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)


def host_bridge_up() -> bool:
    from hi import config

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{config.HOST_BRIDGE_PORT}/health", timeout=1):
            return True
    except OSError:
        return False


def start_host_bridge() -> None:
    """On a Mac, run the bridge that lets the Dockerized backend use Mac-only tools
    (open apps, Bluetooth, screen, ...). Detached, so it outlives this command."""
    if sys.platform != "darwin" or host_bridge_up():
        return
    from hi.host_bridge import ensure_token

    ensure_token()  # before compose starts: the backend reads it from ~/.hi/.env
    log = open(Path.home() / ".hi" / "bridge.log", "ab")
    subprocess.Popen([sys.executable, "-m", "hi.host_bridge"], stdout=log, stderr=log, start_new_session=True)


def context_daemon_up() -> bool:
    """The daemon rewrites its snapshot every few seconds, so a fresh one means it is running."""
    from hi.context import now

    snapshot = now.read()
    return bool(snapshot) and time.time() - snapshot["ts"] < now.STALE_SECONDS


def start_context_daemon() -> None:
    """On a Mac, run the always-on context agent (hi/context/daemon.py) alongside the bridge. It has to be
    native — screen, window and Accessibility APIs don't exist inside the container — so `hi` starts it
    here, detached, instead of the user running `hi --context-daemon` by hand."""
    if sys.platform != "darwin" or context_daemon_up():
        return
    log = open(Path.home() / ".hi" / "context.log", "ab")
    subprocess.Popen([sys.executable, "-m", "hi.cli", "--context-daemon"], stdout=log, stderr=log, start_new_session=True)


def start_menubar() -> None:
    """On a Mac, start the menu bar app (hi/menubar/app.py) unless it is already running."""
    from hi.menubar.app import lock_is_free

    if sys.platform != "darwin" or not lock_is_free():
        return
    log = open(Path.home() / ".hi" / "menubar.log", "ab")
    subprocess.Popen([sys.executable, "-m", "hi.cli", "--menubar"], stdout=log, stderr=log, start_new_session=True)


def start_stack() -> None:
    """`docker compose up -d --build` for the backend + tinyui, unless the
    backend is already answering."""
    start_host_bridge()
    start_context_daemon()
    start_menubar()
    if backend_up():
        return
    if not shutil.which("docker"):
        sys.exit("hi needs Docker to run the web UI (or use `hi --tui`).")
    if not COMPOSE_FILE.exists():
        sys.exit(f"docker-compose.yml not found at {COMPOSE_FILE}")
    print("starting hi…")
    _ensure_mounted_files()
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--build"], env={**os.environ, **_forwarded_settings()}
    )
    if result.returncode != 0:
        sys.exit("docker compose failed — is Docker/OrbStack running?")
    for _ in range(60):
        if backend_up():
            return
        time.sleep(1)
    sys.exit("backend didn't come up; check `docker compose logs backend`.")


def open_web_ui() -> None:
    """The default `hi`: make sure the stack is running, open tinyui."""
    start_stack()
    url = f"http://localhost:{os.environ.get('HI_WEB_PORT', '5173')}"
    print(f"hi is running at {url}")
    webbrowser.open(url)


def main() -> None:
    persona = parse_persona(sys.argv[1:])

    if persona == TUI_MARKER:
        from hi.tui.app import run

        run()
        return

    if persona == CAPTURE_DAEMON_MARKER:
        from hi.capture.hotkey import run_capture_daemon

        run_capture_daemon()
        return

    if persona == SUGGEST_DAEMON_MARKER:
        from hi.suggest.engine import run_suggest_daemon

        run_suggest_daemon()
        return

    if persona == MENUBAR_MARKER:
        from hi.menubar.app import run_menubar

        run_menubar()
        return

    if persona == CONTEXT_DAEMON_MARKER:
        from hi.context.daemon import run_context_daemon

        run_context_daemon()
        return

    if persona == VOICE_DAEMON_MARKER:
        from hi.ipc.server import run_ipc_daemon

        run_ipc_daemon()
        return

    if persona == WAKE_DAEMON_MARKER:
        from hi.wake import run_wake_daemon

        run_wake_daemon()
        return

    if persona is None and os.environ.get(PANE_ENV_VAR) != ROUTER_MARKER:
        open_web_ui()
        return

    if persona == TMUX_MARKER:
        launch_tmux(None)
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
