"""Shared read/write helper for `~/.hi/.env` — the same file
`hi/config.py` parses at import time. Extracted out of
`hi/mcp_install.py` (which needed a writer first) so the native app's
Settings screen (`hi/ipc/server.py`'s `POST /config`) and any future
conversational config tool share one write path instead of two copies
drifting apart.
"""

from __future__ import annotations

from pathlib import Path

ENV_PATH = Path.home() / ".hi" / ".env"


def write_env_var(key: str, value: str, path: Path = ENV_PATH) -> None:
    """Replaces `key`'s line in `path` if present, else appends it —
    same simple `KEY=value` shape `hi/config.py`'s own `_parse_env()`
    reads back. Quoted only if the value contains a space or '#' (either
    would otherwise be misread as ending the value or starting a
    comment); real API tokens/model names/paths are alnum/dash/
    underscore/dot/slash and never need this."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text().splitlines() if path.exists() else []
    needs_quoting = any(c in value for c in " #")
    new_line = f'{key}="{value}"' if needs_quoting else f"{key}={value}"

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
            lines[i] = new_line
            break
    else:
        lines.append(new_line)
    path.write_text("\n".join(lines) + "\n")
