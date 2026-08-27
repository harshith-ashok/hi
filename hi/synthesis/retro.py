"""Auto-generated weekly retro (TODO.md Phase 3 item 9): aggregates the
week's tasks, git activity, deadlines, and LeetCode streak into one dated
note under <VAULT_PATH>/hi/knowledge/retros/<ISO-week>.md.

Triggered on Sunday at the next `hi` session (hi/personas.py) rather than
a genuinely separate cron/timer — the same "next session" pattern Phase
1's inbox triage already established; a standalone scheduled job is a
real enhancement but out of scope here. Also callable on demand via the
`generate_retro` term tool.
"""

from __future__ import annotations

import subprocess
from datetime import date, timedelta
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from hi.capture.schema import Task
from hi.capture.store import list_items
from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model
from hi.tracking.deadlines import get_deadlines
from hi.tracking.leetcode import streak_days, topic_stats
from hi.vault import KNOWLEDGE_DIR
from hi.watchdogs.idle_repos import _known_project_dirs

RETROS_DIR = KNOWLEDGE_DIR / "retros"


def _iso_week_id(day: date) -> str:
    year, week, _weekday = day.isocalendar()
    return f"{year}-W{week:02d}"


def _tasks_summary() -> str:
    tasks = [t for t in list_items(kind="task") if isinstance(t, Task)]
    if not tasks:
        return "No tasks logged."
    by_project: dict[str, list[Task]] = {}
    for t in tasks:
        by_project.setdefault(t.project or "(no project)", []).append(t)
    lines = []
    for project, items in sorted(by_project.items()):
        done = sum(1 for t in items if t.status == "done")
        pending = sum(1 for t in items if t.status == "pending")
        lines.append(f"- **{project}**: {done} done, {pending} still open")
    return "\n".join(lines)


def _git_summary(days: int = 7) -> str:
    since = (date.today() - timedelta(days=days)).isoformat()
    lines = []
    for name, directory in sorted(_known_project_dirs().items()):
        if not (directory / ".git").is_dir():
            continue
        result = subprocess.run(
            ["git", "-C", str(directory), "log", f"--since={since}", "--oneline"],
            capture_output=True,
            text=True,
        )
        commits = result.stdout.strip().splitlines()
        if commits:
            lines.append(f"- **{name}**: {len(commits)} commit(s)")
            lines.extend(f"  - {c}" for c in commits[:10])
    return "\n".join(lines) if lines else "No commits this week across known projects."


def _deadlines_summary(limit: int = 5) -> str:
    deadlines = get_deadlines()[:limit]
    if not deadlines:
        return "No upcoming deadlines."
    return "\n".join(f"- {d.due} — {d.title}" for d in deadlines)


def _leetcode_summary() -> str:
    streak = streak_days()
    stats = topic_stats()
    lines = [f"Streak: {streak} day(s)."]
    if stats:
        weakest = sorted(stats.items(), key=lambda kv: kv[1]["solve_rate"])[:3]
        lines.append(
            "Weakest topics: " + ", ".join(f"{t} ({s['solve_rate']:.0%})" for t, s in weakest)
        )
    return "\n".join(lines)


def this_weeks_retro_exists(day: date | None = None) -> bool:
    day = day or date.today()
    return (RETROS_DIR / f"{_iso_week_id(day)}.md").exists()


def generate_weekly_retro(day: date | None = None) -> Path:
    day = day or date.today()
    week_id = _iso_week_id(day)
    RETROS_DIR.mkdir(parents=True, exist_ok=True)
    path = RETROS_DIR / f"{week_id}.md"
    content = (
        f"---\ntags: [hi, retro]\nweek: {week_id}\n---\n\n"
        f"# Weekly Retro — {week_id}\n\n"
        f"## Tasks\n{_tasks_summary()}\n\n"
        f"## Git activity (last 7 days)\n{_git_summary()}\n\n"
        f"## Deadlines\n{_deadlines_summary()}\n\n"
        f"## LeetCode\n{_leetcode_summary()}\n"
    )
    path.write_text(content)
    return path


@tool
def generate_retro() -> str:
    """Generate this week's retro note now (tasks completed/open per
    project, git activity, deadlines, LeetCode streak) instead of waiting
    for the automatic Sunday generation."""
    path = generate_weekly_retro()
    return f"Wrote weekly retro to {path.relative_to(KNOWLEDGE_DIR.parent)}."


def _smart_reflection(existing_content: str) -> str:
    prompt = (
        "Below is this week's automatically-aggregated retro data (tasks, "
        "git activity, deadlines, LeetCode). Write a short (3-5 sentence) "
        "narrative reflection on it: the actual pattern this week, "
        "anything worth flagging (a project going idle, a task "
        "repeatedly slipping, an unusually strong or quiet week), and "
        "one concrete, specific suggestion for next week. Interpret the "
        "data below, don't just restate it.\n\n"
        f"{existing_content}"
    )
    model = get_tier_model("opus")
    return invoke_with_retry(model, [HumanMessage(prompt)])


def generate_smart_weekly_retro(day: date | None = None) -> Path:
    """Opt-in "smart" variant (`BLOCKERS.md` -> "Suggested feature
    improvements" A, TODO.md Phase 14): generates (or reuses) this
    week's deterministic retro note via generate_weekly_retro() —
    unchanged, not replaced — then appends a real narrative reflection
    from a model call that interprets the same aggregated data instead
    of just presenting it."""
    day = day or date.today()
    week_id = _iso_week_id(day)
    path = RETROS_DIR / f"{week_id}.md"
    if not path.exists():
        generate_weekly_retro(day)
    reflection = _smart_reflection(path.read_text())
    with path.open("a") as f:
        f.write(f"\n## Reflection (smart, opt-in)\n\n{reflection}\n")
    return path


@tool
def generate_retro_smart() -> str:
    """Opt-in, deeper alternative to generate_retro(): generates (or
    reuses) this week's deterministic retro note, then appends a real
    narrative reflection from a model call — interpreting the same
    aggregated data (tasks, git activity, deadlines, LeetCode) instead of
    just presenting it. The deterministic sections are unchanged; this
    only adds a "Reflection" section on top. Use when the user
    explicitly wants a deeper/narrative retro, not just the raw numbers.
    """
    path = generate_smart_weekly_retro()
    return f"Added a smart reflection to this week's retro: {path.relative_to(KNOWLEDGE_DIR.parent)}."
