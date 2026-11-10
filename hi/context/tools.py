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
