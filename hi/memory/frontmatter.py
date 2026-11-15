"""Minimal YAML-subset frontmatter reader/writer shared by every vault file
`hi` writes (knowledge notes, conversation logs, person notes, tasks/
events). Deliberately not a full YAML parser — Obsidian-compatible
frontmatter here is always a flat block of `key: value` pairs plus one
`tags: [a, b]`-style list, which a couple of regexes handle without adding
a YAML dependency.

Convention: any vault note — not just tasks — can declare `due: <ISO date
or datetime>` in its frontmatter to mark a deadline, with no separate entry
system. hi/capture/schema.py's Task is the canonical example (also used by
Event's `when:`); a future deadline tracker can scan the whole vault for
this same key rather than needing its own storage.
"""

from __future__ import annotations

import re

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n\n?", re.DOTALL)
_LIST_RE = re.compile(r"^\[(.*)\]$")

FrontmatterValue = str | list[str]


def parse_frontmatter(content: str) -> tuple[dict[str, FrontmatterValue], str]:
    """Split `content` into (frontmatter fields, body). Returns ({}, content)
    unchanged if there's no frontmatter block."""
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content
    fields: dict[str, FrontmatterValue] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        list_match = _LIST_RE.match(value)
        if list_match:
            fields[key] = [v.strip() for v in list_match.group(1).split(",") if v.strip()]
        else:
            fields[key] = value
    return fields, content[match.end() :]


def dump_frontmatter(fields: dict[str, FrontmatterValue]) -> str:
    """Render `fields` as a `---`-delimited frontmatter block (no trailing
    body) — a list value renders as `key: [a, b]`, everything else as a
    plain scalar."""
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list):
            lines.append(f"{key}: [{', '.join(str(v) for v in value)}]")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---\n")
    return "\n".join(lines)


def with_frontmatter(content: str, fields: dict[str, FrontmatterValue]) -> str:
    """Prefix `content` with a frontmatter block, unless it already starts
    with one (idempotent — a caller that already built its own frontmatter
    block is left alone rather than double-wrapped)."""
    if content.startswith("---\n"):
        return content
    return f"{dump_frontmatter(fields)}\n{content}"
