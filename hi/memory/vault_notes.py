"""Finding and reading your own notes, for adding one to a chat as context.

Only Markdown and plain-text files; never the vault's own machinery (.obsidian, .git, .trash) or hi's internal folders
(sessions, transcripts, journal, backups ...). Of hi's folders only hi/knowledge and hi/projects are offered.
"""

from __future__ import annotations

import os
from pathlib import Path

import hi.config as config

SUFFIXES = {".md", ".markdown", ".txt"}
SKIP_DIRS = {".obsidian", ".git", ".trash", "node_modules", "skills"}
HI_OFFERED = {"knowledge", "projects"}
MAX_READ_CHARS = 200_000
MAX_RESULTS = 40


def _skipped_dir(parts: tuple[str, ...]) -> bool:
    """Whether the folder at `parts` (relative to the vault) is left out."""
    if any(p.startswith(".") or p in SKIP_DIRS for p in parts):
        return True
    return len(parts) > 1 and parts[0] == "hi" and parts[1] not in HI_OFFERED


def _skipped(parts: tuple[str, ...]) -> bool:
    """Whether the file at `parts` is left out: in a skipped folder, or loose in hi/ (which holds only machinery)."""
    return _skipped_dir(parts[:-1]) or (len(parts) == 2 and parts[0] == "hi")


def search(query: str = "", limit: int = MAX_RESULTS) -> list[dict]:
    """[{path, title}] of notes whose path contains every word of `query`, best match first; with no query, the most
    recently edited. `path` is relative to the vault."""
    root = config.VAULT_PATH
    if not root.is_dir():
        return []
    words = [w for w in query.lower().split() if w]
    found: list[tuple[tuple, dict]] = []
    for folder, dirs, files in os.walk(root):
        rel_folder = Path(folder).relative_to(root).parts
        dirs[:] = [d for d in dirs if not _skipped_dir((*rel_folder, d))]
        for name in files:
            if Path(name).suffix.lower() not in SUFFIXES or name.startswith("."):
                continue
            rel = (*rel_folder, name)
            path = "/".join(rel)
            lowered = path.lower()
            if not all(w in lowered for w in words):
                continue
            stem = Path(name).stem.lower()
            try:
                mtime = (root / path).stat().st_mtime
            except OSError:
                continue
            rank = (0 if words and stem.startswith(words[0]) else 1, -mtime)  # a title that starts with it, then newest
            found.append((rank, {"path": path, "title": Path(name).stem}))
    found.sort(key=lambda item: item[0])
    return [item for _rank, item in found[:limit]]


def read(path: str) -> str | None:
    """The text of the note at `path` (relative to the vault), or None when it is not an offered note."""
    root = config.VAULT_PATH.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or target.suffix.lower() not in SUFFIXES or not target.is_file():
        return None
    if _skipped(target.relative_to(root).parts):
        return None
    try:
        return target.read_text(errors="ignore")[:MAX_READ_CHARS]
    except OSError:
        return None
