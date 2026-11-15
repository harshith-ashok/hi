"""Notifications you can answer. Anything the assistant wants to tell you (nudges, suggestions) is posted
here; the menu bar app (hi/menubar/app.py) shows each one as a toast with a reply box and logs what you did
with it. When the app isn't running, `deliver` returns False and the caller sends a plain macOS notification.

    ~/.hi/context/inbox.jsonl   posted messages, append-only: {id, ts, message, source}
    ~/.hi/context/inbox_log.jsonl   outcomes: {id, ts, message, outcome: answered | dismissed | ignored}

The outcomes are how the assistant learns to speak less: see `quiet_for` (used by hi/proactive.py).
"""

from __future__ import annotations

import json
import sys
import time
import uuid

from hi.context import now

INBOX = now.DIR / "inbox.jsonl"
LOG = now.DIR / "inbox_log.jsonl"
FRESH_SECONDS = 600  # a message older than this is stale news: not shown when the app starts
BACK_OFF_AFTER = 3  # this many unanswered messages in a row...
BACK_OFF_SECONDS = 3600  # ...silences nudges for this long


def _append(path, entry: dict) -> None:
    now.DIR.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def deliver(message: str, source: str = "nudge") -> bool:
    """Post `message` for the menu bar app. False (nothing posted) when it isn't running."""
    if sys.platform != "darwin":
        return False
    from hi.menubar.lock import lock_is_free

    if lock_is_free():
        return False
    _append(INBOX, {"id": uuid.uuid4().hex[:8], "ts": time.time(), "message": message, "source": source})
    return True


def _handled_ids() -> set[str]:
    try:
        return {json.loads(line)["id"] for line in LOG.read_text().splitlines() if line.strip()}
    except OSError:
        return set()


def read_from(offset: int) -> tuple[list[dict], int]:
    """(new messages since byte `offset`, new offset). Skips messages older than FRESH_SECONDS and any that
    already have an outcome (so restarting the app does not show an answered message again)."""
    try:
        with INBOX.open("rb") as f:
            f.seek(offset)
            data = f.read()
    except OSError:
        return [], offset
    items = [json.loads(line) for line in data.decode().splitlines() if line.strip()]
    handled = _handled_ids() if items else set()
    return [i for i in items if time.time() - i["ts"] < FRESH_SECONDS and i["id"] not in handled], offset + len(data)


def end_offset() -> int:
    try:
        return INBOX.stat().st_size
    except OSError:
        return 0


def log_outcome(item: dict, outcome: str) -> None:
    _append(LOG, {"id": item["id"], "ts": time.time(), "message": item["message"], "outcome": outcome})


def quiet_for() -> float:
    """Seconds nudges should stay quiet: the last BACK_OFF_AFTER outcomes were all unanswered."""
    try:
        recent = [json.loads(line) for line in LOG.read_text().splitlines()[-BACK_OFF_AFTER:]]
    except OSError:
        return 0.0
    if len(recent) < BACK_OFF_AFTER or any(r["outcome"] == "answered" for r in recent):
        return 0.0
    return max(0.0, recent[-1]["ts"] + BACK_OFF_SECONDS - time.time())
