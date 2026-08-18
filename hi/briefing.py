"""Pre-session briefing for auto-routing mode (`hi`, no flag): gathers
pending tasks, the most recently edited vault note, and the most recently
opened project, then asks the haiku-tier model for one short, concrete,
actionable suggestion — shown once before the first prompt.

Gathering is plain filesystem lookups, not LLM calls — none of the three
sources need reasoning to find, just a stat/mtime comparison.
"""

from pathlib import Path

from langchain_core.messages import HumanMessage

from hi.agents.butler.todo import pending_tasks_greeting
from hi.config import VAULT_PATH
from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model

# ~/Dev is a *different* Obsidian vault on this machine (its own
# .obsidian/.stfolder markers, topic folders like AI/Docker/DSA) — actual
# project directories live one level down, in ~/Dev/Projects/. Verified
# directly before using this path rather than assuming the literal one
# named in the TODO item.
PROJECTS_DIR = Path.home() / "Dev" / "Projects"


def _last_edited_note() -> str | None:
    if not VAULT_PATH.is_dir():
        return None
    hi_dir = VAULT_PATH / "hi"
    # hi/ is the assistant's own namespace (conversations/, knowledge/,
    # todo.md) — hi/conversations/ gets touched on every single turn of
    # every persona, so without this exclusion it always wins "most
    # recently edited" and this part of the briefing never actually
    # reflects a note the user wrote.
    notes = [
        p for p in VAULT_PATH.rglob("*.md") if p.is_file() and not p.is_relative_to(hi_dir)
    ]
    if not notes:
        return None
    latest = max(notes, key=lambda p: p.stat().st_mtime)
    return str(latest.relative_to(VAULT_PATH))


def _last_opened_project() -> str | None:
    if not PROJECTS_DIR.is_dir():
        return None
    projects = [p for p in PROJECTS_DIR.iterdir() if p.is_dir()]
    if not projects:
        return None
    latest = max(projects, key=lambda p: p.stat().st_mtime)
    return latest.name


def build_briefing() -> tuple[str, str] | None:
    """Return (display_text, suggested_action) to show before the first
    router-mode prompt, or None if there's nothing worth surfacing (no
    tasks, no recent notes, no recent projects)."""
    tasks = pending_tasks_greeting()
    last_note = _last_edited_note()
    last_project = _last_opened_project()

    if not tasks and not last_note and not last_project:
        return None

    context_lines = []
    if tasks:
        context_lines.append(tasks)
    if last_note:
        context_lines.append(f"Most recently edited vault note: {last_note}")
    if last_project:
        context_lines.append(f"Most recently opened project: {last_project}")
    context = "\n".join(context_lines)

    prompt = (
        "Here's a quick snapshot of the user's current state:\n\n"
        f"{context}\n\n"
        'Suggest ONE short, concrete, actionable next step as a yes/no '
        'question, e.g. "Want to check off the push-the-repo task?". Base '
        "it on what's actually shown above — don't invent details that "
        "aren't there. Reply in exactly this two-line format:\n"
        "SUGGESTION: <the one-line yes/no question>\n"
        "ACTION: <the concrete instruction to carry out if the user says yes>"
    )
    model = get_tier_model("haiku")
    reply = invoke_with_retry(model, [HumanMessage(prompt)])

    suggestion = None
    action = None
    for line in reply.splitlines():
        if line.startswith("SUGGESTION:"):
            suggestion = line[len("SUGGESTION:") :].strip()
        elif line.startswith("ACTION:"):
            action = line[len("ACTION:") :].strip()

    if not suggestion or not action:
        # Model didn't follow the format — still show the gathered
        # context, just without a suggestion to act on.
        return context, ""

    return f"{context}\n\n{suggestion}", action
