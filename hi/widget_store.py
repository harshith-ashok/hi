"""MCP-UI widget recall (TODO.md Phase 20): persists every widget
`hi/agui_adapter.py` detects to the vault, and a `recall_widget()` tool
that lets `docs` answer "show me that again" by handing the SAME
mcp-ui-shaped content back — `_mcp_ui_widget()` (in `agui_adapter.py`)
detects it exactly the same way it detects a live tool result, so
recall reuses the existing CUSTOM-event passthrough rather than needing
a second rendering path.

Deduped by URI, not by call: `save_widget()` writes to a filename
derived from the widget's own `uri` (mcp-ui resources are already
supposed to be stable per the spec — the same `uri://...` re-served
later is the same widget, so re-saving it just overwrites the same
file rather than piling up duplicates for a widget shown twice).

**Genuinely unverified against a real MCP-UI server, same as
`agui_adapter.py`'s own widget-detection code** — no MCP server this
project has configured implements the mcp-ui extension. Tested here
only against synthetic widget content shaped like the real spec, same
honesty standard as Phase 18.
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import tool

from hi.vault import KNOWLEDGE_DIR, with_frontmatter

WIDGETS_DIR = KNOWLEDGE_DIR / "widgets"

# A vague "show me that again"-style query has no real keyword to search
# on — these all mean "the most recent one", not "search for this word".
_VAGUE_QUERY_WORDS = {
    "", "that", "it", "again", "this", "the last one", "previous",
    "the widget", "that widget", "the last widget", "that again",
    "show me that again", "show that again",
}


def _slugify(uri: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", uri.lower()).strip("-")
    return slug or "widget"


def save_widget(uri: str, mime_type: str, html: str) -> Path:
    """Persists a detected widget to `WIDGETS_DIR`, overwriting any
    earlier save for the same `uri`. Returns the note's path."""
    WIDGETS_DIR.mkdir(parents=True, exist_ok=True)
    path = WIDGETS_DIR / f"{_slugify(uri)}.md"
    content = (
        f"# MCP-UI widget: {uri}\n\n"
        f"- uri: {uri}\n"
        f"- mimeType: {mime_type}\n\n"
        f"```html\n{html}\n```\n"
    )
    path.write_text(with_frontmatter(content, ["hi", "mcp-ui-widget"]))
    return path


def _parse_widget_note(path: Path) -> dict | None:
    text = path.read_text()
    uri_match = re.search(r"^- uri: (.+)$", text, re.MULTILINE)
    mime_match = re.search(r"^- mimeType: (.+)$", text, re.MULTILINE)
    html_match = re.search(r"```html\n(.*)\n```", text, re.DOTALL)
    if not (uri_match and html_match):
        return None
    return {
        "uri": uri_match.group(1).strip(),
        "mimeType": mime_match.group(1).strip() if mime_match else "text/html",
        "text": html_match.group(1),
    }


@tool
def recall_widget(query: str) -> dict | str:
    """Recall a previously-shown MCP-UI widget (a tool's own rendered
    view — a PR diff, a booking screen, etc.) so it can be shown again
    without re-fetching it from the tool that produced it.

    Args:
        query: What the user is asking to see again — pass their own
            words (e.g. "that PR diff"), or an empty string / "that
            again" for a vague "show me that again" with nothing more
            specific to go on. A vague query returns the MOST RECENTLY
            saved widget; a specific one is matched against saved
            widgets' own URIs.
    """
    if not WIDGETS_DIR.is_dir():
        return "No widgets have been saved yet."
    saved = sorted(WIDGETS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not saved:
        return "No widgets have been saved yet."

    normalized = query.strip().lower()
    if normalized in _VAGUE_QUERY_WORDS:
        widget = _parse_widget_note(saved[0])
        return widget if widget is not None else "The most recently saved widget note is unreadable."

    for path in saved:
        if normalized in path.stem.replace("-", " "):
            widget = _parse_widget_note(path)
            if widget is not None:
                return widget

    return f"No saved widget matching '{query}'."
