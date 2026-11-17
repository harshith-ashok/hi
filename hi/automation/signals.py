"""The facts the heartbeat looks at, found by plain code and no model: what is due, what is open, what is stuck.

A `Signal` has a stable `key` (the same fact gives the same key, so an unchanged situation is recognised and costs no
model call), a `text` a model can read and quote, and `screen=True` if it came from what is on the screen (then it
is only used with a local model). The suggestion engine (hi/suggest/engine.py) uses the shared checks too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import hi.config as config

ERROR_MINUTES = 15  # the same error on screen this long means the user is stuck
MEETING_WITHIN_MIN = 60
PROPOSAL_WAIT_HOURS = 24
_ERROR_LINE = re.compile(
    r"^.*(?:Traceback \(most recent call last\)|\b\w*(?:Error|Exception)\b: .+|\bFAILED\b|\bpanic: .+|npm ERR! .+|"
    r"error\[E\d+\]: .+|fatal: .+|Segmentation fault).*$",
    re.MULTILINE,
)
_FOR_MINUTES = re.compile(r"\(for (\d+) (min|s);")
_DATE_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d")


@dataclass(frozen=True)
class Signal:
    key: str
    text: str
    weight: int = 1
    screen: bool = False


def parse_date(value: str) -> datetime | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


# --- shared with the suggestion engine -----------------------------------------------------------------------

def idle_repos() -> list[Signal]:
    from hi.watchdogs.idle_repos import find_idle_repos

    return [
        Signal(f"idle:{f.project}", f"'{f.project}' has been idle {f.days_idle} days with {f.open_task_count} open task(s).")
        for f in find_idle_repos()
    ]


def deadlines(window_days: int = 2, today: date | None = None) -> list[Signal]:
    from hi.tracking.deadlines import get_deadlines

    today = today or date.today()
    found = []
    for d in get_deadlines():
        parsed = parse_date(d.due)
        if parsed is None:
            continue
        days_until = (parsed.date() - today).days
        if 0 <= days_until <= window_days:
            found.append(Signal(f"deadline:{d.source}", f"'{d.title}' is due {d.due} ({days_until}d).", weight=2))
    return found


def applications() -> list[Signal]:
    from hi.tracking.applications import due_follow_ups

    return [Signal(f"application:{a.slug}", f"Follow up on '{a.target}': no update since {a.date_sent}.")
            for a in due_follow_ups()]


def diff_watch() -> list[Signal]:
    """Only for users who opted into the screen-unchanged watcher (DIFF_WATCH_ENABLED)."""
    if not config.DIFF_WATCH_ENABLED:
        return []
    from hi.perception import diff_watch as watcher

    minutes = watcher.unchanged_suggestion()
    if minutes is None:
        return []
    return [Signal(f"diff-watch:{date.today().isoformat()}", f"The screen has looked the same for {minutes}+ minutes.",
                   screen=True)]


# --- only the heartbeat -----------------------------------------------------------------------------------------

def screen_error(described: str) -> list[Signal]:
    """An error visible on screen in a window the user has had open for ERROR_MINUTES or more. `described` is the live
    context text (hi/context/now.py `describe`)."""
    minutes = _FOR_MINUTES.search(described or "")
    if not minutes or minutes.group(2) != "min" or int(minutes.group(1)) < ERROR_MINUTES:
        return []
    visible = described.split("Text visible on screen:", 1)[-1] if "Text visible on screen:" in described else ""
    match = _ERROR_LINE.search(visible)
    if not match:
        return []
    line = match.group(0).strip()[:200]
    window = described.splitlines()[0].removeprefix("Frontmost: ")
    key = "error:" + re.sub(r"\W+", "", line.lower())[:60]  # the same error keeps the same key
    return [Signal(key, f"An error has been on screen for {minutes.group(1)}+ minutes ({window}): {line}", weight=3, screen=True)]


def meetings(now: datetime, within_min: int = MEETING_WITHIN_MIN) -> list[Signal]:
    from hi.capture.schema import Event
    from hi.capture.store import list_items

    found = []
    for item in list_items(kind="event"):
        if isinstance(item, Event) and (when := parse_date(item.when)) and "T" in item.when:
            if timedelta(0) <= when - now <= timedelta(minutes=within_min):
                found.append(Signal(f"meeting:{item.id}", f"'{item.text}' starts at {when:%H:%M} ({int((when - now).total_seconds() // 60)} min).", weight=2))
    return found


def proposals_waiting(now: datetime, hours: int = PROPOSAL_WAIT_HOURS) -> list[Signal]:
    from hi.memory import proposals

    old = [p for p in proposals.pending() if now.timestamp() - p["created_at"] > hours * 3600]
    if not old:
        return []
    ids = ",".join(sorted(p["id"] for p in old))
    return [Signal(f"proposals-waiting:{ids}", f"{len(old)} proposed action(s) have waited over a day for approval: "
                   + "; ".join(f"{p['id']} {p['tool']}" for p in old[:5]))]


def drop_stuck(now: datetime) -> list[Signal]:
    """Files left in the drop folder for over ten minutes: something is wrong with filing them."""
    from hi.automation import drop

    stuck = drop.stuck_files(now)
    return [Signal(f"drop-stuck:{len(stuck)}", f"{len(stuck)} file(s) in the drop folder could not be filed: "
                   + ", ".join(stuck[:5]))] if stuck else []


def collect(now: datetime, described: str = "", include_screen: bool = False) -> list[Signal]:
    """Every signal for this beat. Screen signals only when `include_screen`. A check that fails is skipped: one broken
    source must not hide the rest."""
    checks = [idle_repos, deadlines, applications, lambda: meetings(now), lambda: proposals_waiting(now),
              lambda: drop_stuck(now)]
    if include_screen:
        checks += [diff_watch, lambda: screen_error(described)]
    found: list[Signal] = []
    for check in checks:
        try:
            found += check()
        except Exception:  # boundary: see the docstring
            continue
    return sorted(found, key=lambda s: (-s.weight, s.key))
