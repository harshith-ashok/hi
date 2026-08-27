"""Vault-wide deadline aggregation: merges hi/capture/store.py's
structured Task.due/Event.when with any other vault note's `due:`
frontmatter (hi/frontmatter.py's convention, established in Phase 0) into
one sorted countdown. No separate entry system — everything's already
either a task, an event, or a note.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from langchain_core.tools import tool

from hi.capture.schema import Event, Task
from hi.capture.store import TASKS_DIR, list_items
from hi.config import VAULT_PATH
from hi.frontmatter import parse_frontmatter

_DATE_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d")


@dataclass
class Deadline:
    title: str
    due: str
    category: str | None
    source: str


def _parse_date(value: str) -> datetime | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _from_tasks_and_events() -> list[Deadline]:
    deadlines = []
    for item in list_items():
        if isinstance(item, Task) and item.due and item.status == "pending":
            deadlines.append(Deadline(item.text, item.due, item.category, f"task:{item.id}"))
        elif isinstance(item, Event):
            deadlines.append(Deadline(item.text, item.when, item.category, f"event:{item.id}"))
    return deadlines


def _title_from_body(body: str, fallback: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return fallback


def _from_vault_notes() -> list[Deadline]:
    """Any other vault note declaring `due:` — hi/tasks/ is excluded so
    the tasks/events already picked up above aren't double-counted."""
    deadlines = []
    if not VAULT_PATH.is_dir():
        return deadlines
    for path in VAULT_PATH.rglob("*.md"):
        if path.is_relative_to(TASKS_DIR):
            continue
        try:
            content = path.read_text()
        except OSError:
            continue
        fields, body = parse_frontmatter(content)
        due = fields.get("due")
        if not due or not isinstance(due, str):
            continue
        category = fields.get("category")
        deadlines.append(
            Deadline(
                title=_title_from_body(body, path.stem),
                due=due,
                category=category if isinstance(category, str) else None,
                source=str(path.relative_to(VAULT_PATH)),
            )
        )
    return deadlines


def get_deadlines(category: str | None = None) -> list[Deadline]:
    """Every known deadline, soonest first. `category` filters
    case-insensitively when given."""
    all_deadlines = _from_tasks_and_events() + _from_vault_notes()
    if category:
        all_deadlines = [d for d in all_deadlines if (d.category or "").lower() == category.lower()]
    return sorted(all_deadlines, key=lambda d: _parse_date(d.due) or datetime.max)


@tool
def list_deadlines(category: str | None = None) -> str:
    """List upcoming deadlines across every task, event, and vault note
    that declares one, soonest first.

    Args:
        category: Optional filter, e.g. "hackathon"
            (assignment/test/hackathon/application/milestone/other). Omit
            for everything.
    """
    deadlines = get_deadlines(category)
    if not deadlines:
        return f"No deadlines found{f' (category: {category})' if category else ''}."
    return "\n".join(
        f"{d.due} — {d.title}" + (f" [{d.category}]" if d.category else "") for d in deadlines
    )
