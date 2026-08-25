"""Shared privacy gate for hi/perception/: both browser observation and
screen/OCR capture go through sensitive_context_reason() below before
reading anything.

Originally also had a separate enable/disable toggle per mode (a
"pause/toggle" step gating whether a tool could be called at all) — removed
per explicit request: the friction of a required prior "enable X" step
before a tool that's contextually obviously wanted (the prompt itself
calls for it — "what tab am I on", "what's on my screen") wasn't wanted.
The toggle was one layer of the original design, not the only one — the
protections that actually matter stay:

- Still strictly on-demand, never a background/continuous watcher. Every
  read is triggered by one specific tool call answering one specific
  question — there is no interval loop, no history log, nothing running
  between turns. Removing the toggle didn't change this; a tool being
  reachable without a prior enable step is not the same as it running
  unprompted.
- sensitive_context_reason() below still gates every single call, with no
  opt-out — a password manager frontmost, or a window that looks private/
  incognito, refuses regardless of what the prompt asked for. This is
  best-effort defense-in-depth, not a guarantee — said plainly rather than
  oversold. It can't see inside a browser's actual per-tab incognito state
  (Chromium browsers don't expose that over AppleScript), only whether a
  password-manager app is frontmost, or an actual "Private Browsing"/
  "Incognito" marker a window happens to put in its own title (verified
  Safari does this for private windows; Chromium-based browsers were not
  verified to and likely don't).
"""

from __future__ import annotations

import subprocess

SENSITIVE_APP_NAMES = {
    "1password",
    "1password 7",
    "1password 8",
    "bitwarden",
    "keychain access",
    "lastpass",
    "keepassxc",
    "dashlane",
}

SENSITIVE_TITLE_MARKERS = ("private browsing", "incognito")


def frontmost_app_name() -> str | None:
    result = subprocess.run(
        [
            "osascript",
            "-e",
            'tell application "System Events" to get name of first application '
            "process whose frontmost is true",
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None


def frontmost_window_title() -> str | None:
    script = (
        'tell application "System Events" to tell (first application process '
        "whose frontmost is true) to try\n"
        "  get name of front window\n"
        "end try"
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return result.stdout.strip() or None


def sensitive_context_reason() -> str | None:
    """Returns a human-readable reason capture should be refused right
    now, or None if it's fine to proceed. Best-effort — see module
    docstring for what this can't see."""
    app = frontmost_app_name()
    if app and app.lower() in SENSITIVE_APP_NAMES:
        return f"'{app}' (a password/credential manager) is the active app."
    title = frontmost_window_title()
    if title:
        lowered = title.lower()
        for marker in SENSITIVE_TITLE_MARKERS:
            if marker in lowered:
                return f"the active window looks like a private/incognito browsing window ('{title}')."
    return None
