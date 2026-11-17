"""Tools for creating and managing scheduled tasks by talking ("every weekday at 8 brief me", "remind me Friday...").

The model turns the words into a cron expression or "once <time>"; the tool checks it and answers with the next
fire times written out, which the model must tell the user so a wrong guess is caught at once. A schedule is a note in
the vault (hi/memory/schedules.py) that the scheduler runs (hi/automation/scheduler.py).
"""

from __future__ import annotations

from datetime import datetime

from langchain_core.tools import tool

from hi.action_tiers import confirm_destructive
from hi.automation import scheduler
from hi.memory import schedules
from hi.toolkit import is_read_only


def _describe(s: schedules.Schedule, now: datetime) -> str:
    nxt = schedules.next_fires(s, 1, now)
    state = "on" if s.enabled else "paused"
    return f"- {s.id} [{state}] {s.when} — next {schedules.say_time(nxt[0]) if nxt else 'never'} — {s.kind}: {s.prompt[:80]}"


@tool
def schedule_task(task: str, when: str, kind: str = "task", deliver: str = "notify",
                  context: str = "vault", allow_web: bool = False, allow: str = "") -> str:
    """Schedule something to happen later or repeatedly. It runs without the user, so a task only reads (the vault,
    the web if allowed) and anything it wants to change is left as a proposal for the user to approve.

    Always tell the user the first fire time from the result, so a misunderstanding is caught now.

    Args:
        task: What to do, written as a full instruction ("Brief me for today: overdue tasks, deadlines, open loops"). For a reminder, the exact text to show.
        when: Five cron fields in local time, like "0 8 * * 1-5" (8:00 on weekdays) or "30 17 * * 5" (Friday 17:30), or a single time like "once 2026-11-20T15:00".
        kind: "task" runs the assistant on it; "reminder" shows the text as it is, with no model.
        deliver: "notify" (report and a pop-up), "report" (report only), "silent" (report only, no pop-up even for approvals).
        context: What the run may see: "vault", or "vault,screen" (screen only on a local model).
        allow_web: Let the task search the web.
        allow: Comma-separated extra tools it may use without approval. Needs the user's confirmation now.
    """
    if error := schedules.validate_when(when):
        return f"Not scheduled: {error}"
    extra = tuple(t.strip() for t in allow.split(",") if t.strip())
    if risky := [t for t in extra if not is_read_only(t)]:
        if not confirm_destructive(f"let the scheduled task '{task[:60]}' use {', '.join(risky)} without asking each time"):
            return "Not scheduled: the user declined to give the task those tools."
    parts = tuple(p.strip() for p in context.split(",") if p.strip()) or ("vault",)
    now = datetime.now()
    s = schedules.Schedule(
        id=schedules.new_id(task), when=when.strip(), prompt=task.strip(), kind=kind, deliver=deliver, context=parts,
        allow_web=allow_web, allow=extra, created=now.isoformat(timespec="seconds"),
    )
    try:  # the same checks the scheduler applies when it reads the note back
        schedules.from_markdown(s.id, schedules.to_markdown(s))
    except ValueError as e:
        return f"Not scheduled: {e}"
    schedules.save(s)
    fires = schedules.next_fires(s, 3, now)
    when_text = ", ".join(schedules.say_time(f) for f in fires) or "never (that time has passed)"
    return f"Scheduled '{s.id}'. Next: {when_text}. Tell the user the first one."


@tool
def list_schedules() -> str:
    """List the scheduled tasks with their next run."""
    errors: list[str] = []
    items = schedules.load_all(errors)
    now = datetime.now()
    lines = [_describe(s, now) for s in items] or ["No scheduled tasks."]
    return "\n".join(lines + [f"! {e}" for e in errors])


@tool
def pause_schedule(schedule_id: str, paused: bool = True) -> str:
    """Pause or resume a scheduled task.

    Args:
        schedule_id: The id from list_schedules.
        paused: True to pause, False to resume.
    """
    return (f"{'Paused' if paused else 'Resumed'} '{schedule_id}'." if schedules.set_enabled(schedule_id, not paused)
            else f"No schedule called '{schedule_id}'.")


@tool
def delete_schedule(schedule_id: str) -> str:
    """Delete a scheduled task for good.

    Args:
        schedule_id: The id from list_schedules.
    """
    if schedules.load(schedule_id) is None:
        return f"No schedule called '{schedule_id}'."
    if not confirm_destructive(f"delete the scheduled task '{schedule_id}'"):
        return "Not deleted."
    schedules.delete(schedule_id)
    return f"Deleted '{schedule_id}'."


@tool
def run_schedule_now(schedule_id: str) -> str:
    """Run a scheduled task now, outside its timetable. The result arrives in the Inbox like any other.

    Args:
        schedule_id: The id from list_schedules.
    """
    return scheduler.run_now(schedule_id)


SCHEDULE_TOOLS = [schedule_task, list_schedules, pause_schedule, delete_schedule, run_schedule_now]
