"""Shared Markdown memory, stored inside the user's Obsidian vault
(hi/config.VAULT_PATH) under a dedicated hi/ namespace so it stays separate
from the rest of the vault:

    <VAULT_PATH>/hi/knowledge/...       durable notes, any persona
    <VAULT_PATH>/hi/conversations/...   one dated log per day, every persona

Every note and conversation log carries Obsidian-compatible YAML frontmatter
tagged "hi" (plus "conversation" for logs), so the vault's own tag search
finds them like any other note.
"""

from datetime import date, datetime
from pathlib import Path

from langchain_core.tools import tool

from hi.config import VAULT_PATH
from hi.frontmatter import with_frontmatter as _build_frontmatter

KNOWLEDGE_DIR = VAULT_PATH / "hi" / "knowledge"
CONVERSATIONS_DIR = VAULT_PATH / "hi" / "conversations"


def _resolve_path(base_dir: Path, path: str) -> Path:
    resolved = (base_dir / path).resolve()
    if not resolved.is_relative_to(base_dir.resolve()):
        raise ValueError(f"Invalid path: {path}")
    return resolved


def with_frontmatter(content: str, tags: list[str], due: str | None = None) -> str:
    fields: dict[str, str | list[str]] = {"tags": tags}
    if due:
        fields["due"] = due
    return _build_frontmatter(content, fields)


@tool
def create_note(path: str, content: str, due: str | None = None) -> str:
    """Create a new Markdown note inside the vault's hi/knowledge/ folder,
    overwriting it if it exists.

    Args:
        path: Relative path for the note, e.g. "projects/kaapi.md".
        content: Markdown content to write to the note.
        due: Optional ISO date/datetime (e.g. "2026-09-10") if this note
            represents something with a deadline — any vault note can
            declare one this way via frontmatter, no separate entry system.
    """
    note_path = _resolve_path(KNOWLEDGE_DIR, path)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(with_frontmatter(content, ["hi"], due=due))
    return f"Created note '{path}'."


@tool
def append_note(path: str, content: str) -> str:
    """Append Markdown content to a note inside the vault's hi/knowledge/
    folder, creating it (with frontmatter) if needed.

    Args:
        path: Relative path for the note, e.g. "preferences.md".
        content: Markdown content to append.
    """
    note_path = _resolve_path(KNOWLEDGE_DIR, path)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    if not note_path.exists():
        note_path.write_text(with_frontmatter("", ["hi"]))
    with note_path.open("a") as f:
        if note_path.stat().st_size > 0:
            f.write("\n")
        f.write(content)
    return f"Appended to note '{path}'."


@tool
def read_note(path: str) -> str:
    """Read the contents of a note inside the vault's hi/knowledge/ folder.

    Args:
        path: Relative path for the note, e.g. "ideas.md".
    """
    note_path = _resolve_path(KNOWLEDGE_DIR, path)
    if not note_path.exists():
        return f"Note '{path}' does not exist."
    return note_path.read_text()


@tool
def list_notes() -> str:
    """List all existing notes inside the vault's hi/knowledge/ folder."""
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    notes = sorted(str(p.relative_to(KNOWLEDGE_DIR)) for p in KNOWLEDGE_DIR.rglob("*.md"))
    if not notes:
        return "No notes exist yet."
    return "\n".join(notes)


def _resolve_conversation_path(conversation_date: str) -> Path:
    return _resolve_path(CONVERSATIONS_DIR, f"{conversation_date}.md")


@tool
def list_conversations() -> str:
    """List the dates of all logged conversations inside the vault's
    hi/conversations/ folder."""
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    dates = sorted(p.stem for p in CONVERSATIONS_DIR.glob("*.md"))
    if not dates:
        return "No conversation logs exist yet."
    return "\n".join(dates)


@tool
def read_conversation(date: str) -> str:
    """Read the logged conversation for a given date.

    Args:
        date: Date of the log in YYYY-MM-DD format, e.g. "2026-07-20".
    """
    log_path = _resolve_conversation_path(date)
    if not log_path.exists():
        return f"No conversation log for '{date}'."
    return log_path.read_text()


def log_conversation(persona: str, user_message: str, assistant_message: str) -> None:
    """Append a user/assistant exchange to today's conversation log,
    tagging it with the persona that produced it."""
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = CONVERSATIONS_DIR / f"{date.today().isoformat()}.md"
    if not log_path.exists():
        log_path.write_text(with_frontmatter("", ["hi", "conversation"]))
    with log_path.open("a") as f:
        f.write(f"## {datetime.now().strftime('%H:%M:%S')} — {persona}\n\n")
        f.write(f"**User:** {user_message}\n\n")
        f.write(f"**Assistant:** {assistant_message}\n\n")
