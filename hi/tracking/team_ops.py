"""Hackathon team ops assistant (TODO.md Phase 4): status drafts,
ownership tracking, and deadline pings for teammates. Built generically —
no hardcoded team roster or hackathon name — since teammates and their
tasks are added the same way applications.py's entries are: bootstrapped
empty, filled in via tool calls as the team actually forms.

Ownership reuses Phase 0's Task.owner field rather than a parallel
"assignment" structure — a task already has a project; who owns it inside
that project is just one more optional field, not a new concept.
"""

from __future__ import annotations

from langchain_core.tools import tool

from hi.capture.schema import Task
from hi.capture.store import find_task, list_items, save
from hi.tracking.deadlines import get_deadlines


@tool
def assign_task_owner(text: str, owner: str) -> str:
    """Assign (or reassign) an existing task to a teammate, matched by
    partial, case-insensitive text against the task.

    Args:
        text: Text identifying the task, e.g. "set up CI".
        owner: The teammate's name, e.g. "Alice".
    """
    task = find_task(text)
    if not task:
        return f"No task matching '{text}' found."
    task.owner = owner
    save(task)
    return f"Assigned '{task.text}' to {owner}."


def _tasks_for_project(project: str | None) -> list[Task]:
    return [
        t
        for t in list_items(kind="task")
        if isinstance(t, Task) and (project is None or (t.project or "").lower() == project.lower())
    ]


@tool
def team_status_draft(project: str | None = None) -> str:
    """Draft a plain-text team status update: per teammate, how many
    tasks are done vs. still open, and anything overdue — useful for a
    hackathon/team standup update. Optionally scoped to one project.

    Args:
        project: Optional project name to scope to, e.g. "kaapi". Omit
            for every tracked task regardless of project.
    """
    tasks = _tasks_for_project(project)
    if not tasks:
        scope = f" for '{project}'" if project else ""
        return f"No tasks tracked{scope} yet."

    by_owner: dict[str, list[Task]] = {}
    for t in tasks:
        by_owner.setdefault(t.owner or "(unassigned)", []).append(t)

    deadline_titles = {d.title.lower() for d in get_deadlines()}

    lines = [f"Team status{f' — {project}' if project else ''}:"]
    for owner, items in sorted(by_owner.items()):
        done = sum(1 for t in items if t.status == "done")
        pending = [t for t in items if t.status == "pending"]
        flagged = [t.text for t in pending if t.text.lower() in deadline_titles]
        line = f"- {owner}: {done} done, {len(pending)} pending"
        if flagged:
            line += f" (due soon: {', '.join(flagged)})"
        lines.append(line)
    return "\n".join(lines)


@tool
def team_deadline_pings(project: str | None = None) -> str:
    """List upcoming deadlines alongside which teammate owns the
    matching task, if any — a ping list for who needs a nudge.

    Args:
        project: Optional project name to scope to. Omit for everything.
    """
    tasks_by_text = {t.text.lower(): t for t in _tasks_for_project(project) if t.status == "pending"}
    deadlines = get_deadlines()
    if project:
        deadlines = [d for d in deadlines if d.title.lower() in tasks_by_text]
    if not deadlines:
        return "No matching deadlines found."

    lines = []
    for d in deadlines:
        task = tasks_by_text.get(d.title.lower())
        owner = task.owner if task and task.owner else "unassigned"
        lines.append(f"{d.due} — {d.title} ({owner})")
    return "\n".join(lines)
