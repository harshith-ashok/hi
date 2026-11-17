"""Command-line entry point for `hi`.

Running `hi` with no flag starts the Docker stack (backend + tinyui) if it
isn't already up and opens the web UI, the one supported interface. The
other flags start standalone daemons (capture, suggestions, screen context,
wake word, the backend itself) and the Mac menu bar app.
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

CAPTURE_DAEMON_MARKER = "capture-daemon"
SUGGEST_DAEMON_MARKER = "suggest-daemon"
CONTEXT_DAEMON_MARKER = "context-daemon"
MENUBAR_MARKER = "menubar"
INSTALL_APP_MARKER = "install-app"
UNINSTALL_APP_MARKER = "uninstall-app"
INSTALL_AGENT_MARKER = "install-agent"
UNINSTALL_AGENT_MARKER = "uninstall-agent"
VOICE_DAEMON_MARKER = "voice-daemon"
WAKE_DAEMON_MARKER = "wake-daemon"

COMPOSE_FILE = Path(__file__).resolve().parent.parent / "docker-compose.yml"
BACKEND_URL = "http://127.0.0.1:8765/config"


def parse_mode(argv: list[str]) -> str | None:
    """The requested standalone mode (one of the *_MARKER constants), or None for the
    default: start the stack and open the web UI."""
    parser = argparse.ArgumentParser(prog="hi", description="Start hi (web UI by default).")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--capture-daemon",
        action="store_true",
        help="run the global quick-capture hotkey listener",
    )
    group.add_argument(
        "--suggest-daemon",
        action="store_true",
        help="run the continuous suggestion engine",
    )
    group.add_argument(
        "--context-daemon",
        action="store_true",
        help="run the always-on screen/context agent (standalone, native on the Mac)",
    )
    group.add_argument("--install-app", action="store_true", help="package the menu bar app as ~/Applications/hi.app and add it to Login Items")
    group.add_argument("--uninstall-app", action="store_true", help="remove hi.app and its Login Item")
    group.add_argument("--install-agent", action="store_true", help="start the menu bar app at login and restart it after a crash (launchd)")
    group.add_argument("--uninstall-agent", action="store_true", help="remove the launch agent")
    group.add_argument("--menubar", action="store_true", help="menu bar prompt that uses your screen as context (macOS)")
    group.add_argument(
        "--voice-daemon",
        action="store_true",
        help="run the backend (HTTP API) natively, without Docker",
    )
    group.add_argument(
        "--wake-daemon",
        action="store_true",
        help='run the ambient wake-word listener ("Hey Jarvis") + voice output',
    )
    args = parser.parse_args(argv)
    if args.capture_daemon:
        return CAPTURE_DAEMON_MARKER
    if args.suggest_daemon:
        return SUGGEST_DAEMON_MARKER
    if args.install_app:
        return INSTALL_APP_MARKER
    if args.uninstall_app:
        return UNINSTALL_APP_MARKER
    if args.install_agent:
        return INSTALL_AGENT_MARKER
    if args.uninstall_agent:
        return UNINSTALL_AGENT_MARKER
    if args.menubar:
        return MENUBAR_MARKER
    if args.context_daemon:
        return CONTEXT_DAEMON_MARKER
    if args.voice_daemon:
        return VOICE_DAEMON_MARKER
    if args.wake_daemon:
        return WAKE_DAEMON_MARKER
    return None


def backend_up() -> bool:
    try:
        with urllib.request.urlopen(BACKEND_URL, timeout=1):
            return True
    except OSError:
        return False


# Credentials the container can't read from the host's ~/.hi/.env itself.
FORWARDED_KEYS = ("GITHUB_PERSONAL_ACCESS_TOKEN", "N8N_MCP_URL", "N8N_MCP_TOKEN", "TAILSCALE_OLLAMA_URL", "HF_TOKEN", "AI_MODE", "SEARXNG_SECRET", "IMAGE_BACKEND", "IMAGE_URL", "IMAGE_MODEL", "IMAGE_API_KEY")


def host_timezone() -> str:
    """The Mac's IANA timezone (for example Europe/London), or "" if it can't be found. The container runs in UTC
    unless told otherwise, and a schedule at 8am must fire at 8am where you are."""
    try:
        target = os.readlink("/etc/localtime")
    except OSError:
        return os.environ.get("TZ", "")
    return target.split("zoneinfo/", 1)[1] if "zoneinfo/" in target else ""


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
    if tz := host_timezone():
        forwarded["TZ"] = tz
    return forwarded


def ensure_searxng_secret() -> str:
    """The secret SearXNG signs with, created in ~/.hi/.env on first start (like the host bridge token)."""
    import secrets

    import hi.config as config

    if not config.SEARXNG_SECRET:
        config.set_value("SEARXNG_SECRET", secrets.token_hex(32))
    return config.SEARXNG_SECRET


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


APP_BUNDLE = Path.home() / "Applications" / "hi.app"


def start_menubar() -> None:
    """On a Mac, start the menu bar app unless it is already running. The app starts and owns the context
    daemon and the host bridge (hi/menubar/supervisor.py), so quitting it stops them. If hi.app is installed
    (`hi --install-app`) it is opened as an app, so macOS shows permissions under "hi"."""
    from hi.menubar.lock import lock_is_free

    if sys.platform != "darwin" or not lock_is_free():
        return
    if APP_BUNDLE.exists():
        subprocess.run(["open", "-g", str(APP_BUNDLE)])
        return
    log = open(Path.home() / ".hi" / "menubar.log", "ab")
    subprocess.Popen([sys.executable, "-m", "hi.cli", "--menubar"], stdout=log, stderr=log, start_new_session=True)


def wait_for_host_bridge(seconds: float = 15.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline and not host_bridge_up():
        time.sleep(0.5)


def start_stack() -> None:
    """`docker compose up -d --build` for the backend + tinyui, unless the
    backend is already answering."""
    if sys.platform == "darwin":
        from hi.host_bridge import ensure_token

        ensure_token()  # before compose starts: the backend reads it from ~/.hi/.env
        start_menubar()  # brings up the bridge and the context daemon, and owns them
        wait_for_host_bridge()
    if backend_up():
        return
    ensure_searxng_secret()
    if not shutil.which("docker"):
        sys.exit("hi needs Docker to run the web UI.")
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
    mode = parse_mode(sys.argv[1:])

    if mode == CAPTURE_DAEMON_MARKER:
        from hi.capture.hotkey import run_capture_daemon

        run_capture_daemon()
        return

    if mode == SUGGEST_DAEMON_MARKER:
        from hi.suggest.engine import run_suggest_daemon

        run_suggest_daemon()
        return

    if mode in (INSTALL_APP_MARKER, UNINSTALL_APP_MARKER):
        from hi.menubar import install

        print(install.install_app() if mode == INSTALL_APP_MARKER else install.uninstall_app())
        return

    if mode in (INSTALL_AGENT_MARKER, UNINSTALL_AGENT_MARKER):
        from hi.menubar import install

        print(install.install_agent() if mode == INSTALL_AGENT_MARKER else install.uninstall_agent())
        return

    if mode == MENUBAR_MARKER:
        from hi.menubar.app import run_menubar

        run_menubar()
        return

    if mode == CONTEXT_DAEMON_MARKER:
        from hi.context.daemon import run_context_daemon

        run_context_daemon()
        return

    if mode == VOICE_DAEMON_MARKER:
        from hi.server.app import main as run_backend

        run_backend()
        return

    if mode == WAKE_DAEMON_MARKER:
        from hi.wake import run_wake_daemon

        run_wake_daemon()
        return

    open_web_ui()


if __name__ == "__main__":
    main()
