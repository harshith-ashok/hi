""""What Deserves The Next Hour" arbiter (TODO.md Phase 3 item 8): one
deterministic scoring pass over pending tasks — deadline proximity,
priority, whether the task's project has gone idle
(hi/watchdogs/idle_repos.py), and today's weekday context note
(hi/context/weekday.py). Deliberately rule-based, not an LLM call: the
point, per TODO.md's own framing, is to remove a decision, not introduce
a second, less-inspectable one in its place.

Outputs exactly ONE recommendation + a one-line rationale, never a ranked
list — resist the temptation to return the whole sorted list "just in
case"; the list stays internal to pick_next_hour(), only the winner and
why come back out.
"""

from __future__ import annotations

from datetime import date, datetime

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from hi.capture.schema import Task
from hi.capture.store import list_items
from hi.context.weekday import todays_context_note
from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model
from hi.watchdogs.idle_repos import find_idle_repos

_MAX_TASKS_FOR_SMART = 20  # cap what goes into the prompt — a real ceiling, not a guess

_PRIORITY_SCORES = {"high": 3, "medium": 2, "low": 1}
_DATE_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d")


def _due_score(due: str | None) -> tuple[int, int | None]:
    """Returns (score, days_until); days_until is None if `due` is
    missing or unparseable."""
    if not due:
        return 0, None
    parsed = None
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(due, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        return 0, None
    days_until = (parsed - date.today()).days
    if days_until <= 0:
        return 5, days_until
    if days_until <= 1:
        return 4, days_until
    if days_until <= 3:
        return 3, days_until
    if days_until <= 7:
        return 2, days_until
    return 1, days_until


def _score_task(task: Task, idle_projects: set[str], context_note: str | None) -> tuple[int, dict]:
    priority_score = _PRIORITY_SCORES.get((task.priority or "").lower(), 0)
    due_score, days_until = _due_score(task.due)
    idle = bool(task.project) and task.project.lower() in idle_projects
    mentioned = bool(
        context_note
        and (
            task.text.lower() in context_note.lower()
            or (task.project and task.project.lower() in context_note.lower())
        )
    )
    total = priority_score + due_score + (2 if idle else 0) + (1 if mentioned else 0)
    reasons = {
        "priority": task.priority if priority_score else None,
        "days_until": days_until,
        "overdue": days_until is not None and days_until <= 0,
        "idle": idle,
        "mentioned_today": mentioned,
    }
    return total, reasons


def _rationale(task: Task, reasons: dict) -> str:
    parts = []
    if reasons["overdue"]:
        parts.append("it's overdue")
    elif reasons["days_until"] is not None:
        d = reasons["days_until"]
        parts.append(f"it's due in {d} day{'s' if d != 1 else ''}")
    if reasons["idle"] and task.project:
        parts.append(f"the '{task.project}' repo has gone idle")
    if reasons["priority"] == "high":
        parts.append("it's marked high priority")
    if reasons["mentioned_today"]:
        parts.append("today's context note calls it out")

    if not parts:
        return "No other pending task has a stronger deadline, priority, or idle-project signal right now."
    if len(parts) == 1:
        return parts[0][0].upper() + parts[0][1:] + "."
    return f"{parts[0][0].upper()}{parts[0][1:]} and {parts[1]}."


def _pick_next_task(exclude_ids: frozenset[str] = frozenset()) -> tuple[Task, str] | None:
    """Returns (task, rationale) for the best pending task not in
    exclude_ids — the shared scoring core `pick_next_hour()` and
    `pick_next_task_for_session()` (TODO.md Phase 15) both build on, so
    a follow-up "no, something else" reply re-runs the SAME real scoring
    pass with one task removed, rather than a second, different
    mechanism. None if nothing pending remains."""
    tasks = [
        t
        for t in list_items(kind="task")
        if isinstance(t, Task) and t.status == "pending" and t.id not in exclude_ids
    ]
    if not tasks:
        return None

    idle_projects = {f.project.lower() for f in find_idle_repos()}
    context_note = todays_context_note()

    scored = [(t, *_score_task(t, idle_projects, context_note)) for t in tasks]
    scored.sort(
        key=lambda item: (
            -item[1],
            item[2]["days_until"] if item[2]["days_until"] is not None else 999,
        )
    )
    top_task, _score, reasons = scored[0]
    return top_task, _rationale(top_task, reasons)


def pick_next_hour(exclude_ids: frozenset[str] = frozenset()) -> tuple[str, str]:
    """Returns (recommendation, rationale) — the single best use of the
    next hour, or a "nothing pending" message if there's nothing open.
    `exclude_ids` (TODO.md Phase 15) lets a caller re-run this leaving
    out a task already rejected this session — default empty, so every
    existing caller (what_next()) is unaffected."""
    picked = _pick_next_task(exclude_ids)
    if picked is None:
        if exclude_ids:
            return "No other pending task to recommend.", "Every remaining pending task was already ruled out this session."
        return "Nothing pending right now.", "No open tasks to weigh against each other."
    top_task, rationale = picked
    return top_task.text, rationale


def pick_next_task_for_session(exclude_ids: frozenset[str] = frozenset()) -> tuple[Task, str] | None:
    """Router-facing variant of pick_next_hour() (TODO.md Phase 15) that
    returns the real Task object, not just its text — so
    hi/repl.py's multi-turn pushback handling can track *which* task was
    just recommended (by id) to exclude it on a "no, something else"
    reply, without needing to re-match plain text back to a task."""
    return _pick_next_task(exclude_ids)


@tool
def what_next() -> str:
    """Recommend the single best use of the next hour — weighing deadline
    proximity, task priority, and whether the task's project has gone
    idle — as ONE recommendation with a one-line reason, never a ranked
    list. Use for "what should I work on" / "what's next" / bare-launch
    guidance.
    """
    recommendation, rationale = pick_next_hour()
    return f"{recommendation}\n({rationale})"


def smart_pick_next_hour() -> str:
    """Opt-in "smart" variant (`BLOCKERS.md` -> "Suggested feature
    improvements" A, TODO.md Phase 14): the same underlying signals
    pick_next_hour()'s deterministic scorer already computes (priority,
    days until due, idle-project flag, today's context note) handed to a
    real opus-tier model call, which weighs them the way a thoughtful
    person would and explains its reasoning in its own words — instead
    of picking whichever task the fixed formula scored highest.
    pick_next_hour()/what_next() stay the default for most turns
    (arbiter.py's own original point — "remove the decision, don't
    introduce a second, less-inspectable one" — is still correct there);
    this is for when the user explicitly wants deeper reasoning behind
    the answer, not a replacement for the deterministic default."""
    tasks = [t for t in list_items(kind="task") if isinstance(t, Task) and t.status == "pending"]
    if not tasks:
        return "Nothing pending right now."

    idle_projects = {f.project.lower() for f in find_idle_repos()}
    context_note = todays_context_note()
    scored = sorted(
        ((t, *_score_task(t, idle_projects, context_note)) for t in tasks),
        key=lambda item: -item[1],
    )[:_MAX_TASKS_FOR_SMART]

    lines = []
    for t, _score, reasons in scored:
        bits = [f"priority={t.priority or 'none'}"]
        if t.due:
            bits.append(f"due={t.due}")
        if t.project:
            bits.append(f"project='{t.project}'" + (" [idle]" if reasons["idle"] else ""))
        lines.append(f"- {t.text} ({', '.join(bits)})")
    task_list = "\n".join(lines)

    prompt = (
        "Below is a real, current pending-task list, each already "
        "annotated with its actual priority/due date/project-idle "
        "signal. Recommend the single best use of the next hour, "
        "weighing these signals the way a thoughtful person would — not "
        "just picking whichever looks highest-priority mechanically. A "
        "slightly lower-priority task might matter more right now if "
        "it's what today's context note calls out, or if it unblocks "
        "something else.\n\n"
        f"Today's context note: {context_note or '(none)'}\n\n"
        f"Pending tasks:\n{task_list}\n\n"
        "Reply with the recommended task first, then 1-3 sentences of "
        "real reasoning referencing the actual signals above."
    )
    model = get_tier_model("opus")
    return invoke_with_retry(model, [HumanMessage(prompt)])


@tool
def what_next_smart() -> str:
    """Opt-in, deeper alternative to what_next(): weighs the same
    pending-task signals (deadline proximity, priority, idle project,
    today's context note) but through a real model call that produces
    an actual narrative justification, instead of picking whichever
    task a fixed formula scores highest. Use only when the user
    explicitly wants more reasoning behind the recommendation ("really
    think about it", "give me a smarter recommendation") — what_next()
    is the right default otherwise, since it's faster and the
    recommendation is just as inspectable."""
    return smart_pick_next_hour()
