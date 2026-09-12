""""Where was I" — summarizes where things were left off in a project:
recent git history, recent conversation-log mentions, and the project's
own vault note (hi/knowledge/projects/<name>.md, the path convention
already established elsewhere in this codebase — see README's dev-flow
example). Plain filesystem/subprocess lookups, no LLM call, matching
hi/briefing.py's own "none of this needs reasoning to find" philosophy.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from langchain_core.tools import tool

from hi.agents.term.dev_flow_tool import _current_project_directory, _load_flows
from hi.vault import conversations_dir, knowledge_dir


def matching_dev_flow_name(directory: str) -> str | None:
    """The dev_flows.json project name whose directory exactly contains
    `directory` (itself or a parent), or None if `directory` isn't inside
    any known dev flow — used to gate the automatic "where was I" greeting
    at term startup (hi/personas.py) to only known projects."""
    target = Path(directory).resolve()
    for name, flow in _load_flows().items():
        flow_dir = Path(flow["directory"]).resolve()
        if target == flow_dir or flow_dir in target.parents:
            return name
    return None


def _project_name_for(directory: str) -> str:
    return matching_dev_flow_name(directory) or Path(directory).name


def _git_summary(directory: str, n: int = 5) -> str:
    if not (Path(directory) / ".git").is_dir():
        return "(not a git repository)"
    log = subprocess.run(
        ["git", "-C", directory, "log", f"-{n}", "--oneline"],
        capture_output=True,
        text=True,
    )
    status = subprocess.run(
        ["git", "-C", directory, "status", "--short"],
        capture_output=True,
        text=True,
    )
    commits = log.stdout.strip() or "(no commits yet)"
    dirty = status.stdout.strip() or "(clean)"
    return f"Recent commits:\n{commits}\n\nWorking tree status:\n{dirty}"


def _recent_conversation_lines(project_name: str, max_lines: int = 8, max_logs: int = 7) -> str:
    """Cheap substring match over the most recent conversation logs — not
    semantic search, consistent with hi/briefing.py's plain-lookup
    philosophy for this kind of quick summary."""
    if not conversations_dir().is_dir():
        return "(no conversation logs yet)"
    logs = sorted(conversations_dir().glob("*.md"), key=lambda p: p.stem, reverse=True)[:max_logs]
    needle = project_name.lower()
    matches = []
    for path in logs:
        for line in path.read_text().splitlines():
            if needle in line.lower() and line.strip().startswith(("**User:**", "**Assistant:**")):
                matches.append(f"{path.stem}: {line.strip()}")
    if not matches:
        return "(nothing found mentioning this project)"
    return "\n".join(matches[-max_lines:])


def _project_note_summary(project_name: str) -> str:
    projects_dir = knowledge_dir() / "projects"
    note_path = projects_dir / f"{project_name}.md"
    if not note_path.exists() and projects_dir.is_dir():
        note_path = next(
            (p for p in projects_dir.glob("*.md") if project_name.lower() in p.stem.lower()),
            note_path,
        )
    if not note_path.exists():
        return "(no project note yet)"
    return f"{note_path.relative_to(knowledge_dir().parent)}:\n{note_path.read_text().strip()}"


def build_resume_context(directory: str) -> str:
    project_name = _project_name_for(directory)
    parts = [
        f"Resuming: {project_name} ({directory})",
        "",
        _git_summary(directory),
        "",
        "Recent mentions in conversation logs:",
        _recent_conversation_lines(project_name),
        "",
        "Project note:",
        _project_note_summary(project_name),
    ]
    return "\n".join(parts)


@tool
def resume_context(project_dir: str | None = None) -> str:
    """Summarize where things were left off in a project: recent git
    commits and working-tree status, recent conversation-log mentions,
    and the project's own vault note if it has one. Use this for
    "where was I" / "what was I doing" / resuming a project.

    Args:
        project_dir: Directory to resume, e.g. "/Users/me/Projects/kaapi".
            Defaults to the directory `hi` was launched from.
    """
    directory = project_dir or _current_project_directory()
    if not Path(directory).is_dir():
        return f"'{directory}' is not a directory."
    return build_resume_context(directory)
