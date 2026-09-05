"""Deterministic, zero-network-call fast paths for common, repetitive
requests — a latency fix, at the user's explicit request, for the two
real cloud round trips (classify_with_plan(), then a persona agent's own
generation call) every normal turn otherwise pays even for something as
simple as "mute" or "what's on my todo list."

`maybe_fast_reply()` is checked BEFORE classification ever runs. A match
here skips BOTH round trips entirely and calls the real underlying tool
function directly — this is not a templated-looking answer, it's the
actual same tool a full agent turn would have called, just invoked
without an LLM in the loop to decide to call it.

Every match here is intentionally an EXACT (whole-message, case/
punctuation-insensitive) match against a small, well-known set of
phrasings, or a narrow regex that only extracts from an unambiguous
shape — never a keyword/substring check. "hi, also check my calendar"
or "quit safari and open chrome" must still go through real
classification; a fast path firing on a partial match risks silently
doing the wrong thing (or nothing), which is a far worse failure mode
than the couple of seconds this module exists to save.

Deliberately EXCLUDED, on purpose, not just unimplemented:
- `hi/agents/butler/todo.py`'s `complete_task()`/`remove_task()` — these
  fuzzy-match against the user's EXISTING tasks by free text; a wrong
  regex-guessed match would complete or delete the wrong item, a real
  mistake, not just a missed optimization. `list_tasks()` (read-only)
  and `add_task()` (additive, worst case an oddly-worded new task, never
  touches existing data) are safe enough for this treatment; those
  aren't.
- `hi/agents/butler/mac_control.py`'s `toggle_dnd()` when phrased as
  "turn on/off DND" — the tool only TOGGLES Focus state (macOS gives no
  stable way to read or set it directly), so "turn on DND" run while
  it's already on would incorrectly turn it OFF. Only the literal
  "toggle dnd" phrasing (which matches what the tool actually does) is
  fast-pathed; "turn on/off" goes through real classification instead.
- `term` persona commands (shell, file edits) — always genuinely
  open-ended and can have real side effects; bypassing the model's own
  judgment (and `hi/orchestrator/reviewer.py`'s destructive-command
  check) for these is exactly the kind of shortcut this project's
  philosophy warns against elsewhere.
- `docs` (vault search) — a "repetitive lookup" here still means
  searching arbitrary note content; there's no fixed small phrase set
  to template against.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

_GREETING_REPLIES = {
    "hi": "Hey — what can I help with?",
    "hello": "Hello! What can I help with?",
    "hey": "Hey — what's up?",
    "yo": "Hey — what's up?",
    "sup": "Not much — what do you need?",
    "thanks": "You're welcome!",
    "thank you": "You're welcome!",
    "thx": "You're welcome!",
    "ty": "You're welcome!",
    "bye": "See you!",
    "goodbye": "See you!",
    "good morning": "Good morning! What can I help with?",
    "good night": "Good night!",
    "morning": "Morning! What can I help with?",
}

_LIST_TASKS_PHRASES = {
    "list tasks", "list my tasks", "show tasks", "show my tasks",
    "what are my tasks", "my tasks", "todo list", "my todo list",
    "pending tasks", "what's pending", "whats pending",
    "what's on my todo list", "whats on my todo list",
}

_CLIPBOARD_READ_PHRASES = {
    "what's in my clipboard", "whats in my clipboard", "read clipboard",
    "read my clipboard", "show clipboard", "show my clipboard", "clipboard",
}

_RUNNING_APPS_PHRASES = {
    "what apps are running", "list running apps", "show running apps",
    "what's running", "whats running", "what's open", "whats open",
    "what apps are open", "which apps are running", "which apps are open",
}

_MUTE_PHRASES = {"mute", "mute volume", "mute the volume", "mute audio", "mute sound"}
_UNMUTE_PHRASES = {"unmute", "unmute volume", "unmute the volume", "unmute audio", "unmute sound"}
_DND_TOGGLE_PHRASES = {"toggle dnd", "toggle do not disturb", "toggle focus"}
_SCREENSHOT_PHRASES = {
    "take a screenshot", "take screenshot", "screenshot my screen",
    "screenshot the screen", "take a screenshot of my screen",
}

_VOLUME_RE = re.compile(r"^(?:set\s+)?(?:the\s+)?volume\s+(?:to\s+)?(\d{1,3})%?$")
# Both word orders ("turn on wifi" and "turn wifi on") are natural
# phrasings — an earlier version only covered "turn wifi on", missing
# the more common "turn on wifi", caught by testing both directly.
_WIFI_ON_RE = re.compile(r"^(?:turn on wifi|turn wifi on|enable wifi|wifi on)$")
_WIFI_OFF_RE = re.compile(r"^(?:turn off wifi|turn wifi off|disable wifi|wifi off)$")
# Bounded to a single, unconjoined app name — "quit safari and open chrome"
# must NOT match (a real multi-step request), so any "and"/"then"/","
# in the captured remainder falls through to real classification instead.
_QUIT_APP_RE = re.compile(r"^(?:quit|close|kill)\s+(?:the\s+)?(.+?)(?:\s+app)?$")
_MULTI_COMMAND_HINTS = (" and ", " then ", ",")
_ADD_TASK_RE = re.compile(
    r"^(?:add\s+(?:a\s+)?task\s*(?:to|:)?\s+|remind\s+me\s+to\s+|(?:todo|new\s+task):?\s+)(.+)$"
)


def _normalize(stripped: str) -> str:
    return stripped.lower().strip(" ?!.")


def maybe_fast_reply(stripped: str) -> tuple[str, str] | None:
    """Returns (persona_label, response_text) if `stripped` exactly
    matches a known fast-path phrasing, calling the real underlying tool
    directly — or None if it should go through normal classification."""
    normalized = _normalize(stripped)

    if normalized in _GREETING_REPLIES:
        return "hi", _GREETING_REPLIES[normalized]

    if normalized in _LIST_TASKS_PHRASES:
        from hi.agents.butler.todo import list_tasks

        return "butler", list_tasks.invoke({})

    add_task_match = _ADD_TASK_RE.match(normalized)
    if add_task_match:
        from hi.agents.butler.todo import add_task

        # The task text as the user actually typed it (not the
        # lowercased/stripped `normalized` copy used only for matching).
        original_match = _ADD_TASK_RE.match(stripped.strip())
        task_text = (original_match or add_task_match).group(1).strip()
        if task_text:
            return "butler", add_task.invoke({"text": task_text})

    if normalized in _CLIPBOARD_READ_PHRASES:
        from hi.agents.butler.mac_control import read_clipboard

        return "butler", read_clipboard.invoke({})

    if normalized in _RUNNING_APPS_PHRASES:
        from hi.agents.butler.mac_control import list_running_apps

        return "butler", list_running_apps.invoke({})

    if normalized in _MUTE_PHRASES:
        from hi.agents.butler.mac_control import mute

        return "butler", mute.invoke({})

    if normalized in _UNMUTE_PHRASES:
        from hi.agents.butler.mac_control import unmute

        return "butler", unmute.invoke({})

    if normalized in _DND_TOGGLE_PHRASES:
        from hi.agents.butler.mac_control import toggle_dnd

        return "butler", toggle_dnd.invoke({})

    if normalized in _SCREENSHOT_PHRASES:
        from hi.agents.butler.mac_control import take_screenshot

        path = str(Path.home() / "Desktop" / f"screenshot-{int(time.time())}.png")
        return "butler", take_screenshot.invoke({"path": path})

    volume_match = _VOLUME_RE.match(normalized)
    if volume_match:
        from hi.agents.butler.mac_control import set_volume

        return "butler", set_volume.invoke({"level": int(volume_match.group(1))})

    if _WIFI_ON_RE.match(normalized):
        from hi.agents.butler.mac_control import toggle_wifi

        return "butler", toggle_wifi.invoke({"state": "on"})

    if _WIFI_OFF_RE.match(normalized):
        from hi.agents.butler.mac_control import toggle_wifi

        return "butler", toggle_wifi.invoke({"state": "off"})

    quit_match = _QUIT_APP_RE.match(normalized)
    if quit_match:
        app_name = quit_match.group(1).strip()
        if app_name and not any(hint in f" {app_name} " for hint in _MULTI_COMMAND_HINTS):
            from hi.agents.butler.mac_control import quit_app

            # Still gated by quit_app()'s own confirm_destructive() — this
            # skips the two model round trips getting TO the confirm
            # prompt, not the human confirmation itself.
            return "butler", quit_app.invoke({"name": app_name})

    return None
