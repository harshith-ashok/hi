"""Manages a simple Markdown TODO list at <VAULT_PATH>/hi/todo.md, so
`butler` can create, check off, and delete tasks — and greet the user with
what's still pending when a session starts.
"""

import re
from pathlib import Path

from langchain_core.tools import tool

from hi.config import VAULT_PATH
from hi.vault import with_frontmatter

TODO_PATH = VAULT_PATH / "hi" / "todo.md"

_TASK_RE = re.compile(r"^- \[( |x)\] (.*)$")


def _read_tasks() -> list[tuple[bool, str]]:
    if not TODO_PATH.exists():
        return []
    tasks = []
    for line in TODO_PATH.read_text().splitlines():
        match = _TASK_RE.match(line)
        if match:
            tasks.append((match.group(1) == "x", match.group(2)))
    return tasks


def _write_tasks(tasks: list[tuple[bool, str]]) -> None:
    TODO_PATH.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"- [{'x' if done else ' '}] {text}" for done, text in tasks)
    TODO_PATH.write_text(with_frontmatter(f"# TODO\n\n{body}\n", ["hi"]))


@tool
def add_task(text: str) -> str:
    """Add a new pending task to the TODO list.

    Args:
        text: The task description, e.g. "Buy milk".
    """
    tasks = _read_tasks()
    tasks.append((False, text))
    _write_tasks(tasks)
    return f"Added task: {text}"


@tool
def complete_task(text: str) -> str:
    """Check off a pending task as done, matched by partial,
    case-insensitive text.

    Args:
        text: Text identifying the task, e.g. "milk".
    """
    tasks = _read_tasks()
    for i, (done, task_text) in enumerate(tasks):
        if not done and text.lower() in task_text.lower():
            tasks[i] = (True, task_text)
            _write_tasks(tasks)
            return f"Checked off: {task_text}"
    return f"No pending task matching '{text}' found."


@tool
def remove_task(text: str) -> str:
    """Delete a task entirely (pending or done), matched by partial,
    case-insensitive text.

    Args:
        text: Text identifying the task, e.g. "milk".
    """
    tasks = _read_tasks()
    for i, (_, task_text) in enumerate(tasks):
        if text.lower() in task_text.lower():
            del tasks[i]
            _write_tasks(tasks)
            return f"Removed task: {task_text}"
    return f"No task matching '{text}' found."


@tool
def list_tasks() -> str:
    """List all tasks, pending and completed."""
    tasks = _read_tasks()
    if not tasks:
        return "No tasks yet."
    return "\n".join(f"[{'x' if done else ' '}] {text}" for done, text in tasks)


def pending_tasks_greeting() -> str | None:
    """Return a "Today's Tasks:" summary of pending tasks to greet the user
    with at startup, or None if there are none."""
    pending = [text for done, text in _read_tasks() if not done]
    if not pending:
        return None
    lines = "\n".join(f"{i}. {text}" for i, text in enumerate(pending, start=1))
    return f"Today's Tasks:\n{lines}"
