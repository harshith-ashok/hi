"""Flags shell commands that delete files or folders (so
`term` can pause for a y/n confirmation before running them) or long-
running (so `run_shell_command` can redirect them to their own pane
instead of waiting on them). Both are heuristics, not a sandbox or a
process inspector — they only gate behavior, not what a command is
capable of doing or how long it might actually run.
"""

import re

# Deletion only — the one thing that asks for confirmation. Everything else
# (mv, sudo, redirects, kill, force-push, ...) runs without asking.
_DESTRUCTIVE_PATTERNS = [
    r"\brm\b",
    r"\brmdir\b",
    r"\bunlink\b",
    r"\bshred\b",
    r"\btrash\b",
    r"\bfind\b.*-delete\b",
    r"\bgit\s+clean\s+-[a-z]*f",
]

_DESTRUCTIVE_RE = re.compile("|".join(_DESTRUCTIVE_PATTERNS))


def looks_destructive(command: str) -> bool:
    return bool(_DESTRUCTIVE_RE.search(command))


_LONG_RUNNING_PATTERNS = [
    r"\bnpm\s+(run\s+)?(dev|start|watch)\b",
    r"\byarn\s+(dev|start|watch)\b",
    r"\bpnpm\s+(run\s+)?(dev|start|watch)\b",
    r"\bvite\b",
    r"\bnext\s+dev\b",
    r"\bnodemon\b",
    r"\bflask\s+run\b",
    r"\buvicorn\b",
    r"\bgunicorn\b",
    r"\brails\s+s(erver)?\b",
    r"\bbench\s+start\b",
    r"\bdocker\s+compose\s+up\b(?!.*-d\b)",
    r"\bdocker-compose\s+up\b(?!.*-d\b)",
    r"\btail\s+-f\b",
    r"\bwatch\s+",
    r"\bhttp\.server\b",
]

_LONG_RUNNING_RE = re.compile("|".join(_LONG_RUNNING_PATTERNS))


def looks_long_running(command: str) -> bool:
    return bool(_LONG_RUNNING_RE.search(command))
