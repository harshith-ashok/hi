"""Projects: a named workspace with its own instructions and files, kept in the vault.

    <vault>/hi/projects/<slug>/PROJECT.md     frontmatter: name, description; the body is the instructions
    <vault>/hi/projects/<slug>/<any file>     files that belong to the project

A chat belongs to at most one project (`project:` in the session note, hi/memory/sessions.py); a project holds any
number of chats. The slug never changes once made, so renaming a project does not detach its chats.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import hi.config as config
from hi.memory import sessions
from hi.memory.frontmatter import dump_frontmatter, parse_frontmatter

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
FILE_NAME = re.compile(r"[\w][\w .()+-]{0,119}")
INFO_FILE = "PROJECT.md"
MAX_NAME = 80
MAX_DESCRIPTION = 300
MAX_INSTRUCTIONS = 20_000
MAX_FILE_BYTES = 200_000_000


@dataclass
class Project:
    slug: str
    name: str
    description: str = ""
    instructions: str = ""


def projects_dir() -> Path:
    return config.VAULT_PATH / "hi" / "projects"


def _folder(slug: str) -> Path:
    return projects_dir() / slug


def _one_line(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()[:limit]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-") or "project"


def _write(p: Project) -> None:
    folder = _folder(p.slug)
    folder.mkdir(parents=True, exist_ok=True)
    fields = {"name": p.name, "description": p.description, "tags": ["hi", "project"]}
    tmp = folder / "PROJECT.md.tmp"
    tmp.write_text(f"{dump_frontmatter(fields)}\n{p.instructions.strip()}\n")
    tmp.replace(folder / INFO_FILE)


def get(slug: str) -> Project | None:
    if not SLUG.fullmatch(slug):
        return None
    try:
        fields, body = parse_frontmatter((_folder(slug) / INFO_FILE).read_text())
    except OSError:
        return None
    return Project(slug, str(fields.get("name") or slug), str(fields.get("description") or ""), body.strip())


def list_projects() -> list[Project]:
    found = [p for path in sorted(projects_dir().glob(f"*/{INFO_FILE}")) if (p := get(path.parent.name))] if projects_dir().exists() else []
    return sorted(found, key=lambda p: p.name.lower())


def create(name: str, description: str = "", instructions: str = "") -> Project:
    name = _one_line(name, MAX_NAME)
    if not name:
        raise ValueError("A project needs a name.")
    slug, n = slugify(name), 2
    while _folder(slug).exists():
        slug, n = f"{slugify(name)}-{n}", n + 1
    p = Project(slug, name, _one_line(description, MAX_DESCRIPTION), instructions[:MAX_INSTRUCTIONS])
    _write(p)
    return p


def update(slug: str, name: str | None = None, description: str | None = None, instructions: str | None = None) -> Project | None:
    p = get(slug)
    if p is None:
        return None
    if name is not None:
        p.name = _one_line(name, MAX_NAME) or p.name
    if description is not None:
        p.description = _one_line(description, MAX_DESCRIPTION)
    if instructions is not None:
        p.instructions = instructions[:MAX_INSTRUCTIONS]
    _write(p)
    return p


def delete(slug: str) -> bool:
    """Remove the project and its files. Its chats are kept; they just belong to no project any more."""
    if get(slug) is None:
        return False
    sessions.unassign_project(slug)
    shutil.rmtree(_folder(slug), ignore_errors=True)
    return True


# --- files -------------------------------------------------------------------------------------------------------------

def files(slug: str) -> list[dict]:
    """[{name, size}] of the project's files (not PROJECT.md), by name."""
    folder = _folder(slug)
    if not folder.is_dir():
        return []
    return [{"name": f.name, "size": f.stat().st_size} for f in sorted(folder.iterdir())
            if f.is_file() and f.name != INFO_FILE and not f.name.endswith(".tmp") and not f.name.startswith(".")]


def valid_file_name(name: str) -> bool:
    return bool(FILE_NAME.fullmatch(name)) and name != INFO_FILE and ".." not in name


def save_file(slug: str, name: str, stream: BinaryIO) -> dict:
    """Write an uploaded file into the project, replacing one of the same name."""
    if get(slug) is None:
        raise FileNotFoundError(slug)
    if not valid_file_name(name):
        raise ValueError("That file name is not allowed.")
    target = _folder(slug) / name
    tmp = _folder(slug) / f"{name}.tmp"
    size = 0
    with tmp.open("wb") as out:
        while chunk := stream.read(1 << 20):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                tmp.unlink(missing_ok=True)
                raise ValueError("That file is too large.")
            out.write(chunk)
    tmp.replace(target)
    return {"name": name, "size": size}


def delete_file(slug: str, name: str) -> bool:
    if get(slug) is None or not valid_file_name(name):
        return False
    target = _folder(slug) / name
    if not target.is_file():
        return False
    target.unlink()
    return True


# --- what a turn in a project is told ----------------------------------------------------------------------------------

INSTRUCTION_CONTEXT_CHARS = 6000  # the context window is small: long instructions are clipped here (never in the file)
FILE_LIST_LIMIT = 40


def context_block(session: str) -> str:
    """The project's instructions and file list for a turn in `session`, or "" when the chat is in no project."""
    s = sessions.get(session)
    p = get(s.project) if s and s.project else None
    if p is None:
        return ""
    lines = [f'This chat is in the project "{p.name}" (slug: {p.slug}).']
    if p.instructions.strip():
        text = p.instructions.strip()
        clipped = text[:INSTRUCTION_CONTEXT_CHARS] + (" …[clipped]" if len(text) > INSTRUCTION_CONTEXT_CHARS else "")
        lines.append(f"Follow these project instructions:\n{clipped}")
    listed = files(p.slug)
    if listed:
        names = "\n".join(f"- {f['name']} ({f['size']:,} bytes)" for f in listed[:FILE_LIST_LIMIT])
        more = f"\n(and {len(listed) - FILE_LIST_LIMIT} more)" if len(listed) > FILE_LIST_LIMIT else ""
        lines.append(f"Project files. Open one with read_workspace_file(project='{p.slug}', name=...) when it is relevant:\n{names}{more}")
    return "\n\n".join(lines)
