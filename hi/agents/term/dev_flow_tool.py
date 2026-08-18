"""Tools for opening and saving development workspaces in dev_flows.json:
a project name mapped to a directory, a list of apps to open it in, and an
optional two-pane tmux layout to start there. Still a plain file the user
can hand-edit anytime — add_dev_flow just gives the agent a way to add to
it too, rather than every entry needing to be created by hand.
"""

import json
import os
import subprocess
from pathlib import Path

from langchain_core.tools import tool

from hi.tmux_util import keep_alive, run_tmux_raw, tmux_new_target

DEV_FLOWS_PATH = Path.home() / ".hi" / "dev_flows.json"
LAUNCH_CWD_ENV_VAR = "HI_LAUNCH_CWD"


def _current_project_directory() -> str:
    return os.environ.get(LAUNCH_CWD_ENV_VAR) or os.getcwd()


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
        # Create the window first and capture its id explicitly, then target
        # that id for the split — rather than chaining both commands with
        # ";" and relying on implicit "current window" continuity, which
        # breaks if the left pane's command exits before the split happens.
        new_window = run_tmux_raw(
            [
                tmux_new_target(),
                "-P",
                "-F",
                "#{window_id}",
                "-c",
                directory,
                keep_alive(tmux_layout["left"]),
            ]
        )
        if new_window.returncode != 0:
            problems.append(
                "tmux workspace failed: "
                f"{new_window.stderr.strip() or 'window creation failed'}"
            )
        else:
            window_id = new_window.stdout.strip()
            split = run_tmux_raw(
                [
                    "split-window",
                    "-t",
                    window_id,
                    "-h",
                    "-c",
                    directory,
                    keep_alive(tmux_layout["right"]),
                ]
            )
            if split.returncode != 0:
                problems.append(
                    f"tmux split failed: {split.stderr.strip() or 'split-window failed'}"
                )

    if problems:
        return f"Opened dev flow '{key}' in {directory}, with issues:\n" + "\n".join(problems)
    return f"Opened dev flow '{key}' in {directory}."


@tool
def add_dev_flow(
    name: str,
    left_command: str | None = None,
    right_command: str | None = None,
    apps: list[str] | None = None,
) -> str:
    """Save the directory you were launched from as a new dev flow, so
    open_dev_flow(name) can reopen it later. tmux/apps are optional — a
    bare name is enough to save now; the resulting entry in
    ~/.hi/dev_flows.json can always be hand-edited afterward to add or
    change a layout.

    Args:
        name: A short name for this project, e.g. "kaapi".
        left_command: Command for the left tmux pane when reopened, e.g.
            "bench start". Needs right_command too, or neither is saved.
        right_command: Command for the right tmux pane, e.g. "htop".
        apps: Commands to launch when reopened, e.g. ["zed", "open ."].
    """
    flows = _load_flows()
    if any(k.lower() == name.lower() for k in flows):
        return (
            f"A dev flow named '{name}' already exists. Use a different "
            "name, or edit ~/.hi/dev_flows.json directly to change it."
        )

    directory = _current_project_directory()
    entry: dict = {"directory": directory}
    if left_command and right_command:
        entry["tmux"] = {"left": left_command, "right": right_command}
    if apps:
        entry["apps"] = apps

    flows[name] = entry
    DEV_FLOWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEV_FLOWS_PATH.write_text(json.dumps(flows, indent=2))
    return f"Saved dev flow '{name}' for {directory}."
