"""Shared run state for the orchestrator (TODO.md Phase 16): LangGraph's
own `AsyncSqliteSaver` checkpointer, not a bespoke store — `BLOCKERS.md`'s
own point was that this project already depends on LangGraph without
using its multigraph/checkpointer support; this is that support, put to
actual use for the first time. One shared SQLite file under `~/.hi/`, so
an orchestrated run's state survives a crash mid-DAG — LangGraph resumes
a checkpointed graph from its last completed node on a later
`.ainvoke()` with the same `thread_id`, instead of restarting the whole
plan from scratch.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

CHECKPOINT_PATH = Path.home() / ".hi" / "orchestrator_runs.db"


@asynccontextmanager
async def checkpointer():
    """Yields a ready-to-use AsyncSqliteSaver, creating `~/.hi/` if
    needed. One connection per run (opened/closed around a single
    `run_orchestrated()` call in graph.py) rather than a long-lived
    shared handle — orchestrated runs are infrequent enough that
    per-run connection overhead is not worth the complexity of keeping
    one open across the process lifetime."""
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_PATH)) as saver:
        yield saver
