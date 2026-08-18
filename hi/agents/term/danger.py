"""Flags shell commands that look destructive or hard to reverse, so
`term` can pause for a y/n confirmation before running them. A heuristic,
not a sandbox — it only gates the confirmation prompt, not what the
command is capable of doing.
"""

import re

_DESTRUCTIVE_PATTERNS = [
    r"\brm\b",
    r"\bmv\b",
    r"\bsudo\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bdd\b",
    r"\bmkfs(\.\w+)?\b",
    r"\bkill(all)?\b",
    r"\bpkill\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r">>?",
    r"\bgit\s+push\s+.*--force",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-z]*f",
    r"\|\s*(sh|bash|zsh)\b",
]

_DESTRUCTIVE_RE = re.compile("|".join(_DESTRUCTIVE_PATTERNS))


def looks_destructive(command: str) -> bool:
    return bool(_DESTRUCTIVE_RE.search(command))
