"""A direct line to the user's real macOS shell, bypassing the Docker container.

`run_shell_command` runs wherever the backend runs, which in the usual setup is a
Linux container with only a few mounted folders. `run_mac_shell` runs the command
in the user's own zsh on the Mac instead: their PATH, Homebrew, Xcode tools, SSH
keys, every folder.

Native on a Mac it runs the command directly. From the container it goes through
the host bridge (hi/host_bridge.py) as the `mac_shell` tool, which needs the
bridge token. Deletions still ask for confirmation first, here in the backend
(the bridge has no terminal to ask on). Set HI_MAC_SHELL=off to disable it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

from hi.action_tiers import confirm_destructive
from hi.agents.term.danger import looks_destructive
from hi.host import call as call_host
from hi.memory.vault import launch_cwd

TIMEOUT_SECONDS = 120
CONTAINER_HOME = "/host"  # where the container sees the Mac's home folders (docker-compose.yml)


def enabled() -> bool:
    return os.environ.get("HI_MAC_SHELL", "on").strip().lower() not in ("off", "0", "false", "no")


def _to_mac_path(text: str) -> str:
    """Container paths (/host/Dev/...) back to the Mac's real home."""
    return text.replace(f"{CONTAINER_HOME}/", f"{Path.home()}/")


def execute(command: str, cwd: str = "") -> str:
    """Run `command` in the Mac's login zsh. Runs only where the home folder is the Mac's."""
    workdir = _to_mac_path(cwd) if cwd else str(Path.home())
    if not Path(workdir).is_dir():
        workdir = str(Path.home())
    try:
        done = subprocess.run(
            ["/bin/zsh", "-lc", _to_mac_path(command)],
            cwd=workdir, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return f"Timed out after {TIMEOUT_SECONDS}s: {command}"
    output = (done.stdout + done.stderr).strip()
    return f"Exit code: {done.returncode}\nOutput:\n{output[-8000:]}"


@tool
def mac_shell(command: str, cwd: str = "") -> str:
    """Run a command in the user's macOS zsh (host bridge side; never offered to the model directly).

    Args:
        command: The shell command.
        cwd: Working directory; container paths under /host are mapped to the Mac's home.
    """
    return execute(command, cwd)


@tool
def run_mac_shell(command: str, cwd: str = "") -> str:
    """Run a command in the user's REAL macOS shell (zsh, their PATH, Homebrew, SSH keys,
    any folder), not the Docker container. Use it when something must happen on the Mac
    itself, or when the container's shell lacks the tool, the folder or the access.
    Commands starting under the mounted /host folders are mapped to the real home.
    120s limit, no interactive input. Deletions ask the user first.

    Args:
        command: The shell command, e.g. "brew list" or "ls ~/Library".
        cwd: Optional working directory (defaults to the active project, else the home folder).
    """
    if not enabled():
        return "The Mac shell is turned off (HI_MAC_SHELL=off)."
    if looks_destructive(command) and not confirm_destructive(f"run on your Mac: {command}"):
        return f"Command not run — user declined: {command}"
    workdir = cwd or launch_cwd()
    if sys.platform == "darwin":
        return execute(command, workdir)
    return call_host("mac_shell", {"command": command, "cwd": workdir})
