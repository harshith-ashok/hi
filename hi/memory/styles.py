"""Your own writing styles: <vault>/hi/styles/<name>.md.

    ---
    name: Pirate
    ---
    Answer like a pirate, but keep the facts straight.

The frontmatter `name` is what the style is called in the menu (the file name is used when there is none); the body is
the instruction sent with every message while the style is chosen. hi's built-in styles are in hi/automation/profiles.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import hi.config as config
from hi.memory.frontmatter import parse_frontmatter

MAX_INSTRUCTION_CHARS = 1500


def styles_dir() -> Path:
    return config.VAULT_PATH / "hi" / "styles"


def _id(stem: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")


def vault_styles() -> dict[str, dict[str, str]]:
    """{id: {label, instruction}} for every style file with some instruction in it, by id."""
    found: dict[str, dict[str, str]] = {}
    for path in sorted(styles_dir().glob("*.md")) if styles_dir().is_dir() else []:
        fields, body = parse_frontmatter(path.read_text(errors="ignore"))
        instruction = re.sub(r"\s+", " ", body).strip()[:MAX_INSTRUCTION_CHARS]
        style_id = _id(path.stem)
        if instruction and style_id:
            found.setdefault(style_id, {"label": str(fields.get("name") or path.stem), "instruction": instruction})
    return found
