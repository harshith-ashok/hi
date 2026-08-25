"""Browser observation mode (TODO.md Phase 4, "browser observation mode
first"): on-demand reads of every *running* supported browser's current
tab (title + URL only, never page content — see hi/perception/privacy.py
for why this project doesn't do continuous/background observation).
Callable directly whenever a prompt calls for it — no separate enable
step (an earlier version required one; removed per explicit request, see
privacy.py's docstring) — gated only by privacy.py's sensitive-context
check, on every single call.

Deliberately checks which browsers are *running*, not which one is
frontmost — a real bug in the first version of this file, caught live: a
user asking "what tab do I have open" through `hi` is, by definition,
frontmost in their *terminal* at that exact moment, not their browser, so
a frontmost-only check meant the tool reported "no supported browser" on
essentially every real invocation. See _is_running()/_running_browsers().

Deliberately metadata-only, not a page-content scraper: if more than
"what tab is open" is wanted, the existing term Playwright MCP tools
(browser_navigate, browser_snapshot, ...) already fetch real page
content on request — this module's job is answering "what am I looking
at", composing with those rather than duplicating them. Also note those
Playwright tools drive their own separate, managed browser instance
(started by `npx @playwright/mcp`) — they were never capable of seeing
the user's actual open Safari/Chrome windows at all, which is the real
gap this module fills, via AppleScript instead.
"""

from __future__ import annotations

import subprocess

from langchain_core.tools import tool

from hi.perception.privacy import sensitive_context_reason

_TAB_SCRIPTS = {
    "Safari": (
        'tell application "Safari" to if (count of windows) > 0 then '
        "{URL of current tab of front window, name of current tab of front window}"
    ),
    "Google Chrome": (
        'tell application "Google Chrome" to if (count of windows) > 0 then '
        "{URL of active tab of front window, title of active tab of front window}"
    ),
    "Brave Browser": (
        'tell application "Brave Browser" to if (count of windows) > 0 then '
        "{URL of active tab of front window, title of active tab of front window}"
    ),
    "Microsoft Edge": (
        'tell application "Microsoft Edge" to if (count of windows) > 0 then '
        "{URL of active tab of front window, title of active tab of front window}"
    ),
}

# Accessibility-level window title (not the browser's own AppleScript
# dictionary — verified live that Safari's *own* "name of front window"
# omits the "Private Browsing" marker entirely, while System Events'
# accessibility-level query for the exact same window includes it) can be
# read for a specific process even while that process isn't frontmost —
# also verified live (Finder frontmost, Safari's title still readable).
# This is what makes a *per-browser* private-window check possible instead
# of only ever checking whatever happens to be frontmost right now.
_WINDOW_TITLE_SCRIPT = (
    'tell application "System Events" to tell process "{app}" to try\n'
    "  get name of front window\n"
    "end try"
)
SENSITIVE_TITLE_MARKERS = ("private browsing", "incognito")


def _is_running(app_name: str) -> bool:
    script = f'tell application "System Events" to (exists process "{app_name}")'
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return result.stdout.strip().lower() == "true"


def _running_browsers() -> list[str]:
    return [name for name in _TAB_SCRIPTS if _is_running(name)]


def _window_title(app_name: str) -> str | None:
    script = _WINDOW_TITLE_SCRIPT.format(app=app_name)
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return result.stdout.strip() or None


def _looks_private(title: str | None) -> bool:
    if not title:
        return False
    lowered = title.lower()
    return any(marker in lowered for marker in SENSITIVE_TITLE_MARKERS)


def _read_tab(browser: str) -> tuple[str, str] | None:
    script = _TAB_SCRIPTS[browser]
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    parts = [p.strip() for p in result.stdout.strip().split(",", 1)]
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


@tool
def observe_current_tab() -> str:
    """Read the current tab title and URL from every running supported
    browser (Safari/Chrome/Brave/Edge) — metadata only, never page
    content. Checks which browsers are actually *running*, not which one
    happens to be frontmost (asking through a terminal makes the
    terminal frontmost, not the browser, so a frontmost-only check would
    almost never find anything). Use for "what am I looking at" / "what
    tab is open" — callable directly, no enable step needed. Refuses
    entirely if a password manager is frontmost; separately, any
    individual browser whose window looks private/incognito is skipped
    rather than reported (best-effort — see hi/perception/privacy.py on
    what this can't detect).
    """
    reason = sensitive_context_reason()
    if reason:
        return f"Refused: {reason}"

    running = _running_browsers()
    if not running:
        return "No supported browser (Safari/Chrome/Brave/Edge) appears to be running."

    lines = []
    skipped_private = []
    for browser in running:
        if _looks_private(_window_title(browser)):
            skipped_private.append(browser)
            continue
        tab = _read_tab(browser)
        if tab:
            url, title = tab
            lines.append(f'{browser}: "{title}" — {url}')

    if skipped_private:
        lines.append(
            f"(skipped {', '.join(skipped_private)} — window looks private/incognito)"
        )
    return "\n".join(lines) if lines else "No readable browser window found."
