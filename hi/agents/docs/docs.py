from pathlib import Path

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_ollama import ChatOllama

VAULT_DIR = Path.home() / ".hi" / "vault"


def _resolve_vault_path(path: str) -> Path:
    note_path = (VAULT_DIR / path).resolve()
    if not note_path.is_relative_to(VAULT_DIR.resolve()):
        raise ValueError(f"Invalid note path: {path}")
    return note_path


@tool
def create_note(path: str, content: str) -> str:
    """Create a new Markdown note inside ~/.hi/vault/, overwriting it if it exists.

    Args:
        path: Relative path for the note, e.g. "os/virtual-memory.md".
        content: Markdown content to write to the note.
    """
    note_path = _resolve_vault_path(path)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(content)
    return f"Created note '{path}'."


@tool
def append_note(path: str, content: str) -> str:
    """Append Markdown content to a note inside ~/.hi/vault/, creating it if needed.

    Args:
        path: Relative path for the note, e.g. "lectures/2026-07-20.md".
        content: Markdown content to append.
    """
    note_path = _resolve_vault_path(path)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = note_path.exists() and note_path.stat().st_size > 0
    with note_path.open("a") as f:
        if needs_newline:
            f.write("\n")
        f.write(content)
    return f"Appended to note '{path}'."


@tool
def read_note(path: str) -> str:
    """Read the contents of a note inside ~/.hi/vault/.

    Args:
        path: Relative path for the note, e.g. "ideas.md".
    """
    note_path = _resolve_vault_path(path)
    if not note_path.exists():
        return f"Note '{path}' does not exist."
    return note_path.read_text()


@tool
def list_notes() -> str:
    """List all existing notes inside ~/.hi/vault/."""
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    notes = sorted(str(p.relative_to(VAULT_DIR)) for p in VAULT_DIR.rglob("*.md"))
    if not notes:
        return "No notes exist yet."
    return "\n".join(notes)


model = ChatOllama(
    model="gpt-oss:120b-cloud",
    temperature=0,
)

PROMPT_PATH = Path(__file__).parent / "docs_prompt.md"

agent = create_agent(
    model=model,
    tools=[create_note, append_note, read_note, list_notes],
    system_prompt=PROMPT_PATH.read_text(),
)
