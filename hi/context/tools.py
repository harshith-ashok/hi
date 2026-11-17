"""Tools over the always-on context. They run on the Mac (host bridge) because the snapshot lives there."""

from __future__ import annotations

from langchain_core.tools import tool

from hi.context import now


@tool
def current_context(include_screen: bool = True) -> str:
    """What the user is doing on their Mac right now: frontmost app and window, how long, a one-line
    summary, busiest processes, recent apps and the visible screen text. Use for 'what am I doing',
    'what is this error', 'summarize what's on my screen' before asking the user to paste anything.

    Args:
        include_screen: Include the OCR text of the screen. Set false for just the app/activity.
    """
    return now.describe(include_screen) or "No live context (the context daemon isn't running, or it is paused)."


@tool
def pause_screen_context() -> str:
    """Stop the always-on screen/context reading until resume_screen_context is called."""
    now.DIR.mkdir(parents=True, exist_ok=True)
    now.PAUSED.touch()
    return "Screen context paused. Nothing is being read."


@tool
def resume_screen_context() -> str:
    """Resume the always-on screen/context reading."""
    now.PAUSED.unlink(missing_ok=True)
    return "Screen context resumed."


@tool
def post_to_inbox(message: str, kind: str = "info", priority: str = "normal", dedupe_key: str = "", payload_json: str = "{}") -> str:
    """Show a message in the menu bar island (or as a macOS notification when the app is closed), through the
    interruption gate. Returns shown, notified, deduped, budget, quiet or unsupported.

    Args:
        message: One plain sentence, at most 25 words.
        kind: info, digest, approval, reminder or failure.
        priority: low, normal or urgent.
        dedupe_key: Messages with the same key are shown once per day.
        payload_json: JSON object with report_id, proposal_id or action_id, used by the island's reply handling.
    """
    import json

    from hi.context import inbox

    try:
        payload = json.loads(payload_json or "{}")
    except ValueError:
        payload = {}
    return inbox.post(message, "automation", kind, priority, dedupe_key, payload if isinstance(payload, dict) else {})


@tool
def recent_activity(minutes: int = 30) -> str:
    """What the user spent the last few minutes on, per window, with how long each took. Runs on the Mac.

    Args:
        minutes: How far back to look.
    """
    return now.recent_activity(minutes)
