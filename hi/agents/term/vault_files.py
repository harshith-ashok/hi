"""Read-write access to the whole vault (not just hi/): the user's own notes.

Paths are relative to the vault root, e.g. "Projects/Kaapi.md" (the `.md` may be left off). Text files only,
and never the vault's own machinery (.obsidian, .git, .trash). Every change to a file that already exists
first copies the old version to hi/backups/<timestamp>/<path>, so an edit can always be undone. Replacing a
whole existing note asks for confirmation; a targeted edit or an append does not.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

import hi.config as config
from hi.action_tiers import confirm_destructive

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".canvas", ".csv", ".json", ".yaml", ".yml", ".base"}
PROTECTED_DIRS = {".obsidian", ".git", ".trash", "node_modules"}
BACKUP_DIR = "hi/backups"
LIST_LIMIT = 300


def resolve(path: str, *, must_exist: bool = False) -> Path:
    """The file `path` names inside the vault. Raises ValueError for anything that escapes the vault, touches
    its machinery, the backups, or is not a text file."""
    root = config.VAULT_PATH.resolve()
    target = (root / path).resolve()
    if not target.suffix:
        target = target.with_name(target.name + ".md")
    if not target.is_relative_to(root) or target == root:
        raise ValueError(f"'{path}' is outside the vault")
    rel = target.relative_to(root)
    if PROTECTED_DIRS & set(rel.parts) or rel.as_posix().startswith(BACKUP_DIR + "/"):
        raise ValueError(f"'{path}' is not editable (vault machinery or backups)")
    if target.suffix.lower() not in TEXT_SUFFIXES:
        raise ValueError(f"'{path}' is not a text file I can edit")
    if must_exist and not target.is_file():
        raise ValueError(f"'{path}' does not exist")
    return target


def back_up(target: Path) -> Path | None:
    """Copy `target` into hi/backups/<timestamp>/ before it changes; None if it does not exist yet."""
    if not target.is_file():
        return None
    root = config.VAULT_PATH.resolve()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    copy = root / BACKUP_DIR / stamp / target.relative_to(root)
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(target.read_bytes())
    return copy


def _relative(target: Path) -> str:
    return target.relative_to(config.VAULT_PATH.resolve()).as_posix()


@tool
def list_vault_folder(folder: str = "") -> str:
    """List one folder of the user's vault (not recursive): its sub-folders and files.

    Args:
        folder: Folder relative to the vault root; empty for the root.
    """
    root = config.VAULT_PATH.resolve()
    target = (root / folder).resolve()
    if not target.is_relative_to(root) or not target.is_dir():
        return f"'{folder}' is not a folder in the vault."
    rows = []
    for entry in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if entry.name.startswith(".") or entry.name in PROTECTED_DIRS:
            continue
        rows.append(f"[dir] {entry.name}/" if entry.is_dir() else f"[file] {entry.name}")
    shown = rows[:LIST_LIMIT] + ([f"... ({len(rows) - LIST_LIMIT} more)"] if len(rows) > LIST_LIMIT else [])
    return "\n".join(shown) or "(empty folder)"


@tool
def write_vault_note(path: str, content: str) -> str:
    """Create a note anywhere in the user's vault, or replace an existing one entirely. Replacing asks the user
    to confirm and keeps a backup; for a small change to an existing note use edit_vault_note instead.

    Args:
        path: Path relative to the vault root, e.g. "Projects/Kaapi.md".
        content: The whole note.
    """
    try:
        target = resolve(path)
    except ValueError as e:
        return str(e)
    exists = target.is_file()
    if exists and not confirm_destructive(f"replace the whole note '{_relative(target)}' (a backup is kept)"):
        return f"Cancelled: '{_relative(target)}' was not changed."
    back_up(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"{'Replaced' if exists else 'Created'} '{_relative(target)}'."


@tool
def edit_vault_note(path: str, old_text: str, new_text: str) -> str:
    """Replace one exact, unique piece of text in an existing vault note. Read the note first so old_text matches
    exactly. Fails with no change if old_text is missing or appears more than once (add surrounding lines).

    Args:
        path: Path relative to the vault root.
        old_text: Exact text to find; must appear exactly once.
        new_text: What to put there.
    """
    try:
        target = resolve(path, must_exist=True)
    except ValueError as e:
        return str(e)
    text = target.read_text()
    count = text.count(old_text) if old_text else 0
    if count != 1:
        return (f"old_text was not found in '{_relative(target)}'." if count == 0
                else f"old_text appears {count} times in '{_relative(target)}'; include more context.")
    back_up(target)
    target.write_text(text.replace(old_text, new_text, 1))
    return f"Edited '{_relative(target)}'."


@tool
def append_vault_note(path: str, content: str) -> str:
    """Add text to the end of a vault note, creating the note if it does not exist.

    Args:
        path: Path relative to the vault root.
        content: Markdown to add.
    """
    try:
        target = resolve(path)
    except ValueError as e:
        return str(e)
    back_up(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text() if target.is_file() else ""
    separator = "" if not existing or existing.endswith("\n") else "\n"
    target.write_text(existing + separator + content + ("" if content.endswith("\n") else "\n"))
    return f"Appended to '{_relative(target)}'."


@tool
def move_vault_note(path: str, new_path: str) -> str:
    """Move or rename a vault note. Refuses to overwrite an existing note. Links in other notes are not rewritten.

    Args:
        path: Current path relative to the vault root.
        new_path: New path relative to the vault root.
    """
    try:
        source, dest = resolve(path, must_exist=True), resolve(new_path)
    except ValueError as e:
        return str(e)
    if dest.exists():
        return f"'{_relative(dest)}' already exists; nothing moved."
    dest.parent.mkdir(parents=True, exist_ok=True)
    source.rename(dest)
    return f"Moved '{_relative(source)}' to '{_relative(dest)}'."


VAULT_TOOLS = [list_vault_folder, write_vault_note, edit_vault_note, append_vault_note, move_vault_note]
