"""Skills from the vault: `<vault>/skills/<name>/SKILL.md` (name + description in frontmatter, instructions in
the body, optional bundled files next to it). Progressive loading keeps the prompt small:

- the prompt carries only an index (name + short description) and, when the message matches one, a hint;
- `use_skill(name)` loads the full instructions; `use_skill(name, file)` loads a bundled file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from langchain_core.tools import tool

import hi.config as config
from hi.memory.frontmatter import parse_frontmatter
from hi.memory.context import _words

MAX_BODY_CHARS = 12000
INDEX_DESCRIPTION_CHARS = 110
HINT_MIN_WORDS = 2  # distinct words shared with a skill's name + description before we hint at it


def skills_dir() -> Path:
    return config.VAULT_PATH / "skills"


# Names the chat UI handles itself. A skill with one of these names is still loadable by the model, but `/name` runs
# the built-in, so it is left out of the slash list.
BUILTIN_COMMANDS = frozenset({"new", "clear", "help", "skills", "config", "model", "tier"})
_SLASH_RE = re.compile(r"\A/([A-Za-z0-9][\w-]*)(?:\s+(.*))?\Z", re.DOTALL)


def _skill_files() -> list[Path]:
    """Every SKILL.md under the skills folder, at any depth (a cloned skills repo nests them). A skill's own
    subfolders are not searched, so a bundled example is not mistaken for another skill."""
    found: list[Path] = []
    for root, dirs, files in os.walk(skills_dir()):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        if "SKILL.md" in files:
            found.append(Path(root) / "SKILL.md")
            dirs.clear()
    return found


def _folders(include_hidden: bool = False) -> dict[str, Path]:
    """{skill name: its folder}. The first one found wins when two share a name."""
    found: dict[str, Path] = {}
    for path in _skill_files():
        fields, _body = parse_frontmatter(path.read_text(errors="ignore"))
        if not include_hidden and str(fields.get("invoke", "true")).lower() == "false":
            continue
        found.setdefault(str(fields.get("name") or path.parent.name), path.parent)
    return found


def list_skills(include_hidden: bool = False) -> dict[str, str]:
    """{skill name: description} for every skill folder that has a SKILL.md.
    A skill with `invoke: false` in its frontmatter is hidden unless `include_hidden`."""
    return {
        name: str(parse_frontmatter((folder / "SKILL.md").read_text(errors="ignore"))[0].get("description") or "")
        for name, folder in _folders(include_hidden).items()
    }


def slash_commands() -> list[dict[str, str]]:
    """The skills `/name` can run: [{name, description}], built-in command names excluded."""
    return [{"name": n, "description": d} for n, d in list_skills().items() if n.lower() not in BUILTIN_COMMANDS]


def expand_slash(text: str) -> tuple[str, str, str] | None:
    """For a message like `/pdf merge these`, (skill name, the rest of the message, the skill's instructions).
    None when the message is not a slash command, names a built-in, or names no skill (so `/Users/me/x` is
    left alone)."""
    match = _SLASH_RE.match(text.strip())
    if not match:
        return None
    name = match.group(1)
    skills = {n.lower(): n for n in list_skills() if n.lower() not in BUILTIN_COMMANDS}
    if name.lower() not in skills:
        return None
    return skills[name.lower()], (match.group(2) or "").strip(), skill_text(skills[name.lower()])


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
    return skill_text(name, file)


def skill_text(name: str, file: str = "") -> str:
    """A skill's instructions (frontmatter removed), or one bundled file; an explanatory message when missing."""
    folder = _folders(include_hidden=True).get(name)
    if folder is None:
        return f"No skill named '{name}'. Available: {', '.join(list_skills(include_hidden=True)) or 'none'}."
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
