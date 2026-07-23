from datetime import date, datetime
from pathlib import Path

from langchain_core.tools import tool

MEMORY_DIR = Path.home() / ".hi" / "memory"
CONVERSATIONS_DIR = MEMORY_DIR / "conversations"
KNOWLEDGE_DIR = MEMORY_DIR / "knowledge"


def _resolve_knowledge_path(path: str) -> Path:
    note_path = (KNOWLEDGE_DIR / path).resolve()
    if not note_path.is_relative_to(KNOWLEDGE_DIR.resolve()):
        raise ValueError(f"Invalid note path: {path}")
    return note_path


@tool
def create_note(path: str, content: str) -> str:
    """Create a new Markdown note inside ~/.hi/memory/knowledge/, overwriting it if it exists.

    Args:
        path: Relative path for the note, e.g. "projects/kaapi.md".
        content: Markdown content to write to the note.
    """
    note_path = _resolve_knowledge_path(path)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(content)
    return f"Created note '{path}'."


@tool
def append_note(path: str, content: str) -> str:
    """Append Markdown content to a note inside ~/.hi/memory/knowledge/, creating it if needed.

    Args:
        path: Relative path for the note, e.g. "preferences.md".
        content: Markdown content to append.
    """
    note_path = _resolve_knowledge_path(path)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = note_path.exists() and note_path.stat().st_size > 0
    with note_path.open("a") as f:
        if needs_newline:
            f.write("\n")
        f.write(content)
    return f"Appended to note '{path}'."


@tool
def read_note(path: str) -> str:
    """Read the contents of a note inside ~/.hi/memory/knowledge/.

    Args:
        path: Relative path for the note, e.g. "ideas.md".
    """
    note_path = _resolve_knowledge_path(path)
    if not note_path.exists():
        return f"Note '{path}' does not exist."
    return note_path.read_text()


@tool
def list_notes() -> str:
    """List all existing notes inside ~/.hi/memory/knowledge/."""
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    notes = sorted(str(p.relative_to(KNOWLEDGE_DIR)) for p in KNOWLEDGE_DIR.rglob("*.md"))
    if not notes:
        return "No notes exist yet."
    return "\n".join(notes)


def _resolve_conversation_path(date: str) -> Path:
    log_path = (CONVERSATIONS_DIR / f"{date}.md").resolve()
    if not log_path.is_relative_to(CONVERSATIONS_DIR.resolve()):
        raise ValueError(f"Invalid date: {date}")
    return log_path


@tool
def list_conversations() -> str:
    """List the dates of all logged conversations inside ~/.hi/memory/conversations/."""
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


def log_conversation(user_message: str, assistant_message: str) -> None:
    """Append a user/assistant exchange to today's conversation log."""
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = CONVERSATIONS_DIR / f"{date.today().isoformat()}.md"
    with log_path.open("a") as f:
        f.write(f"## {datetime.now().strftime('%H:%M:%S')}\n\n")
        f.write(f"**User:** {user_message}\n\n")
        f.write(f"**Assistant:** {assistant_message}\n\n")
