"""Vault-backed storage for Task/Event items: one Markdown file per item
under <VAULT_PATH>/hi/tasks/ — both kinds share the directory, told apart
by the `kind:` field in each file's own frontmatter (hi/capture/schema.py),
the same pattern hi/vault.py already uses for knowledge vs. person notes
sharing hi/knowledge/.

Replaces the old flat <VAULT_PATH>/hi/todo.md checklist (a single file
butler read/rewrote wholesale on every change) with one file per item, so
later features (deadline aggregation, LeetCode/application trackers, etc.)
have something structured to read and write instead of a bag of checkbox
lines.
"""

from __future__ import annotations

import re
from pathlib import Path

from hi.capture.schema import Event, Task, load_item
import hi.config as config

def tasks_dir():
    return config.VAULT_PATH / "hi" / "tasks"

# The old flat TODO list this replaces — migrated in automatically the
# first time anything reads the tasks dir, then renamed so it can't be
# migrated twice.
def _legacy_todo_path():
    return config.VAULT_PATH / "hi" / "todo.md"
_LEGACY_TASK_RE = re.compile(r"^- \[( |x)\] (.*)$")

_migrated = False


def _migrate_legacy_todo() -> None:
    global _migrated
    if _migrated:
        return
    _migrated = True
    if not _legacy_todo_path().exists():
        return
    for line in _legacy_todo_path().read_text().splitlines():
        match = _LEGACY_TASK_RE.match(line)
        if not match:
            continue
        text = match.group(2).strip()
        if not text:
            continue
        done = match.group(1) == "x"
        save(Task(text=text, status="done" if done else "pending", source_persona="butler"))
    _legacy_todo_path().rename(_legacy_todo_path().with_name("todo.md.bak"))


def _load(path: Path) -> Task | Event | None:
    return load_item(path.stem, path.read_text())


def save(item: Task | Event) -> Task | Event:
    tasks_dir().mkdir(parents=True, exist_ok=True)
    (tasks_dir() / item.filename).write_text(item.to_markdown())
    return item


def delete(item_id: str) -> bool:
    path = tasks_dir() / f"{item_id}.md"
    if not path.exists():
        return False
    path.unlink()
    return True


def get(item_id: str) -> Task | Event | None:
    path = tasks_dir() / f"{item_id}.md"
    if not path.exists():
        return None
    return _load(path)


def list_items(kind: str | None = None) -> list[Task | Event]:
    """List every task/event in the vault, oldest first (filenames sort
    chronologically — see hi/capture/schema.py's id format). Runs the
    legacy-TODO migration first so a fresh vault still sees old tasks."""
    _migrate_legacy_todo()
    if not tasks_dir().exists():
        return []
    items = []
    for path in sorted(tasks_dir().glob("*.md")):
        item = _load(path)
        if item and (kind is None or item.kind == kind):
            items.append(item)
    return items


def find_task(text: str, pending_only: bool = False) -> Task | None:
    """Match a task by partial, case-insensitive text — mirrors the old
    todo.py's matching behavior for the complete/remove tools."""
    for item in list_items(kind="task"):
        if not isinstance(item, Task):
            continue
        if pending_only and item.status != "pending":
            continue
        if text.lower() in item.text.lower():
            return item
    return None
