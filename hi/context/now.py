"""Reader for the always-on context snapshot written by hi/context/daemon.py.

The daemon runs natively on the Mac (screen and Accessibility permissions need that) and keeps
~/.hi/context/now.json fresh. Anything on the Mac reads the file directly; the Dockerized backend
asks the host bridge for the same text (`current_context` tool).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

DIR = Path.home() / ".hi" / "context"
NOW = DIR / "now.json"
HISTORY = DIR / "history.jsonl"
PAUSED = DIR / "paused"
PINNED = DIR / "pinned.json"  # the screen as it was when the menu bar prompt opened (hi/menubar/app.py)
PINNED_SECONDS = 300
STALE_SECONDS = 30  # the daemon writes every few seconds; older than this means it is not running
SCREEN_CHARS = 1200


def read() -> dict | None:
    try:
        return json.loads(NOW.read_text())
    except (OSError, ValueError):
        return None


def recent_history(minutes: int = 60, limit: int = 8) -> list[dict]:
    cutoff = time.time() - minutes * 60
    try:
        lines = HISTORY.read_text().splitlines()[-200:]
    except OSError:
        return []
    items = [json.loads(line) for line in lines if line.strip()]
    return [i for i in items if i["ts"] >= cutoff][-limit:]


def _ago(seconds: float) -> str:
    return f"{int(seconds // 60)} min" if seconds >= 90 else f"{int(seconds)} s"


def _pinned_block() -> str:
    """The screen the user was looking at when they opened the menu bar prompt, if that was just now."""
    try:
        pinned = json.loads(PINNED.read_text())
    except (OSError, ValueError):
        return ""
    age = time.time() - pinned["ts"]
    if age > PINNED_SECONDS or not pinned.get("screen"):
        return ""
    return (f"The user {PINNED_MARK} ({_ago(age)} ago) while looking at {pinned['app']}"
            + (f" — {pinned['title']}" if pinned.get("title") else "")
            + ". Their question is most likely about this screen. "
            "Text on it:\n" + pinned["screen"][:SCREEN_CHARS * 2])


PINNED_MARK = "just opened the menu bar prompt"


def pinned_text() -> str | None:
    """OCR text of the screen the user was looking at when they opened the menu bar prompt, if that was
    just now. read_screen / ask_about_screen return this instead of taking a second screenshot."""
    try:
        pinned = json.loads(PINNED.read_text())
    except (OSError, ValueError):
        return None
    if time.time() - pinned["ts"] > PINNED_SECONDS or not pinned.get("screen"):
        return None
    return f"(Screen as it was when the user opened the menu bar prompt, {pinned['app']} — {pinned['title']}):\n{pinned['screen']}"


def describe(include_screen: bool = True) -> str:
    """Markdown block: what the user is doing right now. '' when there is no fresh snapshot."""
    text = _describe(include_screen)
    pinned = _pinned_block() if include_screen else ""
    return f"{text}\n\n{pinned}".strip() if pinned else text


def _describe(include_screen: bool) -> str:
    if sys.platform != "darwin":  # in Docker: ask the Mac
        from hi import host

        text = host.call("current_context", {"include_screen": include_screen})
        return "" if text.startswith(("Can't reach", "The Mac bridge", "Mac bridge error")) else text
    now = read()
    if not now or time.time() - now["ts"] > STALE_SECONDS:
        return ""
    if now.get("paused") or now.get("private"):
        return "Screen context is paused or hidden right now (private app or the user paused it)."
    lines = [f"Frontmost: {now['app']}" + (f" — {now['title']}" if now.get("title") else "")
             + f" (for {_ago(time.time() - now['since'])}; user idle {_ago(now['idle'])})"]
    if now.get("activity"):
        lines.append(f"Looks like: {now['activity']}")
    if now.get("processes"):
        lines.append("Busiest processes: " + ", ".join(now["processes"]))
    earlier = [f"{i['app']}" + (f" ({i['activity']})" if i.get("activity") else "") for i in recent_history()[:-1]]
    if earlier:
        lines.append("Earlier this hour: " + " → ".join(earlier))
    if include_screen and now.get("screen") and not _pinned_block():
        lines.append("Text visible on screen:\n" + now["screen"][:SCREEN_CHARS])
    return "\n".join(lines)
