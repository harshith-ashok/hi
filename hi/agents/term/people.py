"""Manages per-person notes at <VAULT_PATH>/hi/knowledge/people/*.md, so
`term` can answer "who do I know" / recall facts about a specific person,
and keep those notes up to date as new things are learned about them.
"""

import re
from pathlib import Path

from langchain_core.tools import tool

from hi.vault import KNOWLEDGE_DIR, with_frontmatter

PEOPLE_DIR = KNOWLEDGE_DIR / "people"


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _person_filename(name: str) -> str:
    words = name.strip().split()
    return "_".join(word.capitalize() for word in words) + ".md"


def _find_person_path(name: str) -> Path | None:
    """Match an existing note by name, tolerant of case/spacing/underscore
    differences (e.g. "dean haidt" matches Dean_Haidt.md). Falls back to an
    unambiguous partial match (exactly one candidate contains the name)."""
    if not PEOPLE_DIR.exists():
        return None
    target = _normalize(name)
    candidates = list(PEOPLE_DIR.glob("*.md"))
    for path in candidates:
        if _normalize(path.stem) == target:
            return path
    partial = [p for p in candidates if target in _normalize(p.stem)]
    return partial[0] if len(partial) == 1 else None


def _display_name(path: Path) -> str:
    return path.stem.replace("_", " ")


@tool
def add_person_info(name: str, info: str) -> str:
    """Add or update information about a person. Creates a new note if
    they don't have one yet, otherwise appends to their existing note —
    prefer this over guessing whether someone is already known.

    Args:
        name: The person's name, e.g. "Dean Haidt".
        info: What to record about them, e.g. "Works at Acme, met at the
            hackathon in March."
    """
    path = _find_person_path(name)
    is_new = path is None
    if is_new:
        path = PEOPLE_DIR / _person_filename(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(with_frontmatter(f"# {name}\n\n- {info}\n", ["hi", "person"]))
        return f"Added a new note for {name}."

    with path.open("a") as f:
        if path.stat().st_size > 0:
            f.write("\n")
        f.write(f"- {info}\n")
    return f"Updated {_display_name(path)}'s note."


@tool
def get_person_info(name: str) -> str:
    """Read what's known about a person.

    Args:
        name: The person's name, e.g. "Dean Haidt".
    """
    path = _find_person_path(name)
    if not path:
        return f"No notes about '{name}' yet."
    return path.read_text()


@tool
def delete_person(name: str) -> str:
    """Delete a person's note entirely.

    Args:
        name: The person's name, e.g. "Dean Haidt".
    """
    path = _find_person_path(name)
    if not path:
        return f"No notes about '{name}' to delete."
    display_name = _display_name(path)
    path.unlink()
    return f"Deleted the note for {display_name}."


@tool
def list_people() -> str:
    """List everyone with a note — use this to answer "who do I know"."""
    if not PEOPLE_DIR.exists():
        return "No people notes yet."
    names = sorted(_display_name(p) for p in PEOPLE_DIR.glob("*.md"))
    if not names:
        return "No people notes yet."
    return "\n".join(names)
