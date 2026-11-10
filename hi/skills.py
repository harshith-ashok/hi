"""Skills from the vault: `<vault>/skills/<name>/SKILL.md` (name + description in frontmatter, instructions in
the body, optional bundled files next to it). Progressive loading keeps the prompt small:

- the prompt carries only an index (name + short description) and, when the message matches one, a hint;
- `use_skill(name)` loads the full instructions; `use_skill(name, file)` loads a bundled file.
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import tool

import hi.config as config
from hi.frontmatter import parse_frontmatter
from hi.vault_context import _words

MAX_BODY_CHARS = 12000
INDEX_DESCRIPTION_CHARS = 110
HINT_MIN_WORDS = 2  # distinct words shared with a skill's name + description before we hint at it


def skills_dir() -> Path:
    return config.VAULT_PATH / "skills"


def list_skills() -> dict[str, str]:
    """{skill name: description} for every skill folder that has a SKILL.md."""
    found = {}
    for path in sorted(skills_dir().glob("*/SKILL.md")):
        fields, _body = parse_frontmatter(path.read_text(errors="ignore"))
        found[str(fields.get("name") or path.parent.name)] = str(fields.get("description") or "")
    return found


def index() -> str:
    """Prompt block listing the skills, or '' when there are none."""
    skills = list_skills()
    if not skills:
        return ""
    lines = [f"- {name}: {re.sub(r'\s+', ' ', desc)[:INDEX_DESCRIPTION_CHARS]}" for name, desc in skills.items()]
    return "Skills (instructions for specific kinds of task; call use_skill(name) to load one before starting):\n" + "\n".join(lines)


def hint_for(message: str) -> str:
    """'' or one line naming the skill that best matches `message`."""
    words = _words(message)
    best, best_score = "", 0
    for name, desc in list_skills().items():
        score = len(words & (_words(name) | _words(desc)))
        if re.search(rf"\b{re.escape(name)}s?\b", message.lower()):  # "pdf" is under _words' 4-letter minimum
            score += HINT_MIN_WORDS
        if score > best_score:
            best, best_score = name, score
    return f"Likely relevant skill: {best}. Call use_skill('{best}') first." if best_score >= HINT_MIN_WORDS else ""


@tool
def use_skill(name: str, file: str = "") -> str:
    """Load a skill's instructions from the vault, or one of its bundled files. Do this before a task a skill
    covers (PDFs, spreadsheets, slides, docs, frontend, ...), then follow the instructions.

    Args:
        name: The skill name from the skills list.
        file: Optional path of a bundled file inside the skill folder, e.g. "reference.md". Empty loads SKILL.md.
    """
    folder = skills_dir() / name
    if name not in list_skills() and not (folder / "SKILL.md").exists():
        return f"No skill named '{name}'. Available: {', '.join(list_skills()) or 'none'}."
    target = (folder / (file or "SKILL.md")).resolve()
    if not target.is_relative_to(folder.resolve()) or not target.is_file():
        bundled = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
        return f"No file '{file}' in skill '{name}'. Files: {', '.join(bundled[:40])}"
    text = target.read_text(errors="ignore")
    if not file:
        text = parse_frontmatter(text)[1]
        others = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and p.name != "SKILL.md")
        if others:
            text += f"\n\n(Bundled files, load with use_skill('{name}', file): {', '.join(others[:40])})"
    return text[:MAX_BODY_CHARS] + ("\n…(truncated)" if len(text) > MAX_BODY_CHARS else "")
