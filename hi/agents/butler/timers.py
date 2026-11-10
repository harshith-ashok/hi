"""Timers: set, list, cancel. State lives in ~/.hi/timers.json (the filesystem is the source of truth).

Each timer is a detached `python -m hi.agents.butler.timers run <id>` process that sleeps until the timer is
due, re-checks the file (so a cancel wins), then notifies and speaks. No model is involved after parsing, so
a timer fires the same whether or not hi is still open. Timers do not survive a reboot (they are dropped).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

from langchain_core.tools import tool

PATH = Path.home() / ".hi" / "timers.json"


def _load() -> dict[str, dict]:
    try:
        return json.loads(PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save(timers: dict[str, dict]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(timers, indent=2))


def _spoken(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    parts = [f"{n} {unit}{'s' if n != 1 else ''}" for n, unit in ((hours, "hour"), (minutes, "minute"), (secs, "second")) if n]
    return " ".join(parts) or "0 seconds"


def _alert(label: str) -> None:
    text = f"Timer done: {label}" if label else "Timer done"
    script = f'display notification "{text}" with title "hi" sound name "Glass"'
    subprocess.run(["osascript", "-e", script], capture_output=True)
    subprocess.run(["say", text], capture_output=True)


@tool
def set_timer(seconds: int, label: str = "") -> str:
    """Start a countdown timer that notifies and speaks when it ends.

    Args:
        seconds: Duration in seconds (convert minutes/hours first).
        label: What it is for, e.g. "pasta". Optional.
    """
    if seconds <= 0:
        return "A timer needs a positive duration."
    timer_id = uuid.uuid4().hex[:6]
    timers = _load()
    timers[timer_id] = {"due": time.time() + seconds, "label": label}
    _save(timers)
    subprocess.Popen(
        [sys.executable, "-m", "hi.agents.butler.timers", "run", timer_id],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    return f"Timer set for {_spoken(seconds)}" + (f" ({label})." if label else ".")


@tool
def list_timers() -> str:
    """List running timers and how long each has left."""
    now = time.time()
    live = {k: v for k, v in _load().items() if v["due"] > now}
    if not live:
        return "No timers running."
    return "\n".join(f"- {v['label'] or k}: {_spoken(int(v['due'] - now))} left" for k, v in sorted(live.items(), key=lambda kv: kv[1]["due"]))


@tool
def cancel_timer(label: str = "") -> str:
    """Cancel a timer by label, or all timers if no label is given.

    Args:
        label: Part of the timer's label. Empty cancels every timer.
    """
    timers = _load()
    hit = [k for k, v in timers.items() if not label or label.lower() in v["label"].lower()]
    for k in hit:
        del timers[k]
    _save(timers)
    return f"Cancelled {len(hit)} timer{'s' if len(hit) != 1 else ''}." if hit else "No matching timer."


def _run(timer_id: str) -> None:
    """Wait until due, polling the file so a cancel makes this process exit promptly."""
    while True:
        timers = _load()
        if timer_id not in timers:  # cancelled
            return
        remaining = timers[timer_id]["due"] - time.time()
        if remaining <= 0:
            break
        time.sleep(min(remaining, 5))
    label = timers.pop(timer_id)["label"]
    _save(timers)
    _alert(label)


if __name__ == "__main__" and sys.argv[1:2] == ["run"]:
    _run(sys.argv[2])
