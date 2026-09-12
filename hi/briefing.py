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
import hi.config as config
from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model
from hi.tracking.applications import due_follow_ups
from hi.tracking.deadlines import get_deadlines
from hi.tracking.leetcode import todays_log
from hi.watchdogs.idle_repos import find_idle_repos

# ~/Dev is a *different* Obsidian vault on this machine (its own
# .obsidian/.stfolder markers, topic folders like AI/Docker/DSA) — actual
# project directories live one level down, in ~/Dev/Projects/. Verified
# directly before using this path rather than assuming the literal one
# named in the TODO item.
PROJECTS_DIR = Path.home() / "Dev" / "Projects"


def _last_edited_note() -> str | None:
    if not config.VAULT_PATH.is_dir():
        return None
    hi_dir = config.VAULT_PATH / "hi"
    # hi/ is the assistant's own namespace (conversations/, knowledge/,
    # todo.md) — hi/conversations/ gets touched on every single turn of
    # every persona, so without this exclusion it always wins "most
    # recently edited" and this part of the briefing never actually
    # reflects a note the user wrote.
    notes = [
        p for p in config.VAULT_PATH.rglob("*.md") if p.is_file() and not p.is_relative_to(hi_dir)
    ]
    if not notes:
        return None
    latest = max(notes, key=lambda p: p.stat().st_mtime)
    return str(latest.relative_to(config.VAULT_PATH))


def _idle_repos_line() -> str | None:
    flags = find_idle_repos()
    if not flags:
        return None
    parts = [f"{f.project} ({f.days_idle}d idle, {f.open_task_count} open task(s))" for f in flags]
    return "Idle repos with open tasks: " + ", ".join(parts)


def _deadlines_line(limit: int = 3) -> str | None:
    deadlines = get_deadlines()[:limit]
    if not deadlines:
        return None
    parts = [f"{d.due} — {d.title}" for d in deadlines]
    return "Nearest deadlines: " + "; ".join(parts)


def _leetcode_line() -> str | None:
    if todays_log() is not None:
        return None
    return "Today's LeetCode problem isn't logged yet."


def _application_follow_ups_line() -> str | None:
    due = due_follow_ups()
    if not due:
        return None
    return "Applications due for a follow-up: " + ", ".join(a.target for a in due)


def _last_opened_project() -> str | None:
    if not PROJECTS_DIR.is_dir():
        return None
    projects = [p for p in PROJECTS_DIR.iterdir() if p.is_dir()]
    if not projects:
        return None
    latest = max(projects, key=lambda p: p.stat().st_mtime)
    return latest.name


def build_briefing() -> tuple[str, str, str] | None:
    """Return (context, suggestion, action) to show before the first
    router-mode prompt, or None if there's nothing worth surfacing (no
    tasks, no recent notes, no recent projects). Split into three pieces
    (rather than one pre-joined display string) so a caller with a
    compact single-line surface — the voice companion's briefing strip,
    hi/ipc/server.py's new GET /briefing — can show just `suggestion`
    without `context`'s full multi-line dump; hi/repl.py's terminal
    still joins them back into one block, unchanged in effect."""
    tasks = pending_tasks_greeting()
    last_note = _last_edited_note()
    last_project = _last_opened_project()
    idle_repos = _idle_repos_line()
    deadlines = _deadlines_line()
    leetcode = _leetcode_line()
    follow_ups = _application_follow_ups_line()

    sources = (tasks, last_note, last_project, idle_repos, deadlines, leetcode, follow_ups)
    if not any(sources):
        return None

    context_lines = []
    if tasks:
        context_lines.append(tasks)
    if last_note:
        context_lines.append(f"Most recently edited vault note: {last_note}")
    if last_project:
        context_lines.append(f"Most recently opened project: {last_project}")
    if idle_repos:
        context_lines.append(idle_repos)
    if deadlines:
        context_lines.append(deadlines)
    if leetcode:
        context_lines.append(leetcode)
    if follow_ups:
        context_lines.append(follow_ups)
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
        return context, "", ""

    return context, suggestion, action
