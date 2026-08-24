"""Opens a URL in the user's actual default browser — macOS's own `open`
command, which respects System Settings' default-browser choice and
gives a real, persistent tab, not a separate automation instance.

Extracted from hi/tracking/leetcode.py's original `_open_in_browser`
(same logic, same reasoning: an earlier version there used Playwright
MCP's `browser_navigate` and that opened a throwaway, separate
automation-controlled browser instead of the user's real one — verified
live, not assumed, and documented in TODO.md). Exposed here as a general
tool too, registered on both `butler` and `term`, since "open X in the
browser" is a real gap neither persona had a working answer for before
this: butler's `open_app` only launches a bare app with no way to
navigate it anywhere, and term had no browser-opening tool at all.
"""

from __future__ import annotations

import subprocess

from langchain_core.tools import tool


def open_url(url: str) -> str:
    # -g: open in the background, without stealing focus from wherever
    # the request came from (a terminal `hi` session, or the voice
    # companion's own panel).
    result = subprocess.run(["open", "-g", url], capture_output=True, text=True)
    if result.returncode != 0:
        return f"Failed to open '{url}': {result.stderr.strip() or 'unknown error'}"
    return f"Opened {url} in your default browser."


@tool
def open_url_in_browser(url: str) -> str:
    """Open a URL in the user's actual default browser — a real,
    persistent tab, not a separate automation browser. Use this whenever
    asked to open a website or link, e.g. "open youtube in safari" or
    "open github.com/foo/bar".

    Args:
        url: The URL to open, e.g. "https://youtube.com". Add "https://"
            if the user's request didn't include a scheme.
    """
    return open_url(url)
