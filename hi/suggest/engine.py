"""Continuous suggestion engine (TODO.md Phase 4): the "surface via the
suggestion engine" line that Phase 1/2's watchdogs and trackers kept
deferring to, built now that there's real signal-producing infra
(hi/watchdogs/, hi/tracking/) to actually drive it. A standalone
background process (the same shape as hi/capture/hotkey.py's capture
daemon), not tied to any one `hi` session — these signals matter whether
or not a `hi` pane happens to be open right now.

Confidence gating: each signal only surfaces past a fixed, deterministic
threshold rather than an LLM judgment call — an idle repo needs open
tasks *and* to have actually crossed the idle-days threshold, a LeetCode
nudge only fires in the evening, a deadline nudge only inside its own
proximity window. A per-day dedup (~/.hi/suggest_state.json) stops the
same thing from renotifying every cycle.

Run with: hi --suggest-daemon
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from hi.capture.schema import Task
from hi.capture.store import list_items
from hi.config import DIFF_WATCH_ENABLED, SMART_SUGGESTIONS_ENABLED
from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model
from hi.perception import diff_watch
from hi.tracking.applications import due_follow_ups
from hi.tracking.deadlines import get_deadlines
from hi.tracking.leetcode import todays_log
from hi.watchdogs import context_shift
from hi.watchdogs.idle_repos import find_idle_repos

DEFAULT_INTERVAL_SECONDS = 30 * 60
DEADLINE_WINDOW_DAYS = 2
LEETCODE_NUDGE_HOUR = 18  # local time — no point nagging in the morning

STATE_PATH = Path.home() / ".hi" / "suggest_state.json"

_DATE_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d")


@dataclass
class Suggestion:
    key: str  # stable id, for per-day dedup
    message: str


def _parse_date(value: str) -> datetime | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _idle_repo_suggestions() -> list[Suggestion]:
    return [
        Suggestion(
            key=f"idle:{f.project}",
            message=f"'{f.project}' has been idle {f.days_idle} days with {f.open_task_count} open task(s).",
        )
        for f in find_idle_repos()
    ]


def _deadline_suggestions(window_days: int = DEADLINE_WINDOW_DAYS) -> list[Suggestion]:
    suggestions = []
    for d in get_deadlines():
        parsed = _parse_date(d.due)
        if parsed is None:
            continue
        days_until = (parsed.date() - date.today()).days
        if 0 <= days_until <= window_days:
            suggestions.append(
                Suggestion(key=f"deadline:{d.source}", message=f"'{d.title}' is due {d.due} ({days_until}d).")
            )
    return suggestions


def _leetcode_suggestion() -> list[Suggestion]:
    if datetime.now().hour < LEETCODE_NUDGE_HOUR or todays_log() is not None:
        return []
    return [
        Suggestion(
            key=f"leetcode:{date.today().isoformat()}",
            message="Today's LeetCode problem isn't logged yet.",
        )
    ]


def _application_suggestions() -> list[Suggestion]:
    return [
        Suggestion(key=f"application:{a.slug}", message=f"Follow up on '{a.target}' — no update since {a.date_sent}.")
        for a in due_follow_ups()
    ]


def _context_shift_suggestions() -> list[Suggestion]:
    """hi/watchdogs/context_shift.py's dwell state -> a gated Suggestion,
    same as every other signal here — never a parallel notification path.
    The key includes today's date (not the dwell duration), so this stays
    dedup'd like everything else in this file: at most one nudge per app
    per day, not one per 30-min cycle for as long as you stay put."""
    result = context_shift.dwell_suggestion()
    if result is None:
        return []
    app, minutes = result
    return [
        Suggestion(
            key=f"context-shift:{app}:{date.today().isoformat()}",
            message=f"'{app}' has been frontmost for {minutes}+ minutes without switching.",
        )
    ]


def _diff_watch_suggestions() -> list[Suggestion]:
    """hi/perception/diff_watch.py's unchanged-screen state -> a gated
    Suggestion — only when the user has explicitly opted in
    (DIFF_WATCH_ENABLED), since this is the one signal here with a
    genuinely different privacy posture (an interval screen watcher, not
    on-demand). Disabled means simply not surfaced, same as if nothing
    were detected — the watcher itself is never polled at all in that
    case (see run_suggest_daemon())."""
    if not DIFF_WATCH_ENABLED:
        return []
    minutes = diff_watch.unchanged_suggestion()
    if minutes is None:
        return []
    return [
        Suggestion(
            key=f"diff-watch:{date.today().isoformat()}",
            message=f"Your screen has looked the same for {minutes}+ minutes — still stuck, or just reading?",
        )
    ]


_NOTHING_MARKER = "NOTHING"


def _smart_suggestions(deterministic: list[Suggestion]) -> list[Suggestion]:
    """Model-judgment enrichment (TODO.md Phase 14, `BLOCKERS.md` ->
    "Suggested feature improvements" G) layered on top of every
    deterministic gate above — never a replacement for them, and this
    module's own fixed thresholds stay the always-on floor regardless of
    whether this succeeds. Only enabled via SMART_SUGGESTIONS_ENABLED
    (an extra real model call per cycle otherwise), and wrapped so that
    ANY failure here — a model error, a timeout, anything — degrades to
    "nothing extra to add" rather than breaking the unattended daemon
    loop that calls gather_suggestions() every cycle."""
    if not SMART_SUGGESTIONS_ENABLED:
        return []
    try:
        tasks = [t for t in list_items(kind="task") if isinstance(t, Task) and t.status == "pending"]
        if not tasks:
            return []
        task_lines = "\n".join(
            f"- {t.text} (priority={t.priority or 'none'}, due={t.due or 'none'}, project={t.project or 'none'})"
            for t in tasks[:20]
        )
        deterministic_lines = (
            "\n".join(f"- {s.message}" for s in deterministic) if deterministic else "(none)"
        )
        prompt = (
            "Below are real pending tasks and the suggestions a fixed, "
            "deterministic rule set already flagged today. Look for "
            "anything worth flagging that the fixed rules would miss — "
            "a pattern across several tasks together, something "
            "time-sensitive that doesn't fit a simple threshold. Do NOT "
            "repeat anything already in the deterministic list. Be "
            f"conservative — if nothing extra stands out, reply with "
            f"exactly the word {_NOTHING_MARKER} and nothing else. "
            "Otherwise reply with ONE short sentence.\n\n"
            f"Pending tasks:\n{task_lines}\n\n"
            f"Already flagged today:\n{deterministic_lines}"
        )
        model = get_tier_model("sonnet")
        reply = invoke_with_retry(model, [HumanMessage(prompt)]).strip()
        if not reply or reply.upper() == _NOTHING_MARKER:
            return []
        return [Suggestion(key=f"smart:{date.today().isoformat()}", message=reply)]
    except Exception:
        return []


def gather_suggestions() -> list[Suggestion]:
    deterministic = (
        _idle_repo_suggestions()
        + _deadline_suggestions()
        + _leetcode_suggestion()
        + _application_suggestions()
        + _context_shift_suggestions()
        + _diff_watch_suggestions()
    )
    return deterministic + _smart_suggestions(deterministic)


def _load_notified_today() -> set[str]:
    if not STATE_PATH.exists():
        return set()
    try:
        data = json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return set()
    today = date.today().isoformat()
    return {key for key, notified_on in data.items() if notified_on == today}


def _save_notified(keys: set[str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    STATE_PATH.write_text(json.dumps({key: today for key in keys}))


def _notify(message: str) -> None:
    script = f"display notification {json.dumps(message)} with title \"hi\""
    subprocess.run(["osascript", "-e", script], capture_output=True, text=True)


def run_once(notify: bool = True) -> list[Suggestion]:
    """Gather suggestions, drop anything already surfaced today, notify
    the rest (unless notify=False), and record them. Returns what was
    freshly surfaced this call — empty once everything's already been
    said today."""
    already_notified = _load_notified_today()
    suggestions = gather_suggestions()
    fresh = [s for s in suggestions if s.key not in already_notified]
    if notify:
        for s in fresh:
            _notify(s.message)
    _save_notified(already_notified | {s.key for s in fresh})
    return fresh


def run_suggest_daemon(interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> None:
    """The main suggestion cycle (idle repos/deadlines/LeetCode/
    applications/context-shift/diff-watch -> run_once()'s gate+dedup)
    still runs every `interval_seconds` (default 30min) — but
    context_shift.poll_once() (and diff_watch.poll_once(), if opted in)
    are polled on their own much tighter loop nested inside this one, per
    BLOCKERS.md's "every 30-60s"/"~2min" — state-change detection needs
    that cadence to actually catch a switch; the suggestion it might
    eventually produce doesn't need to be re-checked nearly that often.
    """
    poll_interval = min(
        context_shift.POLL_INTERVAL_SECONDS,
        diff_watch.POLL_INTERVAL_SECONDS if DIFF_WATCH_ENABLED else context_shift.POLL_INTERVAL_SECONDS,
    )
    print(
        f"Suggestion engine running, checking every {interval_seconds}s "
        f"(context-shift polled every {context_shift.POLL_INTERVAL_SECONDS}s"
        + (f", diff-watch every {diff_watch.POLL_INTERVAL_SECONDS}s" if DIFF_WATCH_ENABLED else "")
        + "). Ctrl-C to stop."
    )
    next_check = time.monotonic() + interval_seconds
    next_diff_watch = time.monotonic()
    while True:
        context_shift.poll_once()
        if DIFF_WATCH_ENABLED and time.monotonic() >= next_diff_watch:
            diff_watch.poll_once()
            next_diff_watch = time.monotonic() + diff_watch.POLL_INTERVAL_SECONDS
        if time.monotonic() >= next_check:
            for s in run_once():
                print(f"[suggested] {s.message}")
            next_check = time.monotonic() + interval_seconds
        time.sleep(poll_interval)


@tool
def check_suggestions() -> str:
    """Preview what the background suggestion engine would currently
    flag (idle repos, approaching deadlines, an unlogged LeetCode problem
    in the evening, application follow-ups, staying on the same app a
    long time without switching, — only if the user has opted into
    DIFF_WATCH_ENABLED — the screen looking unchanged for a while, and —
    only if opted into SMART_SUGGESTIONS_ENABLED — a real model-judgment
    pass looking for anything the fixed rules above would miss) without
    waiting for its next cycle or sending a system notification. Note:
    the app-dwell and screen-unchanged signals only reflect reality if
    the background daemon (`hi --suggest-daemon`) has actually been
    running recently to poll them — calling this tool alone doesn't poll
    fresh state for those two."""
    suggestions = gather_suggestions()
    if not suggestions:
        return "Nothing to flag right now."
    return "\n".join(s.message for s in suggestions)
