"""On-demand health check for dev-server/watch-mode processes, reusing
hi/agents/term/danger.py's existing looks_long_running() detection (the
same heuristic that already redirects `npm run dev`/`vite`/etc. to their
own tmux pane) to identify *which* running processes count, rather than
inventing a second classifier.

This is a snapshot check, not a continuous background monitor: a real
crash-loop only shows up over repeated sampling across time, which needs
the suggestion-engine's continuous loop (Phase 4 of TODO.md) to run
unattended between `hi` sessions. What's built here — two quick samples a
couple seconds apart — genuinely catches a restart that happens to occur
inside that short window, and is honest about not catching a slower loop;
it's the reusable core a Phase 4 background version would still want.
"""

from __future__ import annotations

import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from langchain_core.tools import tool

from hi.agents.term.danger import looks_long_running

_SAMPLE_GAP_SECONDS = 2.0


@dataclass
class _Snapshot:
    pid: str
    etime: str
    command: str


def _ps_snapshot() -> list[_Snapshot]:
    result = subprocess.run(["ps", "-eo", "pid,etime,command"], capture_output=True, text=True)
    snapshots = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, etime, command = parts
        if looks_long_running(command):
            snapshots.append(_Snapshot(pid=pid, etime=etime, command=command))
    return snapshots


def _check_http(port: int, timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}", timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True  # any real HTTP response (even 4xx/5xx) means it's up
    except Exception:
        return False


@tool
def check_dev_servers(port: int | None = None) -> str:
    """Check the health of currently-running dev-server/watch-mode
    processes (npm run dev, vite, uvicorn, etc.): whether each is still
    alive, whether it looks like it just restarted (a possible sign of a
    crash loop), and optionally whether a given local port is actually
    answering HTTP requests. Use this when asked whether a dev server is
    still running or working.

    Args:
        port: Optional local port to check with a real HTTP request, e.g. 5173.
    """
    first = _ps_snapshot()
    if not first:
        return "No dev-server-shaped processes currently running."

    time.sleep(_SAMPLE_GAP_SECONDS)
    second_by_command = {s.command: s for s in _ps_snapshot()}

    lines = []
    for snap in first:
        still = second_by_command.get(snap.command)
        if still is None:
            lines.append(f"[gone] {snap.command} (pid {snap.pid}, was up {snap.etime})")
        elif still.pid != snap.pid:
            lines.append(
                f"[possible restart] {snap.command} — pid changed {snap.pid} -> {still.pid} "
                f"within the last {_SAMPLE_GAP_SECONDS:.0f}s"
            )
        else:
            lines.append(f"[alive] {snap.command} (pid {snap.pid}, up {snap.etime})")

    if port is not None:
        ok = _check_http(port)
        lines.append(f"http://127.0.0.1:{port} — {'responding' if ok else 'not responding'}")

    return "\n".join(lines)
