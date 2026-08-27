"""Manages `hi`'s tasks (<VAULT_PATH>/hi/tasks/*.md — see
hi/capture/schema.py and hi/capture/store.py), so `butler` can create,
check off, and delete tasks — and greet the user with what's still pending
when a session starts. Each task is its own Markdown file with frontmatter
(status/category/priority/due/...) instead of one flat checklist file;
hi/capture/store.py migrates any pre-existing flat
<VAULT_PATH>/hi/todo.md in automatically, the first time this reads.
"""

from langchain_core.tools import tool

from hi.action_tiers import confirm_destructive
from hi.capture.ambient import normalize_ambient
from hi.capture.schema import Task
from hi.capture.store import delete, find_task, list_items, save


@tool
def add_task(text: str) -> str:
    """Add a new pending task to the TODO list.

    Args:
        text: The task description, e.g. "Buy milk".
    """
    save(Task(text=text, source_persona="butler"))
    return f"Added task: {text}"


@tool
def capture_note(raw_text: str) -> str:
    """Jot down a raw note — a to-do, a reminder, something happening at a
    specific time — and let it be classified into a task or event
    automatically, instead of deciding that yourself. Prefer this over
    add_task when the note might have a date/time attached (e.g. "assignment
    due Friday", "team meeting at 3pm tomorrow") so that date is actually
    captured.

    Args:
        raw_text: The note verbatim, e.g. "renew car registration by the 20th".
    """
    item = normalize_ambient(raw_text, source_persona="butler")
    kind = "event" if item.kind == "event" else "task"
    when = getattr(item, "when", None) or getattr(item, "due", None)
    suffix = f" (due {when})" if when else ""
    return f"Captured as {kind}: {item.text}{suffix}"


@tool
def complete_task(text: str) -> str:
    """Check off a pending task as done, matched by partial,
    case-insensitive text.

    Args:
        text: Text identifying the task, e.g. "milk".
    """
    task = find_task(text, pending_only=True)
    if not task:
        return f"No pending task matching '{text}' found."
    task.status = "done"
    save(task)
    return f"Checked off: {task.text}"


@tool
def remove_task(text: str) -> str:
    """Delete a task entirely (pending or done), matched by partial,
    case-insensitive text.

    Args:
        text: Text identifying the task, e.g. "milk".
    """
    task = find_task(text)
    if not task:
        return f"No task matching '{text}' found."
    if not confirm_destructive(f"delete the task '{task.text}'"):
        return f"Not removed — user declined: {task.text}"
    delete(task.id)
    return f"Removed task: {task.text}"


@tool
def list_tasks() -> str:
    """List all tasks, pending and completed."""
    tasks = [item for item in list_items(kind="task") if isinstance(item, Task)]
    if not tasks:
        return "No tasks yet."
    return "\n".join(f"[{'x' if t.status == 'done' else ' '}] {t.text}" for t in tasks)


def pending_tasks_greeting() -> str | None:
    """Return a "Today's Tasks:" summary of pending tasks to greet the user
    with at startup, or None if there are none."""
    pending = [
        item.text
        for item in list_items(kind="task")
        if isinstance(item, Task) and item.status == "pending"
    ]
    if not pending:
        return None
    lines = "\n".join(f"{i}. {text}" for i, text in enumerate(pending, start=1))
    return f"Today's Tasks:\n{lines}"
