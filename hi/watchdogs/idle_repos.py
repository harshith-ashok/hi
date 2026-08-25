"""Idle-repo watchdog: flags known project directories whose last commit
is older than a threshold while pending tasks still reference that
project — a "you have open work here but haven't touched the repo in a
while" signal. Read-only: it only ever returns flags for
hi/briefing.py to surface, never touches a repo or archives anything.

"Known project directories" = dev_flows.json's entries plus every
subdirectory of PROJECTS_ROOT — the same source hi/briefing.py already
uses for "most recently opened project", so both features agree on what
counts as a project.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from hi.agents.term.dev_flow_tool import _load_flows
from hi.capture.schema import Task
from hi.capture.store import list_items

IDLE_THRESHOLD_DAYS_DEFAULT = 14
PROJECTS_ROOT = Path.home() / "Dev" / "Projects"


@dataclass
class IdleRepoFlag:
    project: str
    directory: str
    days_idle: int
    open_task_count: int


def _last_commit_age_days(directory: Path) -> int | None:
    if not (directory / ".git").is_dir():
        return None
    result = subprocess.run(
        ["git", "-C", str(directory), "log", "-1", "--format=%ct"],
        capture_output=True,
        text=True,
    )
    ts = result.stdout.strip()
    if not ts.isdigit():
        return None
    return int((time.time() - int(ts)) // 86400)


def _known_project_dirs() -> dict[str, Path]:
    dirs: dict[str, Path] = {
        name: Path(flow["directory"]) for name, flow in _load_flows().items()
    }
    if PROJECTS_ROOT.is_dir():
        for entry in PROJECTS_ROOT.iterdir():
            if entry.is_dir() and entry.name not in dirs:
                dirs[entry.name] = entry
    return dirs


def _open_task_count(project_name: str) -> int:
    return sum(
        1
        for item in list_items(kind="task")
        if isinstance(item, Task)
        and item.status == "pending"
        and item.project
        and item.project.lower() == project_name.lower()
    )


def find_idle_repos(threshold_days: int = IDLE_THRESHOLD_DAYS_DEFAULT) -> list[IdleRepoFlag]:
    flags = []
    for name, directory in _known_project_dirs().items():
        if not directory.is_dir():
            continue
        idle_days = _last_commit_age_days(directory)
        if idle_days is None or idle_days < threshold_days:
            continue
        open_tasks = _open_task_count(name)
        if open_tasks == 0:
            continue
        flags.append(
            IdleRepoFlag(
                project=name,
                directory=str(directory),
                days_idle=idle_days,
                open_task_count=open_tasks,
            )
        )
    return flags
