"""Notifications you can answer. Anything the assistant wants to tell you (nudges, suggestions) is posted
here; the menu bar app (hi/menubar/app.py) shows each one as a toast with a reply box and logs what you did
with it. When the app isn't running, `deliver` returns False and the caller sends a plain macOS notification.

    ~/.hi/context/inbox.jsonl   posted messages, append-only: {id, ts, message, source}
    ~/.hi/context/inbox_log.jsonl   outcomes: {id, ts, message, outcome: answered | dismissed | ignored}

The outcomes are how the assistant learns to speak less: see `quiet_for` (used by hi/proactive.py).

`post` is the one gate every unprompted message passes (nudges, the heartbeat, schedules, approvals): it drops a
message it already showed today (`dedupe_key`), keeps to one shared interruption budget per hour, and stays quiet
after several ignored messages. Approvals, reminders, failures and anything marked urgent skip the budget and the
quiet period (they are things you are waiting for), but never the dedupe.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import date

import hi.config as config
from hi.context import now

INBOX = now.DIR / "inbox.jsonl"
LOG = now.DIR / "inbox_log.jsonl"
FRESH_SECONDS = 600  # a message older than this is stale news: not shown when the app starts
BACK_OFF_AFTER = 3  # this many unanswered messages in a row...
BACK_OFF_SECONDS = 3600  # ...silences nudges for this long
BUDGET = now.DIR.parent / "notify_times.json"  # when recent messages were shown, for the hourly budget
DEDUPE = now.DIR / "dedupe.json"  # {"day": ISO date, "keys": [...]}
BACKEND = "http://127.0.0.1:8765"
EXEMPT_KINDS = frozenset({"approval", "reminder", "failure"})
STATUSES = ("shown", "notified", "deduped", "budget", "quiet", "unsupported")


def _append(path, entry: dict) -> None:
    now.DIR.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _exempt(kind: str, priority: str) -> bool:
    return priority == "urgent" or kind in EXEMPT_KINDS


def budget_left() -> int:
    """Messages still allowed in the last hour (the shared interruption budget)."""
    try:
        times = json.loads(BUDGET.read_text())
    except (OSError, ValueError):
        times = []
    recent = [t for t in times if time.time() - t < 3600]
    BUDGET.parent.mkdir(parents=True, exist_ok=True)
    BUDGET.write_text(json.dumps(recent))
    return max(0, config.MAX_NOTIFICATIONS_PER_HOUR - len(recent))


def record_notification() -> None:
    try:
        times = json.loads(BUDGET.read_text())
    except (OSError, ValueError):
        times = []
    BUDGET.parent.mkdir(parents=True, exist_ok=True)
    BUDGET.write_text(json.dumps(times + [time.time()]))


def _seen_today(key: str) -> bool:
    try:
        data = json.loads(DEDUPE.read_text())
    except (OSError, ValueError):
        return False
    return data.get("day") == date.today().isoformat() and key in data.get("keys", [])


def _remember(key: str) -> None:
    try:
        data = json.loads(DEDUPE.read_text())
    except (OSError, ValueError):
        data = {}
    keys = data.get("keys", []) if data.get("day") == date.today().isoformat() else []
    now.DIR.mkdir(parents=True, exist_ok=True)
    DEDUPE.write_text(json.dumps({"day": date.today().isoformat(), "keys": [*keys, key][-500:]}))


def _system_notification(message: str) -> None:
    """A plain macOS notification, for when the menu bar app is not running."""
    text = json.dumps(message[:240], ensure_ascii=False)
    subprocess.run(["osascript", "-e", f"display notification {text} with title \"hi\""], check=False, timeout=5,
                   capture_output=True)


def post(message: str, source: str = "nudge", kind: str = "info", priority: str = "normal",
         dedupe_key: str = "", payload: dict | None = None) -> str:
    """Show `message` through the gate. Returns "shown" (in the island), "notified" (as a macOS notification because
    the app is closed), or why nothing was shown: "deduped", "budget", "quiet", "unsupported"."""
    if sys.platform != "darwin":
        return "unsupported"
    if dedupe_key and _seen_today(dedupe_key):
        return "deduped"
    exempt = _exempt(kind, priority)
    if not exempt:
        if budget_left() <= 0:
            return "budget"
        if quiet_for() > 0:
            return "quiet"
    from hi.menubar.lock import lock_is_free

    if dedupe_key:
        _remember(dedupe_key)
    if not exempt:
        record_notification()
    if lock_is_free():
        _system_notification(message)
        return "notified"
    _append(INBOX, {"id": uuid.uuid4().hex[:8], "ts": time.time(), "message": message, "source": source,
                    "kind": kind, "priority": priority, "payload": payload or {}})
    return "shown"


def deliver(message: str, source: str = "nudge") -> bool:
    """Post a plain message for the menu bar app. False when nothing was shown in it."""
    return post(message, source) == "shown"


def _http_post(url: str) -> str:
    request = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(request, timeout=10):
        return "ok"


def hint_for(item: dict) -> str:
    """The line shown under a message in the island: what you can do with it."""
    payload = item.get("payload") or {}
    if payload.get("truncated"):
        return "Too long to approve here: review it in tinyui"
    if item.get("kind") == "approval" or payload.get("proposal_id"):
        return "Reply yes to approve, no to deny" + (" (details in the Inbox)" if payload.get("report_id") else "")
    if payload.get("report_id"):
        return f"Full report in the Inbox: {payload['report_id']}"
    return ""


def approval_url(item: dict, approve: bool) -> str | None:
    payload = item.get("payload") or {}
    verb = "approve" if approve else "deny"
    if payload.get("proposal_id"):
        return f"{BACKEND}/proposals/{payload['proposal_id']}/{verb}"
    if payload.get("action_id"):
        return f"{BACKEND}/pending/{payload['action_id']}/{verb}"
    return None


_YES = frozenset({"y", "yes", "yep", "ok", "okay", "approve", "approved", "do it", "go ahead", "send it"})
_NO = frozenset({"n", "no", "nope", "deny", "denied", "cancel", "don't", "dont", "stop"})


def answer_approval(item: dict, text: str, send=_http_post) -> str | None:
    """If `text` answers an approval, send the answer to the backend and return what to show. None when the item is
    not an approval or the text is not a yes/no (the island then treats it as an ordinary reply)."""
    reply = text.strip().lower().rstrip(".!")
    if reply not in _YES | _NO:
        return None
    approve = reply in _YES
    if approve and (item.get("payload") or {}).get("truncated"):
        return "Too long to approve from here. Review it in tinyui."
    url = approval_url(item, approve)
    if url is None:
        return None
    try:
        send(url)
    except urllib.error.HTTPError as e:
        return "That was already answered." if e.code in (404, 409) else f"The backend said {e.code}."
    except (urllib.error.URLError, OSError) as e:
        return f"Can't reach hi's backend ({e}). Run `hi` to start it."
    return "Approved. Running it now." if approve else "Denied. Nothing was run."


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
