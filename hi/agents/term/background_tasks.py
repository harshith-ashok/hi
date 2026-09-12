"""Long-running shell commands (dev servers, watch-mode builds, log
tails) used to be redirected into a brand-new tmux pane
(`hi/agents/term/tmux_control.py`, now removed) — a physical pane the
user had to go look at, and the whole reason `term`'s shell tools only
worked inside a specific two-pane tmux layout at all.

Per explicit request to completely phase out that dependency and make
everything frontend-manageable instead ("spawn terminal instances as
separate task and assign agents instead of relying on the left pane"):
a long-running command now starts as a tracked background process —
the same in-memory-registry shape `hi/orchestrator/pending_actions.py`
already established (a `threading.Lock` + module dict, this process's
own runtime state) — pollable, tailable, and stoppable from any
frontend (the Agents view, currently), not a pane you have to be
looking at when it happens.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from uuid import uuid4

# Keep the in-memory tail bounded — a genuinely chatty dev server
# shouldn't grow this without limit for the life of the process.
_OUTPUT_TAIL_LINES = 500


@dataclass
class BackgroundProcess:
    id: str
    command: str
    cwd: str | None
    started_at: float
    process: subprocess.Popen = field(repr=False)
    output_lines: list[str] = field(default_factory=list, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def to_dict(self) -> dict:
        exit_code = self.process.poll()
        with self.lock:
            tail = list(self.output_lines[-_OUTPUT_TAIL_LINES:])
        return {
            "id": self.id,
            "command": self.command,
            "cwd": self.cwd,
            "started_at": self.started_at,
            "pid": self.process.pid,
            "status": "running" if exit_code is None else "exited",
            "exit_code": exit_code,
            "output_tail": "\n".join(tail),
        }


_lock = threading.Lock()
_processes: dict[str, BackgroundProcess] = {}


def _reader_thread(bp: BackgroundProcess) -> None:
    assert bp.process.stdout is not None
    for line in bp.process.stdout:
        with bp.lock:
            bp.output_lines.append(line.rstrip("\n"))
            if len(bp.output_lines) > _OUTPUT_TAIL_LINES * 2:
                bp.output_lines = bp.output_lines[-_OUTPUT_TAIL_LINES:]
    bp.process.wait()


def start_background_process(command: str, cwd: str | None = None) -> BackgroundProcess:
    """Starts `command` as a detached-from-any-terminal background
    process, capturing its combined stdout/stderr into a live-tailed
    buffer. Returns immediately — the reader thread keeps draining
    output in the background so `to_dict()` always has the latest tail
    without blocking whoever's polling it."""
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    bp = BackgroundProcess(id=uuid4().hex[:10], command=command, cwd=cwd, started_at=time.time(), process=process)
    with _lock:
        _processes[bp.id] = bp
    threading.Thread(target=_reader_thread, args=(bp,), daemon=True).start()
    return bp


def list_processes() -> list[BackgroundProcess]:
    with _lock:
        return sorted(_processes.values(), key=lambda p: p.started_at, reverse=True)


def get_process(process_id: str) -> BackgroundProcess | None:
    with _lock:
        return _processes.get(process_id)


def stop_process(process_id: str) -> bool:
    """Returns False for an unknown id or one that's already exited —
    the caller can't meaningfully "stop" either of those."""
    bp = get_process(process_id)
    if bp is None or bp.process.poll() is not None:
        return False
    bp.process.terminate()
    return True
