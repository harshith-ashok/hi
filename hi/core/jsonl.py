"""Read an append-only JSON-lines file, re-parsing it only when it has changed.

The logs `hi` keeps (proposals, schedule runs, usage) grow forever and are read far more often than written (the UI
polls them every few seconds), so parsing them on every read is wasted work. The parsed rows are cached against the
file's modified time and size: any append changes both, so a stale answer is not possible. A line that does not parse
(a write cut short by a crash) is skipped, not fatal. The returned list is shared: callers must not change it.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

MAX_CACHED_FILES = 32

_cache: dict[str, tuple[tuple[int, int], list[dict]]] = {}
_lock = threading.Lock()


def read(path: Path) -> list[dict]:
    """The objects in `path`, oldest first; [] if it does not exist."""
    try:
        stat = path.stat()
    except OSError:
        return []
    signature = (stat.st_mtime_ns, stat.st_size)
    key = str(path)
    with _lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] == signature:
            return hit[1]
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    rows: list[dict] = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    with _lock:
        if len(_cache) >= MAX_CACHED_FILES:
            _cache.clear()
        _cache[key] = (signature, rows)
    return rows
