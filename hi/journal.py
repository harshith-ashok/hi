"""The activity journal: one Markdown note per day in the vault, written by the
wrapper around the agent, not by the model.

    <VAULT_PATH>/hi/journal/YYYY-MM-DD.md

Every turn (what was asked, which tools ran and what they returned, the answer,
how long it took) and notable events (approvals, settings changes, errors) are
appended as timestamped entries. Notes a turn touched are linked as
[[wikilinks]], so they show up in Obsidian's graph and backlinks. The journal
is also the source of the "recent activity" context (hi/vault_context.py).
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import hi.config as config
from hi.frontmatter import with_frontmatter

SNIP = 160
# tool name -> (argument holding a note path, wikilink prefix inside the vault)
_NOTE_TOOLS = {
    "create_note": "hi/knowledge/", "append_note": "hi/knowledge/", "read_note": "hi/knowledge/",
    "read_vault_note": "", "save_project_to_vault": "",
}


def journal_dir() -> Path:
    return config.VAULT_PATH / "hi" / "journal"


def _day_file(day: date) -> Path:
    return journal_dir() / f"{day.isoformat()}.md"


def _snip(text: str, limit: int = SNIP) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _append(entry: str) -> None:
    path = _day_file(date.today())
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(with_frontmatter("", {"tags": ["hi", "journal"], "date": date.today().isoformat()}))
    with path.open("a") as f:
        f.write(entry)


def _links(tools: list[dict]) -> list[str]:
    links: list[str] = []
    for t in tools:
        prefix = _NOTE_TOOLS.get(t["name"])
        if prefix is None:
            continue
        try:
            note = json.loads(t.get("args") or "{}").get("path")
        except json.JSONDecodeError:
            note = None
        if note:
            link = f"[[{prefix}{note}".removesuffix(".md") + "]]"
            if link not in links:
                links.append(link)
    return links


def record_turn(persona: str, tier: str, ask: str, answer: str, tools: list[dict], seconds: float) -> None:
    """tools: [{"name", "args" (JSON string), "result"}] in call order."""
    lines = [f"## {datetime.now():%H:%M} · {persona}/{tier} · {seconds:.1f}s", f"**Asked:** {_snip(ask, 400)}"]
    for t in tools:
        lines.append(f"- `{t['name']}` {_snip(t.get('args', ''), 100)} → {_snip(t.get('result', ''))}")
    lines.append(f"**Answered:** {_snip(answer, 500)}")
    if links := _links(tools):
        lines.append("**Notes:** " + " ".join(links))
    _append("\n".join(lines) + "\n\n")


def record_event(kind: str, text: str) -> None:
    """A non-turn happening: approval, settings change, error, ..."""
    _append(f"## {datetime.now():%H:%M} · {kind}\n{_snip(text, 400)}\n\n")


def recent(max_entries: int = 6) -> str:
    """The newest journal entries (today, topped up from yesterday) as one line
    each — what just happened, for use as context."""
    entries: list[str] = []
    for day in (date.today(), date.today() - timedelta(days=1)):
        path = _day_file(day)
        if not path.exists():
            continue
        for block in reversed(path.read_text().split("\n## ")[1:]):
            head, *body = block.strip().splitlines()
            asked = next((b.removeprefix("**Asked:** ") for b in body if b.startswith("**Asked:**")), "")
            tools = ", ".join(re.findall(r"^- `(\w+)`", "\n".join(body), re.MULTILINE))
            entries.append(f"{day:%m-%d} {head}" + (f" — {_snip(asked, 90)}" if asked else "") + (f" [{tools}]" if tools else ""))
            if len(entries) >= max_entries:
                return "\n".join(reversed(entries))
    return "\n".join(reversed(entries))
