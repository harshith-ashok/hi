"""Writing skills: <vault>/skills/<name>/SKILL.md (hi/memory/skills.py). A new skill needs no confirmation (it only adds a
file); replacing the instructions of an existing one does, and the old file is copied to hi/backups first."""

from __future__ import annotations

from datetime import datetime

from langchain_core.tools import tool

import hi.config as config
from hi.action_tiers import confirm_destructive
from hi.memory import skills


@tool
def create_skill(name: str, description: str, instructions: str) -> str:
    """Save a new skill the user asked for: reusable instructions for a kind of task. The user can then run it by typing
    /name in the chat, and you can load it with use_skill. Does not overwrite: use update_skill for an existing one.

    Args:
        name: 2 to 40 characters: lower-case letters, digits and hyphens (for example "weekly-report").
        description: One line: what the skill does and when to use it. It is shown in the skills list.
        instructions: The full instructions, in Markdown, written to whoever will follow them.
    """
    try:
        skills.create(name, description, instructions)
    except ValueError as e:
        return str(e)
    return f"Created the skill '{name}'. The user can run it with /{name}."


@tool
def update_skill(name: str, instructions: str, description: str = "") -> str:
    """Replace the instructions of an existing skill (and its description, if you give one). The old version is kept in
    hi/backups. Asks the user first.

    Args:
        name: The skill's name.
        instructions: The complete new instructions in Markdown (not a patch).
        description: Optional new one-line description.
    """
    if name not in skills.list_skills(include_hidden=True):
        return f"No skill named '{name}'. Available: {', '.join(skills.list_skills(include_hidden=True)) or 'none'}."
    if not confirm_destructive(f"replace the instructions of the skill '{name}' (the old version is kept in hi/backups)"):
        return "Cancelled: the skill was not changed."
    old = skills._folders(include_hidden=True)[name] / "SKILL.md"
    copy = config.VAULT_PATH / "hi" / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f") / "skills" / name / "SKILL.md"
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(old.read_bytes())
    try:
        skills.update(name, instructions, description)
    except ValueError as e:
        return str(e)
    return f"Updated the skill '{name}'."
