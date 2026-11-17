"""Run one turn with nobody attached: what a schedule, the heartbeat and the drop folder call.

It uses the same pipeline as POST /query (hi/server/turn.py), so routing, tools, the journal and the transcript all
behave the same. What differs: it runs under a policy (hi/core/runpolicy.py) so risky tool calls become proposals,
it starts from a clean history so nothing leaks into your chat, it never speaks, and it stops at a deadline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ag_ui.core import events as ag

from hi.automation import profiles
from hi.core import runpolicy
from hi.core.runpolicy import RunPolicy
from hi.server import turn


@dataclass
class RunResult:
    answer: str = ""
    tools: list[dict] = field(default_factory=list)  # {name, args, result} in call order
    proposals: list[str] = field(default_factory=list)  # ids of proposals this run created
    error: str = ""
    timing: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def run_turn(
    text: str, *, origin: str, policy: RunPolicy, persona: str | None = None, tier: str | None = None,
    context: str = "", profile: str | None = None,
) -> RunResult:
    """Run `text` as a background turn and return what happened. Never raises: a failure is in `error`."""
    prof = profiles.profile(profile or origin)
    deadline = (time.monotonic() + (policy.timeout_s or prof.timeout_s)) if (policy.timeout_s or prof.timeout_s) else None
    result = RunResult()
    calls: dict[str, dict] = {}
    with runpolicy.run_scope(policy, origin) as state:
        events = turn.stream_query_as_agui(
            text, forced_persona=persona, fresh=True, context=context, origin=origin, forced_tier=tier or prof.tier,
        )
        try:
            for event in events:
                if isinstance(event, ag.ToolCallStartEvent):
                    calls[event.tool_call_id] = {"name": event.tool_call_name, "args": "", "result": ""}
                elif isinstance(event, ag.ToolCallArgsEvent) and event.tool_call_id in calls:
                    calls[event.tool_call_id]["args"] += event.delta
                elif isinstance(event, ag.ToolCallResultEvent) and event.tool_call_id in calls:
                    calls[event.tool_call_id]["result"] = str(event.content)
                elif isinstance(event, ag.RunFinishedEvent) and isinstance(event.result, str):
                    result.answer = event.result
                elif isinstance(event, ag.RunErrorEvent):
                    result.error = event.message
                elif isinstance(event, ag.CustomEvent) and event.name == "timing":
                    result.timing = dict(event.value)
                if deadline is not None and time.monotonic() > deadline:
                    result.error = f"timed out after {policy.timeout_s or prof.timeout_s:.0f}s"
                    break
        finally:
            events.close()
        result.tools = list(calls.values())
        result.proposals = list(state.proposals)
        result.notes = list(state.notes)
    if result.answer and result.error.startswith("timed out"):
        result.answer = ""  # a half-written answer from a run that did not finish is not a result
    return result
