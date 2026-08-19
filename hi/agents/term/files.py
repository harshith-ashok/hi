"""General-purpose filesystem access for `term` — reading/listing/
searching files on disk directly (plain `pathlib`/`os`/`subprocess`, no
shell command, no tmux dependency), which nothing in this codebase had
before. `hi/vault.py`'s note tools are hard-scoped to
`<VAULT_PATH>/hi/knowledge/`; `run_shell_command` needs a live tmux pane
(`hi/agents/term/shell_pane.py`'s `_own_pane_id()` raises outright
without one), which makes it entirely unusable from the voice
companion's IPC path (`hi/ipc/server.py` has no tmux context at all).
These tools work the same way `hi/agents/term/resume.py`'s
`resume_context` already does — direct subprocess/pathlib calls, proven
to work fine outside tmux — not a new pattern. See `BLOCKERS.md` #1/#2
for the full reasoning behind why this was missing.

Relative paths resolve against `HI_LAUNCH_CWD` (the directory `hi` was
launched from) so "read the README" doesn't need a spelled-out path.
Deliberately no sandboxing beyond that: `run_shell_command` already has
unrestricted filesystem access on this single-user, local-only tool, so
a *read-only* file tool is strictly less powerful than what already
exists — adding an artificial boundary here would be security theater,
not real safety.

`write_project_file`/`edit_project_file` (TODO.md Phase 13, "propose and
apply real file edits, not just read") extend this from read-only to
real mutation, using the same tiering `hi/action_tiers.py` already
established for non-shell tools: creating a brand-new file is
reversible (trivially undone by deleting it) so it's ungated, same as
`create_note`; overwriting an *existing* file's whole content is
destructive (the old content is gone, not recoverable through this tool
afterward) so it goes through `confirm_destructive()`, the same y/N gate
`run_shell_command` already uses for a destructive shell command — one
shared mechanism, not a second one invented here. `edit_project_file` is
a targeted, Edit-tool-style find/replace instead (fails loudly if
`old_text` isn't found or isn't unique, rather than guessing) — that
class of edit is trivially reversible by swapping the two arguments
back, and the exact text removed is always visible in the tool call
itself, so it stays ungated too, matching `append_note`'s reasoning.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from langchain_core.tools import tool

from hi.action_tiers import confirm_destructive

LAUNCH_CWD_ENV_VAR = "HI_LAUNCH_CWD"

# Skipped when walking a directory that isn't a git repo (git repos get
# this for free via `git ls-files --exclude-standard`, see
# _git_tracked_files below) — the common noise directories nobody ever
# means to search through.
_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    "target",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}

_MAX_READ_BYTES = 200_000
_MAX_LIST_ENTRIES = 300
_MAX_SEARCH_RESULTS = 50


def _base_dir() -> Path:
    launch_cwd = os.environ.get(LAUNCH_CWD_ENV_VAR)
    return Path(launch_cwd) if launch_cwd else Path.cwd()


def _resolve(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = _base_dir() / p
    return p.resolve()


def _looks_binary(sample: bytes) -> bool:
    return b"\x00" in sample


@tool
def read_project_file(path: str) -> str:
    """Read a text file from disk — a project's README, source code,
    config, anything. Relative paths resolve against the directory `hi`
    was launched from. Not scoped to the vault; use this for real
    project files. Refuses binary files and truncates very large ones.

    Args:
        path: File path, e.g. "README.md" or "src/main.py". Relative or absolute.
    """
    resolved = _resolve(path)
    if not resolved.exists():
        return f"'{path}' does not exist (resolved to {resolved})."
    if not resolved.is_file():
        return f"'{path}' is not a file."

    try:
        raw = resolved.read_bytes()
    except OSError as e:
        return f"Failed to read '{path}': {e}"

    if _looks_binary(raw[:8000]):
        return f"'{path}' looks like a binary file — not readable as text."

    truncated = len(raw) > _MAX_READ_BYTES
    text = raw[:_MAX_READ_BYTES].decode("utf-8", errors="replace")
    if truncated:
        text += f"\n\n... (truncated, {len(raw):,} bytes total, showing first {_MAX_READ_BYTES:,})"
    return text


@tool
def list_project_files(path: str = ".") -> str:
    """List the contents of a directory — a project's top-level
    structure, or any subdirectory. Not recursive; use search_files to
    find something across a whole project. Relative paths resolve
    against the directory `hi` was launched from.

    Args:
        path: Directory path, e.g. "." or "src". Relative or absolute.
    """
    resolved = _resolve(path)
    if not resolved.is_dir():
        return f"'{path}' is not a directory (resolved to {resolved})."

    entries = sorted(resolved.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    lines = []
    for entry in entries:
        if entry.name in _SKIP_DIRS:
            continue
        kind = "dir" if entry.is_dir() else "file"
        size = "" if entry.is_dir() else f", {entry.stat().st_size:,}B"
        lines.append(f"[{kind}] {entry.name}{size}")

    if len(lines) > _MAX_LIST_ENTRIES:
        shown = lines[:_MAX_LIST_ENTRIES]
        shown.append(f"... ({len(lines) - _MAX_LIST_ENTRIES} more not shown)")
        lines = shown
    return "\n".join(lines) if lines else "(empty directory)"


def _is_git_repo(directory: Path) -> bool:
    return (directory / ".git").is_dir()


def _git_tracked_files(directory: Path) -> list[Path] | None:
    """Tracked + untracked-but-not-ignored files, if `directory` is a git
    repo — the cheapest possible .gitignore-respecting file list, reusing
    git itself rather than reimplementing gitignore parsing. Returns None
    if `directory` isn't a git repo (or `git` fails), signaling the
    caller should fall back to a plain directory walk."""
    if not _is_git_repo(directory):
        return None
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=directory,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return [directory / line for line in result.stdout.splitlines() if line]


def _walk_files(directory: Path) -> list[Path]:
    tracked = _git_tracked_files(directory)
    if tracked is not None:
        return [p for p in tracked if p.is_file()]
    files = []
    for root, dirs, filenames in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        files.extend(Path(root) / name for name in filenames)
    return files


@tool
def search_files(query: str, path: str = ".", mode: str = "name") -> str:
    """Search for files by name or content within a project. Respects
    .gitignore when the target is a git repo (reuses `git ls-files`);
    otherwise skips common noise directories (node_modules, __pycache__,
    .venv, build output, etc.) automatically.

    Args:
        query: What to search for — a filename fragment for mode="name",
            or plain text for mode="content".
        path: Directory to search within. Defaults to the current project.
        mode: "name" (default) or "content".
    """
    if mode not in ("name", "content"):
        return "Invalid mode. Use 'name' or 'content'."

    resolved = _resolve(path)
    if not resolved.is_dir():
        return f"'{path}' is not a directory (resolved to {resolved})."

    files = _walk_files(resolved)

    if mode == "name":
        query_lower = query.lower()
        matches = [f for f in files if query_lower in f.name.lower()]
        if not matches:
            return f"No files matching '{query}' found under {path}."
        lines = [str(f.relative_to(resolved)) for f in matches[:_MAX_SEARCH_RESULTS]]
        if len(matches) > _MAX_SEARCH_RESULTS:
            lines.append(f"... ({len(matches) - _MAX_SEARCH_RESULTS} more not shown)")
        return "\n".join(lines)

    # mode == "content"
    results = []
    for f in files:
        if len(results) >= _MAX_SEARCH_RESULTS:
            break
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        if _looks_binary(raw[:8000]):
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if query.lower() in line.lower():
                results.append(f"{f.relative_to(resolved)}:{i}: {line.strip()[:200]}")
                if len(results) >= _MAX_SEARCH_RESULTS:
                    break

    if not results:
        return f"No content matches for '{query}' found under {path}."
    if len(results) >= _MAX_SEARCH_RESULTS:
        results.append("... (more results not shown, narrow your search)")
    return "\n".join(results)


@tool
def write_project_file(path: str, content: str) -> str:
    """Create a new file, or fully overwrite an existing one, with
    `content`. Relative paths resolve against the directory `hi` was
    launched from; parent directories are created as needed. Overwriting
    a file that already exists asks for a y/N confirmation first (its old
    content is replaced wholesale and isn't recoverable through this tool
    afterward) — creating a brand-new file is not gated. For a small,
    targeted change to an existing file, prefer edit_project_file
    instead of reading the whole thing and rewriting it here.

    Args:
        path: File path to write. Relative or absolute.
        content: The full file content to write.
    """
    resolved = _resolve(path)
    if resolved.exists() and not resolved.is_file():
        return f"'{path}' exists and is not a file — refusing to overwrite it."

    exists = resolved.exists()
    if exists:
        old_size = resolved.stat().st_size
        if not confirm_destructive(f"overwrite '{path}' ({old_size:,}B) with new content ({len(content):,} chars)"):
            return f"Not written — user declined: {path}"

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content)
    except OSError as e:
        return f"Failed to write '{path}': {e}"
    return f"{'Overwrote' if exists else 'Created'} '{path}' ({len(content):,} chars)."


@tool
def edit_project_file(path: str, old_text: str, new_text: str) -> str:
    """Replace one exact, unique occurrence of `old_text` with `new_text`
    in an existing file — a targeted edit, not a full rewrite. Read the
    file first (read_project_file) so `old_text` matches exactly,
    whitespace included. Fails with no changes made if `old_text` isn't
    found, or is found more than once in the file — in that case, include
    more surrounding lines in `old_text` to make it unique rather than
    retrying blindly.

    Args:
        path: Existing file to edit. Relative or absolute.
        old_text: Exact text to find — must appear exactly once in the file.
        new_text: Text to replace it with.
    """
    resolved = _resolve(path)
    if not resolved.exists():
        return f"'{path}' does not exist (resolved to {resolved}) — use write_project_file to create it."
    if not resolved.is_file():
        return f"'{path}' is not a file."

    try:
        raw = resolved.read_bytes()
    except OSError as e:
        return f"Failed to read '{path}': {e}"
    if _looks_binary(raw[:8000]):
        return f"'{path}' looks like a binary file — not editable as text."

    text = raw.decode("utf-8", errors="replace")
    count = text.count(old_text)
    if count == 0:
        return f"old_text not found in '{path}' — re-read the file to get an exact match, whitespace included."
    if count > 1:
        return f"old_text appears {count} times in '{path}' — include more surrounding context to make it unique."

    new_text_content = text.replace(old_text, new_text, 1)
    try:
        resolved.write_text(new_text_content)
    except OSError as e:
        return f"Failed to write '{path}': {e}"
    return f"Edited '{path}' (1 occurrence replaced)."
