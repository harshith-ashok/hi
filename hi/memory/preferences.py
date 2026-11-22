"""Your standing preferences: <vault>/hi/knowledge/preferences.md.

The term agent reads this file on every model call (hi/agents/term/term.py), so an edit applies to the next reply with no
restart. The file is plain Markdown with the usual `tags: [hi]` frontmatter; `hi` also appends to it when you ask it to
remember a preference.
"""

from __future__ import annotations

from hi.memory.frontmatter import dump_frontmatter, parse_frontmatter
from hi.memory.vault import knowledge_dir

FILE = "preferences.md"
MAX_CHARS = 8000  # it rides in every prompt, and the context window is small


def path():
    return knowledge_dir() / FILE


def read() -> str:
    """The preferences as text, without the frontmatter ("" when there is no file)."""
    try:
        return parse_frontmatter(path().read_text())[1].strip()
    except OSError:
        return ""


def write(text: str) -> None:
    """Replace the preferences. Blank text removes the file, so the prompt has no empty section."""
    text = text.strip()
    if len(text) > MAX_CHARS:
        raise ValueError(f"Preferences are limited to {MAX_CHARS:,} characters: they are sent with every message.")
    target = path()
    if not text:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(f"{dump_frontmatter({'tags': ['hi']})}\n{text}\n")
    tmp.replace(target)
