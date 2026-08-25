"""Task/Event schema for `hi`'s capture system. Both are just Markdown
notes with YAML frontmatter under <VAULT_PATH>/hi/tasks/ — the fields below
are the whole schema, no separate database, matching this project's "the
filesystem is the single source of truth" philosophy (see CLAUDE.md).
hi/capture/store.py persists/loads them; hi/frontmatter.py does the actual
(de)serialization, and its `due:`/`when:` convention is what lets any other
vault note (not just these) declare a deadline the same way.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from hi.frontmatter import dump_frontmatter, parse_frontmatter

Status = Literal["pending", "done"]

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-")[:50] or "item"


def _new_id(text: str) -> str:
    return f"{date.today().isoformat()}-{_slugify(text)}-{uuid.uuid4().hex[:6]}"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Task:
    """A to-do item — the structured replacement for the old flat
    <VAULT_PATH>/hi/todo.md checklist (see hi/agents/butler/todo.py)."""

    text: str
    status: Status = "pending"
    category: str | None = None  # assignment/test/hackathon/application/milestone/other
    priority: str | None = None  # low/medium/high
    due: str | None = None  # ISO date/datetime — hi/frontmatter.py's due: convention
    source_persona: str | None = None
    project: str | None = None
    owner: str | None = None  # team-ops: who's responsible, see hi/tracking/team_ops.py
    created: str | None = None
    id: str = ""
    kind: Literal["task"] = field(default="task", init=False)

    def __post_init__(self) -> None:
        if self.created is None:
            self.created = _now()
        if not self.id:
            self.id = _new_id(self.text)

    @property
    def filename(self) -> str:
        return f"{self.id}.md"

    def to_markdown(self) -> str:
        fields: dict[str, str | list[str]] = {
            "tags": ["hi", "task"],
            "kind": self.kind,
            "text": self.text,
            "status": self.status,
            "created": self.created or "",
        }
        for key in ("category", "priority", "due", "source_persona", "project", "owner"):
            value = getattr(self, key)
            if value:
                fields[key] = value
        return f"{dump_frontmatter(fields)}\n# {self.text}\n"

    @classmethod
    def from_markdown(cls, item_id: str, content: str) -> Task:
        fields, _body = parse_frontmatter(content)
        return cls(
            text=str(fields.get("text", "")),
            status=str(fields.get("status", "pending")),  # type: ignore[arg-type]
            category=_str_or_none(fields.get("category")),
            priority=_str_or_none(fields.get("priority")),
            due=_str_or_none(fields.get("due")),
            source_persona=_str_or_none(fields.get("source_persona")),
            project=_str_or_none(fields.get("project")),
            owner=_str_or_none(fields.get("owner")),
            created=_str_or_none(fields.get("created")),
            id=item_id,
        )


@dataclass
class Event:
    """Something happening at a specific date/time, as opposed to a Task's
    open-ended "get this done eventually"."""

    text: str
    when: str  # ISO date or datetime the event occurs
    category: str | None = None
    source_persona: str | None = None
    project: str | None = None
    created: str | None = None
    id: str = ""
    kind: Literal["event"] = field(default="event", init=False)

    def __post_init__(self) -> None:
        if self.created is None:
            self.created = _now()
        if not self.id:
            self.id = _new_id(self.text)

    @property
    def filename(self) -> str:
        return f"{self.id}.md"

    def to_markdown(self) -> str:
        fields: dict[str, str | list[str]] = {
            "tags": ["hi", "event"],
            "kind": self.kind,
            "text": self.text,
            "when": self.when,
            "created": self.created or "",
        }
        for key in ("category", "source_persona", "project"):
            value = getattr(self, key)
            if value:
                fields[key] = value
        return f"{dump_frontmatter(fields)}\n# {self.text}\n"

    @classmethod
    def from_markdown(cls, item_id: str, content: str) -> Event:
        fields, _body = parse_frontmatter(content)
        return cls(
            text=str(fields.get("text", "")),
            when=str(fields.get("when", "")),
            category=_str_or_none(fields.get("category")),
            source_persona=_str_or_none(fields.get("source_persona")),
            project=_str_or_none(fields.get("project")),
            created=_str_or_none(fields.get("created")),
            id=item_id,
        )


def _str_or_none(value: object) -> str | None:
    return str(value) if value else None


def load_item(item_id: str, content: str) -> Task | Event | None:
    """Dispatch a Markdown file's content to Task or Event based on its own
    `kind:` frontmatter, so both can share one directory (hi/capture/store.py)
    the same way hi/vault.py's knowledge notes and person notes already
    share hi/knowledge/, told apart by content rather than location."""
    fields, _body = parse_frontmatter(content)
    kind = fields.get("kind")
    if kind == "event":
        return Event.from_markdown(item_id, content)
    if kind == "task":
        return Task.from_markdown(item_id, content)
    return None
