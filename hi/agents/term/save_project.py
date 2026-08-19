"""Save a project's README/manifest/structure to the vault as a real,
structured knowledge note (`BLOCKERS.md` #3) — "save this project to the
vault" had no dedicated tool before this; the model had to improvise
reading files via a shell command (blocked outside tmux, see
`hi/agents/term/files.py`'s docstring) and guessing a `create_note` call
— a multi-step chain unreliable enough that it "almost never worked."

Follows the same "tool gathers real content, one internal model call
synthesizes, the tool writes" shape `hi/capture/ambient.py`'s
`normalize_ambient()` already established, for the same reason: one
reliable tool call beats hoping the outer agent chains several tool
calls together correctly on its own every time.
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from hi.agents.term.files import _SKIP_DIRS, _base_dir, _resolve
from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model
from hi.vault import KNOWLEDGE_DIR, with_frontmatter

PROJECTS_DIR = KNOWLEDGE_DIR / "projects"

_README_NAMES = ("README.md", "README", "readme.md", "Readme.md")
_MANIFEST_NAMES = (
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Gemfile",
    "composer.json",
)
_MAX_README_CHARS = 20_000
_MAX_MANIFEST_CHARS = 5_000
_MAX_STRUCTURE_ENTRIES = 60


def _find_first(directory: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "project"


def _shallow_structure(directory: Path) -> str:
    entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    lines = [
        ("dir  " if e.is_dir() else "file ") + e.name for e in entries if e.name not in _SKIP_DIRS
    ]
    return "\n".join(lines[:_MAX_STRUCTURE_ENTRIES])


@tool
def save_project_to_vault(directory: str | None = None, name: str | None = None) -> str:
    """Read a project's README, manifest (package.json/pyproject.toml/
    Cargo.toml/etc.), and top-level structure, and save a real,
    structured summary note to the vault under
    hi/knowledge/projects/<name>.md. Use this for "save this project to
    the vault" / "remember this project". Writes the note only —
    add_dev_flow is a separate tool if the user also wants a reopenable
    workspace shortcut for it.

    Args:
        directory: Project directory. Defaults to the directory `hi` was launched from.
        name: Project name for the note's filename. Defaults to the directory's own name.
    """
    resolved = _resolve(directory) if directory else _base_dir()
    if not resolved.is_dir():
        return f"'{directory}' is not a directory."

    project_name = name or resolved.name
    readme_path = _find_first(resolved, _README_NAMES)
    manifest_path = _find_first(resolved, _MANIFEST_NAMES)

    if not readme_path and not manifest_path:
        return (
            f"No README or manifest file found in {resolved} — nothing substantial "
            "to summarize. Use read_project_file/list_project_files and create_note "
            "directly if you want to write a note by hand instead."
        )

    sections = [f"Directory: {resolved}", f"Top-level structure:\n{_shallow_structure(resolved)}"]
    if readme_path:
        readme_text = readme_path.read_text(errors="replace")[:_MAX_README_CHARS]
        sections.append(f"README ({readme_path.name}):\n{readme_text}")
    if manifest_path:
        manifest_text = manifest_path.read_text(errors="replace")[:_MAX_MANIFEST_CHARS]
        sections.append(f"Manifest ({manifest_path.name}):\n{manifest_text}")

    prompt = (
        "Write a concise, structured Markdown summary note about this project for a "
        "personal knowledge vault. Cover: what it is/does, its tech stack, and its "
        "notable structure — a few short sections, not a copy of the README. Start "
        f'with a single "# {project_name}" heading.\n\n' + "\n\n---\n\n".join(sections)
    )
    model = get_tier_model("sonnet")
    summary = invoke_with_retry(model, [HumanMessage(prompt)]).strip()
    if not summary:
        return "Failed to generate a project summary — model returned an empty reply."

    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    note_path = PROJECTS_DIR / f"{_slugify(project_name)}.md"
    note_path.write_text(with_frontmatter(summary, ["hi", "project"]))
    return f"Saved project note: hi/knowledge/projects/{note_path.name}"
