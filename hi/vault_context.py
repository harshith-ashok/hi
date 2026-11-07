"""Vault-backed context for the agent: what just happened (the journal) and the
notes most related to this message, found by plain word matching on note names,
paths and text across the whole vault. No embeddings or index; reads files.

`build_context(message)` is injected into the system prompt each turn;
`search_vault` is the same search as a tool for the model to call itself.
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import tool

import hi.config as config
from hi import journal, memory, reflection_agent
from hi.frontmatter import parse_frontmatter

MAX_CONTEXT_CHARS = 8000
CONTEXT_NOTES = 5
MIN_SCORE = 3  # a word of the note's own name, or two distinct words in its text (one text hit scores 2)
SKIP_DIRS = {".obsidian", ".git", ".trash", "attachments", "node_modules"}
SKIP_PREFIXES = ("hi/conversations/", "hi/journal/", "hi/tasks/", "hi/knowledge/preferences.md")
STOPWORDS = frozenset(
    "that this with from have what when where which about would could should there their them then than into your "
    "just like want need make some more also does please tell show give find figure out write wrote written note notes "
    "wrote what did".split()
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{4,}", text.lower()) if w not in STOPWORDS}


def _notes() -> list[Path]:
    root = config.VAULT_PATH
    if not root.exists():
        return []
    return [
        p for p in root.rglob("*.md")
        if not SKIP_DIRS & set(p.relative_to(root).parts) and not p.relative_to(root).as_posix().startswith(SKIP_PREFIXES)
    ]


def _score(path: Path, words: set[str], body: str) -> int:
    """Name hits weigh most, then headings, then any other word in the text."""
    rel = path.relative_to(config.VAULT_PATH).as_posix().lower()
    headings = " ".join(line for line in body.splitlines() if line.lstrip().startswith("#"))
    return (
        3 * len(words & _words(path.stem))
        + len(words & _words(rel))
        + 2 * len(words & _words(body))
        + len(words & _words(headings))
    )


def _read(path: Path) -> str:
    try:
        return parse_frontmatter(path.read_text(errors="ignore"))[1]
    except OSError:
        return ""


def find_notes(query: str, limit: int = 3) -> list[tuple[str, str]]:
    """[(vault-relative path, snippet)] for the notes in the whole vault that best match `query`,
    by name, path and text."""
    words = _words(query)
    if not words:
        return []
    scored = []
    for path in _notes():
        body = _read(path)
        if (score := _score(path, words, body)) >= MIN_SCORE:
            scored.append((score, path, body))
    scored.sort(key=lambda t: (-t[0], str(t[1])))
    return [
        (path.relative_to(config.VAULT_PATH).as_posix(), re.sub(r"\s+", " ", body).strip()[:320])
        for _score_, path, body in scored[:limit]
    ]


def build_context(message: str) -> str:
    """Markdown block for the system prompt, or '' when there is nothing to add."""
    parts = []
    if remembered := parse_frontmatter(memory.read_memory())[1][-1800:].strip():
        parts.append("### What you remember about the user (hi/memory/memory.md)\n" + remembered)
    if loops := reflection_agent.latest_open_loops():
        parts.append("### Open loops from your last reflection\n" + loops)
    if activity := journal.recent():
        parts.append("### Recent activity (your journal)\n" + activity)
    if notes := find_notes(message, limit=CONTEXT_NOTES):
        parts.append("### Notes related to this message\n" + "\n".join(f"- [[{p.removesuffix('.md')}]]: {s}" for p, s in notes))
    return "\n\n".join(parts)[:MAX_CONTEXT_CHARS]


@tool
def search_vault(query: str) -> str:
    """Search the user's whole Obsidian vault by note name, path and text. Returns the
    best matching notes with a snippet each; read one fully with read_vault_note.

    Args:
        query: Words to look for, e.g. "kaapi deployment" or "placement resume".
    """
    found = find_notes(query, limit=6)
    if not found:
        return f"No notes matched '{query}'."
    return "\n".join(f"- {p}: {s}" for p, s in found)
