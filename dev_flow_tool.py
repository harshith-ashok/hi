"""Tool for opening a saved development workspace from dev_flows.json.

dev_flows.json is user-managed config (not editable by the agent): it maps
a project name to a directory, a list of apps to open it in, and a two-pane
tmux layout to start there.
"""

import json
import subprocess
from pathlib import Path

from langchain_core.tools import tool

from tmux_util import run_tmux

DEV_FLOWS_PATH = Path.home() / ".hi" / "dev_flows.json"


def _load_flows() -> dict:
    if not DEV_FLOWS_PATH.exists():
        return {}
    return json.loads(DEV_FLOWS_PATH.read_text())


def _open_app(command: str, directory: str) -> str | None:
    """Run one entry from a flow's "apps" list. A bare command name (no
    spaces) is given the directory as an argument; a full command string is
    run as-is with the directory as its cwd."""
    full_command = command if " " in command else f"{command} {directory}"
    try:
        subprocess.run(
            full_command,
            shell=True,
            cwd=directory,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return None
    except subprocess.TimeoutExpired:
        return f"'{command}' timed out"
    except subprocess.CalledProcessError as e:
        return f"'{command}' failed: {e.stderr.strip() or e}"


@tool
def open_dev_flow(project: str) -> str:
    """Open a saved development workspace for a project: launches its
    directory in the configured apps and starts a tmux workspace running its
    configured left/right pane commands.

    Args:
        project: The project's name as configured in dev_flows.json, e.g. "kaapi".
    """
    flows = _load_flows()
    key = next((k for k in flows if k.lower() == project.lower()), None)
    if key is None:
        available = ", ".join(sorted(flows)) or "none configured"
        return f"No dev flow found for '{project}'. Available: {available}"

    flow = flows[key]
    directory = flow["directory"]
    if not Path(directory).is_dir():
        return f"Dev flow '{key}' points to a missing directory: {directory}"

    problems = []

    for app_command in flow.get("apps", []):
        error = _open_app(app_command, directory)
        if error:
            problems.append(error)

    tmux_layout = flow.get("tmux")
    if tmux_layout:
        error = run_tmux(
            [
                "-c",
                directory,
                tmux_layout["left"],
                ";",
                "split-window",
                "-h",
                "-c",
                directory,
                tmux_layout["right"],
            ]
        )
        if error:
            problems.append(f"tmux workspace failed: {error}")

    if problems:
        return f"Opened dev flow '{key}' in {directory}, with issues:\n" + "\n".join(problems)
    return f"Opened dev flow '{key}' in {directory}."
