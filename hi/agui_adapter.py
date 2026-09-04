"""Translates `hi`'s own agent/orchestrator execution into AG-UI's
typed event stream (TODO.md Phase 18) — `ag_ui.core.events`, from the
real, installed `ag-ui-protocol` SDK, not a bespoke format. The actual
point (`BLOCKERS.md`'s own framing): a flat token stream can't express
"3 subagents are running in parallel" or "here's a tool's rendered
widget, not just its text result" — a typed event stream can, and any
AG-UI-aware client (including one this project didn't write) can
render a run without `hi` inventing its own wire format.

**Correction to `BLOCKERS.md`'s own naming, confirmed live before
writing this** (`ag_ui.core.events`'s real fields inspected directly,
not assumed from documentation): the real network-facing streaming
surface this belongs on is `hi/ipc/server.py`'s `POST /query` — not
`hi/streaming.py` (prints tokens to the *terminal's own stdout*, no
network client to speak AG-UI to) or a `hi/server.py` that doesn't
exist under that name.

Two entry points:

- `stream_agent_as_agui()`: a normal, single-persona turn — the exact
  case `hi/ipc/server.py`'s old `stream_events()` already drove,
  reshaped onto AG-UI's real event types (with real token-level
  `TEXT_MESSAGE_CONTENT` deltas and real `TOOL_CALL_*` events) instead
  of a bespoke `{event: persona/token/done}` dict.
- `stream_orchestrated_as_agui()`: a TODO.md Phase 16 orchestrated DAG
  run — `SUBAGENT_STARTED`/`SUBAGENT_FINISHED`/`SUBAGENT_ERROR` (real
  AG-UI event types, built for exactly this) frame each task's
  complete result. Deliberately milestone-level per subagent (started →
  finished with its whole answer), not token-by-token within each one
  — `hi/orchestrator/graph.py`'s own `DAGEvent` queue (shared with
  Phase 19's tmux status line) only carries that much granularity, and
  that's genuinely enough to satisfy the actual ask ("3 subagents are
  running" visibility), not a shortfall.

MCP-UI widget passthrough (the same phase's mcp_tools.py item): detected
here, not in `hi/mcp_tools.py` itself — a tool's rendered widget only
matters at the point something is about to stream a `TOOL_CALL_RESULT`
event for it, which is exactly where this module already inspects tool
messages. **Not verified against a real MCP-UI server** — none of this
project's configured servers (Playwright, GitHub, Obsidian) implement
the mcp-ui extension, so this is written defensively (checked against a
synthetic content block shaped like the mcp-ui spec) and documented as
such, not silently assumed correct end to end.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

from ag_ui.core import events as ag
from langchain_core.messages import AIMessageChunk, ToolMessage

from hi.orchestrator.graph import DAGEvent, run_orchestrated


def _mcp_ui_widget(content: Any) -> dict | None:
    """Returns `{"mimeType": ..., "uri": ..., "text": ...}` if `content`
    looks like an mcp-ui resource block (a `dict` or list-of-`dict`
    with a `"resource"`/`"uri"` shape whose URI uses the `ui://` scheme
    the mcp-ui spec reserves for rendered widgets), else None. Accepts
    both a single content block and langchain_mcp_adapters' list-of-
    content-blocks form."""
    blocks = content if isinstance(content, list) else [content]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        resource = block.get("resource") if block.get("type") == "resource" else block
        if not isinstance(resource, dict):
            continue
        uri = resource.get("uri", "")
        if isinstance(uri, str) and uri.startswith("ui://"):
            return {
                "mimeType": resource.get("mimeType", "text/html"),
                "uri": uri,
                "text": resource.get("text", ""),
            }
    return None


def stream_agent_as_agui(agent, text: str, thread_id: str) -> Iterator[ag.BaseEvent]:
    """Wraps a single (non-orchestrated) persona agent's own real
    `.stream(...)` call — the same one `hi/ipc/server.py`'s old
    `stream_events()` already made — translating it into AG-UI events
    instead of a bespoke dict shape.

    Also surfaces `thinking` (a real AG-UI event type: `THINKING_START`/
    `THINKING_TEXT_MESSAGE_START/CONTENT/END`/`THINKING_END`), not just
    the final answer — the same reasoning content `hi/streaming.py`'s
    terminal-side `stream_and_print()` already prints dimmed, mirrored
    here with the identical open/close logic (`thinking_open`): a
    thinking block starts the first time `chunk.additional_kwargs
    ["reasoning_content"]` appears, and ends the moment real
    `chunk.content` starts arriving, since a reasoning model always
    "thinks" before its real answer, never interleaved with it.
    """
    run_id = uuid.uuid4().hex
    yield ag.RunStartedEvent(thread_id=thread_id, run_id=run_id)

    message_id: str | None = None
    thinking_open = False
    open_tool_calls: dict[str, str] = {}  # tool_call_id -> tool name, for TOOL_CALL_RESULT's benefit
    final_messages: list | None = None

    try:
        for _ns, mode, payload in agent.stream(
            {"messages": [{"role": "user", "content": text}]},
            stream_mode=["messages", "values"],
            subgraphs=True,
        ):
            if mode != "messages":
                final_messages = payload["messages"]
                continue
            chunk, _metadata = payload

            if isinstance(chunk, AIMessageChunk):
                thinking = chunk.additional_kwargs.get("reasoning_content")
                if thinking:
                    if not thinking_open:
                        yield ag.ThinkingStartEvent()
                        yield ag.ThinkingTextMessageStartEvent()
                        thinking_open = True
                    yield ag.ThinkingTextMessageContentEvent(delta=thinking)

                for call in chunk.tool_call_chunks or []:
                    call_id = call.get("id")
                    if not call_id:
                        continue
                    if call_id not in open_tool_calls:
                        open_tool_calls[call_id] = call.get("name") or ""
                        yield ag.ToolCallStartEvent(tool_call_id=call_id, tool_call_name=open_tool_calls[call_id])
                    if call.get("args"):
                        yield ag.ToolCallArgsEvent(tool_call_id=call_id, delta=call["args"])
                if chunk.content:
                    if thinking_open:
                        yield ag.ThinkingTextMessageEndEvent()
                        yield ag.ThinkingEndEvent()
                        thinking_open = False
                    if message_id is None:
                        message_id = uuid.uuid4().hex
                        yield ag.TextMessageStartEvent(message_id=message_id, role="assistant")
                    yield ag.TextMessageContentEvent(message_id=message_id, delta=chunk.content)

            elif isinstance(chunk, ToolMessage):
                if chunk.tool_call_id in open_tool_calls:
                    yield ag.ToolCallEndEvent(tool_call_id=chunk.tool_call_id)
                widget = _mcp_ui_widget(chunk.content)
                if widget is not None:
                    # TODO.md Phase 20 (widget recall): persisted here,
                    # not in whatever tool produced it — this is the one
                    # place every widget (MCP-sourced or, now,
                    # hi/widget_store.py's own recall_widget() re-serving
                    # a saved one) already passes through on its way to
                    # becoming a CUSTOM event. Deduped by uri, so a
                    # recalled widget re-saves over itself, not a
                    # growing pile of duplicates.
                    from hi.widget_store import save_widget

                    save_widget(widget["uri"], widget["mimeType"], widget["text"])
                    yield ag.CustomEvent(name="mcp_ui_widget", value={"tool_call_id": chunk.tool_call_id, **widget})
                yield ag.ToolCallResultEvent(
                    message_id=uuid.uuid4().hex,
                    tool_call_id=chunk.tool_call_id,
                    content=chunk.content if isinstance(chunk.content, str) else str(chunk.content),
                    role="tool",
                )
    except Exception as e:
        yield ag.RunErrorEvent(message=str(e))
        return

    # Defensive close, mirroring stream_and_print()'s own end-of-stream
    # cleanup: a response that's ALL reasoning with no real final content
    # (rare, but seen live during this project's own build) would
    # otherwise leave a thinking block open forever from the client's
    # point of view.
    if thinking_open:
        yield ag.ThinkingTextMessageEndEvent()
        yield ag.ThinkingEndEvent()

    if message_id is not None:
        yield ag.TextMessageEndEvent(message_id=message_id)

    response = final_messages[-1].content if final_messages else ""
    yield ag.RunFinishedEvent(thread_id=thread_id, run_id=run_id, result=response)


async def stream_orchestrated_as_agui(prompt: str, thread_id: str) -> AsyncIterator[ag.BaseEvent]:
    """Runs `hi/orchestrator/graph.py`'s `run_orchestrated()` DAG while
    concurrently draining its `DAGEvent` queue — the same live-progress
    mechanism Phase 19's tmux status line drains, here translated into
    `SUBAGENT_STARTED`/`FINISHED`/`ERROR` events instead of plain prints.
    A `SUBAGENT_STARTED` also gets a `TEXT_MESSAGE_START/CONTENT/END`
    triple carrying its whole answer once it finishes — not streamed
    token-by-token (see module docstring for why that's a deliberate
    scope, not a shortfall).

    Falls back to a `RunErrorEvent` (never a raw crash) if the planner
    itself decides not to decompose after all — that's a real, expected
    outcome (a `classify_with_plan()` false positive self-correcting),
    not a failure, so it's reported plainly rather than as an error.
    """
    run_id = uuid.uuid4().hex
    yield ag.RunStartedEvent(thread_id=thread_id, run_id=run_id)

    queue: asyncio.Queue[DAGEvent] = asyncio.Queue()
    task = asyncio.create_task(run_orchestrated(prompt, event_queue=queue))
    open_message_ids: dict[str, str] = {}  # task_id -> message_id, while a subagent is running
    # TODO.md Phase 20 ("approvals as generative UI"): action_id -> its
    # description, for every pending action this run has already told
    # the client about — lets _pending_action_events() tell "brand new"
    # from "already reported" and notice when a previously-reported one
    # has since been resolved. Scoped to THIS generator call, not global
    # state — this project's own "one thing at a time" usage model
    # (pending_actions.py's own docstring) means that's enough, same
    # assumption PendingActionsMonitor.swift's polling already makes.
    seen_pending: dict[str, str] = {}

    while not task.done():
        for ag_event in _pending_action_events(seen_pending):
            yield ag_event
        try:
            event = await asyncio.wait_for(queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        for ag_event in _dag_event_to_agui(event, open_message_ids):
            yield ag_event

    for ag_event in _pending_action_events(seen_pending):
        yield ag_event
    while not queue.empty():
        for ag_event in _dag_event_to_agui(queue.get_nowait(), open_message_ids):
            yield ag_event

    try:
        result = await task
    except Exception as e:
        yield ag.RunErrorEvent(message=str(e))
        return

    if result is None:
        yield ag.RunFinishedEvent(
            thread_id=thread_id, run_id=run_id,
            result="(this turned out not to need a multi-step plan after all)",
        )
        return

    answer, _tasks, _results = result
    yield ag.RunFinishedEvent(thread_id=thread_id, run_id=run_id, result=answer)


def _dag_event_to_agui(event: DAGEvent, open_message_ids: dict[str, str]) -> list[ag.BaseEvent]:
    if event.kind == "subagent_started":
        return [ag.SubagentStartedEvent(subagent_run_id=event.task_id, name=event.persona)]
    if event.kind == "subagent_retrying":
        return [ag.CustomEvent(name="subagent_retrying", value={"task_id": event.task_id, "reason": event.text},
                                subagent_run_id=event.task_id)]
    if event.kind == "subagent_error":
        return [ag.SubagentErrorEvent(subagent_run_id=event.task_id, message=event.text)]
    if event.kind == "subagent_finished":
        message_id = uuid.uuid4().hex
        return [
            ag.TextMessageStartEvent(message_id=message_id, role="assistant", subagent_run_id=event.task_id),
            ag.TextMessageContentEvent(message_id=message_id, delta=event.text, subagent_run_id=event.task_id),
            ag.TextMessageEndEvent(message_id=message_id, subagent_run_id=event.task_id),
            ag.SubagentFinishedEvent(subagent_run_id=event.task_id, result=event.text),
        ]
    return []


def _pending_action_events(seen_pending: dict[str, str]) -> list[ag.BaseEvent]:
    """TODO.md Phase 20 ("approvals as generative UI"): translates
    `hi/orchestrator/pending_actions.py`'s plain queue into CUSTOM
    events, so a destructive action an orchestrated subagent is waiting
    on can render as a real inline approve/deny card in the client
    (`voice_companion`'s `PendingActionCard.swift`) instead of only the
    menu-bar indicator `PendingActionsMonitor.swift` already polls for
    separately. Mutates `seen_pending` in place (add on first sight,
    remove once resolved) — the caller owns it across repeated calls
    within one `stream_orchestrated_as_agui()` run.
    """
    from hi.orchestrator.pending_actions import list_pending, resolution_of

    events: list[ag.BaseEvent] = []
    current = {a.id: a.description for a in list_pending()}

    for action_id, description in current.items():
        if action_id not in seen_pending:
            seen_pending[action_id] = description
            events.append(ag.CustomEvent(
                name="pending_action", value={"id": action_id, "description": description}
            ))

    for action_id in list(seen_pending):
        if action_id not in current:
            approved = resolution_of(action_id)
            events.append(ag.CustomEvent(
                name="pending_action_resolved", value={"id": action_id, "approved": bool(approved)}
            ))
            del seen_pending[action_id]

    return events


def stream_orchestrated_as_agui_sync(prompt: str, thread_id: str) -> Iterator[ag.BaseEvent]:
    """Sync-generator bridge for `stream_orchestrated_as_agui()`, for a
    caller with no event loop of its own — `hi/ipc/server.py`'s HTTP
    handler runs on a plain `ThreadingHTTPServer` worker thread, not
    inside asyncio. A fresh event loop scoped to this one call (each
    HTTP request already gets its own OS thread, so a fresh loop per
    call is the natural scope, not a shared one)."""
    loop = asyncio.new_event_loop()
    try:
        agen = stream_orchestrated_as_agui(prompt, thread_id)
        while True:
            try:
                yield loop.run_until_complete(agen.__anext__())
            except StopAsyncIteration:
                break
    finally:
        loop.close()
