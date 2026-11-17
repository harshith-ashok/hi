"""The context a background run is given, assembled from the vault and (when allowed) the screen.

This is what makes a run useful without you: it knows what is due, what is open, what you were doing and what it
already prepared. Each part is capped and redacted. The screen part is only included for a local model (screen text
never goes to a hosted one), and is left out, with a note, when the screen is paused or private.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from hi.core.redact import redact
from hi.llm import registry

SECTION_CHARS = 2500
TASK_LIMIT = 8
DUE_WITHIN_DAYS = 2
PAUSED_MARKER = "Screen context is paused or hidden"


@dataclass
class ContextPack:
    text: str = ""
    screen_included: bool = False
    sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # what was left out and why, for the run log


def _clip(text: str, limit: int = SECTION_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + " …"


def _parse(value: str | None) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value or "", fmt)
        except ValueError:
            continue
    return None


def _due_tasks(now: datetime) -> str:
    from hi.capture.schema import Task
    from hi.capture.store import list_items

    horizon = now + timedelta(days=DUE_WITHIN_DAYS)
    rows = []
    for item in list_items(kind="task"):
        if isinstance(item, Task) and item.status == "pending" and (due := _parse(item.due)) and due <= horizon:
            rows.append((due, f"- {'OVERDUE ' if due < now.replace(hour=0, minute=0) else ''}{item.due}: {item.text}"))
    return "\n".join(line for _, line in sorted(rows)[:TASK_LIMIT])


def _deadlines(now: datetime) -> str:
    from hi.tracking.deadlines import get_deadlines

    horizon = now + timedelta(days=DUE_WITHIN_DAYS + 1)
    return "\n".join(
        f"- {d.due}: {d.title}" for d in get_deadlines()
        if (due := _parse(d.due)) and now.replace(hour=0, minute=0) <= due <= horizon
    )[:SECTION_CHARS]


def _vault_sections(query: str, now: datetime) -> list[tuple[str, str]]:
    from hi.context.weekday import todays_context_note
    from hi.memory import journal, reflection, reports
    from hi.memory.context import build_context

    return [
        ("Due soon (tasks)", _due_tasks(now)),
        ("Deadlines", _deadlines(now)),
        ("Open loops from yesterday's reflection", reflection.latest_open_loops()),
        ("Recent activity (journal)", journal.recent(8) or ""),
        (f"Notes for {now:%A}", todays_context_note() or ""),
        ("Notes that match the task", build_context(query) if query else ""),
        ("Already prepared recently (do not prepare these again)", "\n".join(f"- {h}" for h in reports.recent_headlines(8))),
    ]


def _screen_sections() -> list[tuple[str, str]]:
    from hi.context import now as live

    described = live.describe(include_screen=True)
    if not described or described.startswith(PAUSED_MARKER):
        return []
    return [("What the user is doing right now", described), ("The last half hour", live.recent_activity(30))]


def build(parts: set[str] | frozenset[str] | list[str], query: str = "", tier: str = "sonnet",
          now: datetime | None = None) -> ContextPack:
    """The context for a run. `parts` may contain "vault" and "screen"."""
    now = now or datetime.now()
    parts = set(parts)
    pack = ContextPack()
    sections: list[tuple[str, str]] = [("Now", f"{now:%A %d %B %Y, %H:%M}")]
    if "vault" in parts:
        sections += _vault_sections(query, now)
        pack.sources.append("vault")
    if "screen" in parts:
        if not registry.is_local(tier):
            pack.notes.append(f"screen left out: the {tier} tier is not a local model")
        else:
            screen = _screen_sections()
            if screen:
                sections += screen
                pack.screen_included = True
                pack.sources.append("screen")
            else:
                pack.notes.append("screen left out: no live context (paused, private, or the daemon is not running)")
    body = "\n\n".join(f"### {title}\n{_clip(text)}" for title, text in sections if text and text.strip())
    pack.text = redact("\n\n## Context (assembled automatically for this background run)\n\n" + body) if body else ""
    return pack
