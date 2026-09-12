"""The DAG executor (TODO.md Phase 16): takes a `planner.py`-produced
task DAG and actually runs it. Builds a real LangGraph `StateGraph` —
one node per task, edges per `depends_on` — so LangGraph's own
execution engine handles the topological scheduling: async node
functions with no unmet dependency run concurrently under `.ainvoke()`,
no hand-rolled scheduler needed once the graph itself is shaped
correctly (`BLOCKERS.md`'s own point about actually using LangGraph's
multigraph support, not adding a second framework beside it). An
`asyncio.Semaphore` is layered *inside* each node to bound how many
subagents can be mid-model-call at once — LangGraph schedules the DAG,
the semaphore separately caps real concurrency against a finite model
pool.

Checkpointed via `blackboard.py`'s `AsyncSqliteSaver` — a crash mid-DAG
can resume from the last completed node on a retry with the same
`run_id`, instead of restarting the whole plan from scratch.

`DAGEvent`/`event_queue` (TODO.md Phases 18/19): each node pushes its
own start/finish/error/retry milestones into an optional shared queue
as they happen — the ONE live-progress mechanism two different
consumers drain: `hi/repl.py`'s tmux status line (Phase 19, plain
prints) and `hi/agui_adapter.py`'s `SUBAGENT_STARTED`/`FINISHED` events
(Phase 18, for the voice companion/any AG-UI client) — not two separate
plumbing paths for the same underlying progress. Deliberately a plain,
presentation-agnostic dataclass here, not an AG-UI event type directly
— this module has no reason to depend on the AG-UI SDK, only
`hi/agui_adapter.py` does.

Scoped scratch space per run (TODO.md Phase 20): every run gets its own
private temp directory under `~/.hi/scratch/<run_id>/`, created before
the DAG starts and deleted once it finishes (success or failure) — a
task that shells out to write an intermediate file has somewhere to put
it that can't collide with a concurrent run's own files or the user's
actual vault/cwd, and doesn't need manual cleanup after. Every node's
own prompt content is told this path; nothing else about the directory
is special-cased — it's a plain, empty folder each subagent's normal
tool calls (`run_shell_command`, mainly) can read/write like any other.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from datetime import datetime
from operator import ior
from pathlib import Path
from typing import Annotated, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from hi.models import get_tier_model
from hi.orchestrator import aggregator
from hi.orchestrator.blackboard import checkpointer
from hi.orchestrator.pending_actions import mark_orchestrated_active, mark_orchestrated_done
from hi.orchestrator.planner import TaskSpec, plan_tasks
from hi.orchestrator.subagent import build_subagent
from hi.vault import conversations_dir, with_frontmatter

def _runs_dir():
    return conversations_dir() / "runs"
SCRATCH_ROOT = Path.home() / ".hi" / "scratch"
MAX_CONCURRENT_MODEL_CALLS = 3  # more than this and the Ollama Cloud account chokes

# TODO.md Phase 20 ("auto-retry with tier escalation"): the one-step-up
# order for each tier, tried once before a task is allowed to fail for
# real. Retrying at the SAME tier would just repeat whatever went
# wrong; opus is already the top, so a failed opus task has nowhere
# higher to escalate to and is retried at the same tier instead (still
# a genuine second attempt — real transient failures do happen — just
# not a *stronger* one).
_TIER_ESCALATION = {"haiku": "sonnet", "sonnet": "opus", "opus": "opus"}


@dataclass(frozen=True)
class DAGEvent:
    kind: str  # "subagent_started" | "subagent_retrying" | "subagent_finished" | "subagent_error"
    task_id: str
    persona: str = ""
    text: str = ""


class OrchestratorState(TypedDict):
    results: Annotated[dict[str, str], ior]
    tool_calls: Annotated[dict[str, list[str]], ior]


def _emit(event_queue: asyncio.Queue[DAGEvent] | None, event: DAGEvent) -> None:
    if event_queue is not None:
        event_queue.put_nowait(event)


async def _run_subagent_once(task: TaskSpec, tier: str, content: str) -> tuple[str, list[str]]:
    """One real attempt: builds a subagent at `tier` (which may differ
    from `task.tier` on a retry — see `_TIER_ESCALATION`) and invokes it
    with `content`. Raises on failure rather than swallowing it — the
    caller decides whether to retry."""
    model = get_tier_model(tier)
    agent = build_subagent(model, task.persona, task.tool_scope or None, task.archetype or None)
    # TODO.md Phase 17: marks the window in which a destructive tool
    # call (run_shell_command, confirm_destructive()) must route to the
    # async pending-approval queue instead of a blocking input() —
    # there's no terminal pane a subagent's own confirmation prompt
    # could sensibly appear in. Always unmarked in the finally, even on
    # a crash, so a failed subagent can't leave a normal interactive
    # turn permanently mistaken for an orchestrated one afterward.
    mark_orchestrated_active()
    try:
        result = await agent.ainvoke({"messages": [{"role": "user", "content": content}]})
    finally:
        mark_orchestrated_done()

    messages = result.get("messages", [])
    final_text = messages[-1].content if messages else ""
    tool_names = [
        call["name"]
        for m in messages
        if getattr(m, "tool_calls", None)
        for call in m.tool_calls
    ]
    return final_text, tool_names


def _make_node(
    task: TaskSpec, semaphore: asyncio.Semaphore, event_queue: asyncio.Queue[DAGEvent] | None,
    scratch_dir: Path,
):
    async def node(state: OrchestratorState) -> dict:
        # depends_on governs more than execution ORDER — LangGraph
        # already guarantees this node only runs once every dependency
        # is done, but a dependent task also needs the actual DATA those
        # tasks produced, not just a description that refers to them
        # abstractly. Caught live: without this, a "compare X and Y"
        # task that depends on the tasks that looked up X and Y ran
        # right on schedule but had no idea what they'd actually found.
        parts = [
            f"Scratch directory for this run (a private, temporary "
            f"folder just for this task DAG — safe to read/write freely, "
            f"deleted once the whole run finishes): {scratch_dir}"
        ]
        parts.extend(
            f"Result of task {dep_id}:\n{state['results'][dep_id]}"
            for dep_id in task.depends_on
            if dep_id in state["results"]
        )
        content = "\n\n".join(parts) + f"\n\n---\n\nYour task: {task.description}"

        _emit(event_queue, DAGEvent(kind="subagent_started", task_id=task.id, persona=task.persona))

        async with semaphore:
            try:
                final_text, tool_names = await _run_subagent_once(task, task.tier, content)
            except Exception as first_error:
                # TODO.md Phase 20: one real retry, at the next tier up
                # — a genuinely different (usually stronger) model
                # attempting the same task, not just repeating the
                # identical call and hoping for a different result.
                escalated_tier = _TIER_ESCALATION[task.tier]
                _emit(event_queue, DAGEvent(
                    kind="subagent_retrying", task_id=task.id, persona=task.persona,
                    text=f"{type(first_error).__name__}: {first_error}",
                ))
                try:
                    final_text, tool_names = await _run_subagent_once(task, escalated_tier, content)
                except Exception as second_error:
                    _emit(event_queue, DAGEvent(
                        kind="subagent_error", task_id=task.id, persona=task.persona,
                        text=f"{type(second_error).__name__}: {second_error}",
                    ))
                    final_text = f"(task failed after retry: {second_error})"
                    tool_names = []

        _emit(event_queue, DAGEvent(kind="subagent_finished", task_id=task.id, persona=task.persona, text=final_text))
        return {"results": {task.id: final_text}, "tool_calls": {task.id: tool_names}}

    return node


def _build_graph(
    tasks: list[TaskSpec], semaphore: asyncio.Semaphore, saver, scratch_dir: Path,
    event_queue: asyncio.Queue[DAGEvent] | None = None,
):
    builder = StateGraph(OrchestratorState)
    for task in tasks:
        builder.add_node(task.id, _make_node(task, semaphore, event_queue, scratch_dir))

    has_dependents = {dep for task in tasks for dep in task.depends_on}
    for task in tasks:
        if task.depends_on:
            for dep in task.depends_on:
                builder.add_edge(dep, task.id)
        else:
            builder.add_edge(START, task.id)
        if task.id not in has_dependents:
            builder.add_edge(task.id, END)

    return builder.compile(checkpointer=saver)


def _write_run_log(
    run_id: str, prompt: str, tasks: list[TaskSpec], results: dict[str, str],
    tool_calls: dict[str, list[str]], answer: str,
) -> None:
    """Every completed orchestrated run as a dated note under
    `<VAULT_PATH>/hi/conversations/runs/` — DAG shape, which subagent
    did what, real tool calls made — so "the filesystem is the single
    source of truth" stays true for multi-agent runs too, not just
    single-turn ones."""
    _runs_dir().mkdir(parents=True, exist_ok=True)
    lines = [f"# Orchestrated run — {run_id}", "", f"**Request:** {prompt}", "", "## Tasks"]
    for t in tasks:
        deps = ", ".join(t.depends_on) if t.depends_on else "(none — ran independently)"
        calls = ", ".join(tool_calls.get(t.id, [])) or "(none)"
        label = f"{t.id} — {t.persona}/{t.tier}" + (f" ({t.archetype})" if t.archetype else "")
        lines.append(f"\n### {label}")
        lines.append(f"- Description: {t.description}")
        lines.append(f"- Depends on: {deps}")
        lines.append(f"- Tools called: {calls}")
        lines.append(f"- Result: {results.get(t.id, '(no result)')}")
    lines.append("\n## Final answer\n")
    lines.append(answer)
    content = "\n".join(lines)

    path = _runs_dir() / f"{run_id}.md"
    path.write_text(with_frontmatter(content, ["hi", "orchestrated-run"]))


def latest_run_trace() -> str | None:
    """TODO.md Phase 19's `trace` tool: the most recent orchestrated
    run's own log note (run ids are timestamp-prefixed, so sorting by
    filename is already sorting by recency — no need to stat() every
    file). None if no orchestrated run has ever completed."""
    if not _runs_dir().is_dir():
        return None
    runs = sorted(_runs_dir().glob("*.md"))
    if not runs:
        return None
    return runs[-1].read_text()


async def run_orchestrated(
    prompt: str,
    event_queue: asyncio.Queue[DAGEvent] | None = None,
) -> tuple[str, list[TaskSpec], dict[str, str]] | None:
    """Plans and runs a DAG for `prompt`. Returns (final_answer, tasks,
    results), or None if `planner.plan_tasks()` decided this request
    doesn't actually need decomposition (or failed to plan one) — the
    caller (hi/repl.py) falls back to the normal single-persona path in
    that case, same as a Phase 14 `decompose()` miss used to.

    `event_queue` (TODO.md Phases 18/19), if given, receives a
    `DAGEvent` for every subagent's start/retry/finish/error as it
    happens — the caller is responsible for draining it concurrently
    (e.g. via its own background task) if it wants live progress rather
    than just the final return value; nothing is pushed if omitted, and
    nothing here waits on it being drained.
    """
    tasks = plan_tasks(prompt)
    if not tasks:
        return None

    run_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_MODEL_CALLS)

    scratch_dir = SCRATCH_ROOT / run_id
    scratch_dir.mkdir(parents=True, exist_ok=True)
    try:
        async with checkpointer() as saver:
            graph = _build_graph(tasks, semaphore, saver, scratch_dir, event_queue)
            final_state = await graph.ainvoke(
                {"results": {}, "tool_calls": {}},
                config={"configurable": {"thread_id": run_id}},
            )
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    results = final_state.get("results", {})
    tool_calls = final_state.get("tool_calls", {})
    answer = aggregator.synthesize(prompt, tasks, results)
    _write_run_log(run_id, prompt, tasks, results, tool_calls, answer)
    return answer, tasks, results
