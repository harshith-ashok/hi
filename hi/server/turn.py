"""One query, end to end: route it (butler or term, and a tier), run the agent or an orchestrated
plan, and yield AG-UI events for the client, writing the finished turn to every log.

`stream_query_as_agui` is the entry point, used by POST /query (hi/server/routes/query.py).
"""

from __future__ import annotations

import threading
import time
import uuid

from ag_ui.core import events as ag

import hi.config as config
from hi import llm
from hi.automation import profiles
from hi.agui_adapter import stream_agent_as_agui, stream_orchestrated_as_agui_sync
from hi.core import runpolicy
from hi.core.runpolicy import BACKGROUND_ORIGINS
from hi.llm.registry import TIERS, get_tier_model, get_tier_model_fast
from hi.memory import extraction as memory
from hi.memory import artifacts, records, reflection as reflection_agent, sessions, summary, transcript
from hi.memory.skills import expand_slash
from hi.orchestrator.complexity import classify_or_default
from hi.personas import PERSONAS, get_agent_builder
from hi.router import collapse, fast_route, remember_route
from hi.server.spoken_summary import make_spoken_summary
from hi.speaker import Speaker
from hi.ui_spec import WAIT_MARKER
from hi.visuals import make_visual

# Tier used when the client forces a specific persona (the panel's tab
# row) instead of letting classify_with_plan() pick one — "typical,
# moderately complex requests, the default for most things"
# (hi/router.py's own TIER_DESCRIPTIONS), a reasonable default absent
# any other signal to pick from, same as classify_with_plan() itself
# falls back to on a parse miss. Forcing a persona also always means
# no orchestrated plan — asking for a specific persona is explicitly
# asking NOT to have the request decomposed across several.
_FORCED_PERSONA_TIER = "sonnet"

# Cached per (persona, tier, model_name), same as hi/repl.py's
# run_router_repl() — so cross-turn memory (term's own statefulness) and
# warm/keep_alive model state survive across voice queries in this
# process too. model_name is part of the key, not just (persona, tier),
# specifically so a `POST /config` change to e.g. SONNET_MODEL (Settings
# screen) builds a fresh agent on the very next call instead of quietly
# returning one already built against the tier's *old* model — found
# live while wiring up config hot-reload (hi/models.py's tier_models()
# already re-resolves per call; this cache would have silently
# undermined that one level up if left keyed on tier alone).
_agent_cache: dict[tuple, object] = {}
_cache_lock = threading.Lock()


MAX_CACHED_AGENTS = 16  # one per (persona, tier, session) in use; the least recently used is dropped


ARTIFACT_SHARE = 0.6  # at most this much of what is left of the context window goes to the chat's artifacts


def _get_agent(persona_name: str, tier: str, isolated: bool = False, session: str = ""):
    """The cached agent for (persona, tier, session). term remembers its conversation, so each chat session gets its
    own, and `isolated` gives background runs theirs: a background run must neither read your chat nor reset it."""
    model = get_tier_model(tier)
    key = (persona_name, tier, llm.model_name(model), llm.signature(), isolated, session)
    with _cache_lock:
        if key in _agent_cache:
            _agent_cache[key] = _agent_cache.pop(key)  # most recently used goes last
        else:
            _agent_cache[key] = get_agent_builder(persona_name)(model)
            while len(_agent_cache) > MAX_CACHED_AGENTS:
                _agent_cache.pop(next(iter(_agent_cache)))
        return _agent_cache[key]


def _context_used(text: str) -> dict | None:
    """What memory the agent is given for this message, so the UI can show it."""
    from hi.memory.context import find_notes

    lines = [l for l in memory.read_memory().splitlines() if l.lstrip().startswith("- ")]
    notes = [path for path, _ in find_notes(text, limit=5)]
    return {"memory": len(lines), "notes": notes} if lines or notes else None


def stream_query_as_agui(
    text: str, forced_persona: str | None = None, fresh: bool = False, context: str = "",
    origin: str = "ui", forced_tier: str | None = None, session: str = "", visualize: bool = False,
    parent: str | None = None,
):
    """Wraps `_stream_query_as_agui` so a failure while setting up the turn
    (unreachable Ollama, missing model) reaches the client
    as a RUN_ERROR event instead of a silently dropped connection."""
    try:
        yield from _stream_query_as_agui(text, forced_persona, fresh, context, origin, forced_tier, session, visualize, parent)
    except Exception as e:
        records.record_turn(records.TurnRecord(
            forced_persona or "", "", text, error=llm.friendly_error(e), detail=repr(e), origin=origin, session=session,
            parent=parent,
        ))
        yield ag.RunErrorEvent(message=llm.friendly_error(e))


def _stream_query_as_agui(
    text: str, forced_persona: str | None = None, fresh: bool = False, context: str = "",
    origin: str = "ui", forced_tier: str | None = None, session: str = "", visualize: bool = False,
    parent: str | None = None,
):
    """Yields AG-UI events for one query — a `persona_selected` CUSTOM
    event first (this project's own extension; AG-UI has no built-in
    field for "which persona/tier answered"), then either
    `stream_agent_as_agui()`'s or (TODO.md Phase 16 orchestrated case)
    `stream_orchestrated_as_agui_sync()`'s real events, then a
    `spoken_summary` CUSTOM event once the real final answer is known
    (the same TTS condensation `hi/server/spoken_summary.py` already did
    for the old protocol).

    `forced_persona` (the panel's persona-tab row) skips
    `classify_with_plan()` entirely when set to one of `PERSONAS` — the
    same "force a specific persona" behavior `hi --term`/`--butler`/etc.
    already give the terminal, reachable from the voice companion's UI
    too, and (see module docstring) never triggers an orchestrated plan.
    """
    started = time.monotonic()
    if slash := expand_slash(text):  # "/skill-name request": the skill's instructions ride along as context
        skill_name, _rest, instructions = slash
        context += f"\n\nThe user invoked the '{skill_name}' skill. Follow these instructions for their request:\n\n{instructions}"
        forced_persona = forced_persona or "term"
    reflection_agent.maybe_reflect_yesterday()  # background, at most once a day
    if forced_persona in PERSONAS:
        persona_name, tier, needs_plan = forced_persona, _FORCED_PERSONA_TIER, False
    elif origin in BACKGROUND_ORIGINS:
        # No routing model call, and never a multi-agent plan: a background run is one agent under the run guard.
        persona_name, tier, needs_plan = "term", _FORCED_PERSONA_TIER, False
    else:
        routed = fast_route(text)
        persona_name, tier, needs_plan = (*routed, False) if routed else classify_or_default(text)
        persona_name = collapse(persona_name)
    prof = profiles.profile(origin)
    routed_tier = tier  # what the router chose, before the user's choice is applied
    if forced_tier in TIERS:  # the user (or a background run) asked for a specific tier
        tier = forced_tier
    tier = profiles.cap_tier(tier, prof.max_tier)  # the island never needs the heaviest model
    if origin in BACKGROUND_ORIGINS:
        state = runpolicy.current()
        if state is not None:
            state.persona = persona_name  # so a proposal knows which agent's tools can run it
    else:
        remember_route(persona_name, routed_tier)  # the router's pick, not a tier you forced: Auto must stay auto
        # (a background run must not steer the next chat message's route either)
    route_s = time.monotonic() - started

    yield ag.CustomEvent(name="persona_selected", value={"name": persona_name, "tier": tier, "plan": needs_plan})

    if used := _context_used(text):
        yield ag.CustomEvent(name="context_used", value=used)

    thread_id = uuid.uuid4().hex
    turn_id = uuid.uuid4().hex[:12]
    head = sessions.head_of(session) if session else ""
    branched = parent is not None and parent != head  # an edit or "ask again": not a continuation of the latest turn
    if parent is None:
        parent = head  # the turn this one follows in its chat
    dropped = 0  # earlier turns of the chat that did not fit the context window
    if needs_plan:
        events = stream_orchestrated_as_agui_sync(text + context + prof.style, thread_id)
        log_persona = "orchestrator"
    else:
        agent = _get_agent(persona_name, tier, isolated=origin in BACKGROUND_ORIGINS, session=session)
        if fresh and hasattr(agent, "reset"):
            agent.reset()  # a question about the screen right now must not be answered from an earlier one
        if session and not fresh:
            on_branch = set() if branched and not parent else {e["id"] for e in transcript.session_path(session, parent)}
            share = int(max(transcript.history_budget(text + context + prof.style), 0) * ARTIFACT_SHARE)
            if block := artifacts.context_block(session, share, on_branch):
                context += "\n\n" + block
        message = text + context + prof.style
        if branched and hasattr(agent, "reset"):
            agent.reset()  # its memory holds the other branch; the transcript has the right one
        if fresh or (branched and not parent):
            earlier: list[dict] = []
        elif session:
            saved = (sessions.get(session) or sessions.Session(session)).summary
            budget = transcript.history_budget(message) - (transcript.estimate_tokens(saved) + 40 if saved else 0)
            earlier, dropped = transcript.history_within(budget, session, parent)
            if dropped and saved:
                earlier = summary.messages(saved) + earlier
            used = transcript.PROMPT_OVERHEAD_TOKENS + transcript.estimate_tokens(message) + sum(transcript.estimate_tokens(m["content"]) for m in earlier)
            yield ag.CustomEvent(name="context_window", value={"used": used, "limit": config.CONTEXT_TOKENS, "dropped_turns": dropped})
        else:
            earlier = transcript.history()
        events = stream_agent_as_agui(agent, message, thread_id, earlier)
        log_persona = persona_name

    final_answer = ""
    run_error = ""
    speaker = Speaker()
    speaks = origin in ("ui", "voice")  # the island and background runs show text; they never read it aloud
    first_token_s: float | None = None
    tool_starts: dict[str, tuple[str, float]] = {}
    tool_times: list[dict] = []
    journal_tools: dict[str, dict] = {}  # call id -> {name, args, result}, for the journal
    streamed: list[str] = []  # the answer so far, in case the client stops the reply
    run_ids: tuple[str, str] | None = None
    try:
        for event in events:
            now = time.monotonic()
            if first_token_s is None and isinstance(event, ag.TextMessageContentEvent):
                first_token_s = now - started
            if isinstance(event, ag.TextMessageContentEvent) and not event.subagent_run_id:
                streamed.append(event.delta)
                if speaks:
                    speaker.feed(event.delta)
            if isinstance(event, ag.ToolCallStartEvent):
                journal_tools[event.tool_call_id] = {"name": event.tool_call_name, "args": "", "result": ""}
            elif isinstance(event, ag.ToolCallArgsEvent) and event.tool_call_id in journal_tools:
                journal_tools[event.tool_call_id]["args"] += event.delta
            elif isinstance(event, ag.ToolCallResultEvent) and event.tool_call_id in journal_tools:
                journal_tools[event.tool_call_id]["result"] = str(event.content)
            if isinstance(event, ag.ToolCallStartEvent):
                speaker.block_ended_by_tool()
                tool_starts[event.tool_call_id] = (event.tool_call_name, now)
            elif isinstance(event, ag.ToolCallResultEvent) and event.tool_call_id in tool_starts:
                name, began = tool_starts.pop(event.tool_call_id)
                tool_times.append({"name": name, "s": round(now - began, 2)})
            if isinstance(event, ag.RunFinishedEvent) and isinstance(event.result, str):
                final_answer = event.result
            elif isinstance(event, ag.RunErrorEvent):
                run_error = event.message
            if isinstance(event, ag.RunStartedEvent):
                run_ids = (event.thread_id, event.run_id)
            yield event
            for line in speaker.ready():
                yield ag.CustomEvent(name="spoken_chunk", value={"text": line})
            if isinstance(event, ag.ToolCallResultEvent) and WAIT_MARKER in str(event.content) and run_ids:
                # A form or question is on screen and the assistant has nothing to add until the user answers: end the
                # turn here rather than spend a model call on an empty reply (and leave the user a window to answer
                # while it is still "running").
                events.close()
                yield ag.RunFinishedEvent(thread_id=run_ids[0], run_id=run_ids[1], result="")
                break

    except GeneratorExit:
        # The client pressed Stop (or went away). Keep what was said: a stopped turn stays in its chat session.
        records.record_turn(records.TurnRecord(
            log_persona, tier, text, "".join(streamed), list(journal_tools.values()), time.monotonic() - started,
            needs_plan, error=records.STOPPED, origin=origin, session=session, id=turn_id, parent=parent,
        ))
        raise

    for line in speaker.finish():
        yield ag.CustomEvent(name="spoken_chunk", value={"text": line})

    visual = ""
    if visualize and final_answer and origin in ("ui", "voice") and "```mermaid" not in final_answer:
        # Forced visualization: draw the answer after it has streamed (unless the answer already has a diagram of its
        # own). The chat shows "drawing" until this arrives.
        yield ag.CustomEvent(name="phase", value={"name": "visualizing", "state": "start"})
        visual = make_visual(text, final_answer) or ""
        yield ag.CustomEvent(name="visual", value={"mermaid": visual})
        yield ag.CustomEvent(name="phase", value={"name": "visualizing", "state": "end"})

    _record_usage(origin, tier, len(tool_times), time.monotonic() - started, first_token_s)
    yield ag.CustomEvent(
        name="timing",
        value={
            "route_s": round(route_s, 2),
            "first_token_s": round(first_token_s, 2) if first_token_s is not None else None,
            "total_s": round(time.monotonic() - started, 2),
            "tools": tool_times,
        },
    )

    record = records.TurnRecord(
        log_persona, tier, text, final_answer, list(journal_tools.values()), time.monotonic() - started, needs_plan,
        error="" if final_answer else run_error, detail=run_error, origin=origin, session=session, visual=visual,
        id=turn_id, parent=parent,
    )
    records.record_turn(record)
    yield ag.CustomEvent(name="turn", value={"id": turn_id, "parent": parent})
    for saved in record.artifacts:
        yield ag.CustomEvent(name="artifact", value=saved)
    if dropped and origin not in BACKGROUND_ORIGINS:
        summary.summarise_async(session, parent, dropped)  # for the next turn: what fell out of the window
    if final_answer and speaks:
        if not speaker.has_spoken:  # nothing sayable streamed (tool-only answer, one-liner): summarize
            yield ag.CustomEvent(name="spoken_summary", value={"text": make_spoken_summary(final_answer)})


def _record_usage(origin: str, tier: str, tool_calls: int, seconds: float, first_token_s: float | None) -> None:
    """One line per turn in ~/.hi/state/usage.jsonl: how the limits count background runs, and per-origin latency."""
    from hi.automation import limits
    from hi.llm.registry import is_local

    try:
        limits.record(origin, tier, not is_local(tier), tool_calls, seconds, round(first_token_s, 2) if first_token_s is not None else None)
    except (OSError, KeyError, ValueError):
        pass  # a usage record is never a reason to fail a turn


def _warm_up() -> None:
    """Pay the one-time costs at startup, not on the user's first question: load the always-resident model
    on the model server, and build the agents (MCP connections, tool lists, prompts) that turns will use.
    Best-effort, in the background; the server answers requests meanwhile."""
    from hi import config
    from hi.llm.resilience import preload_models

    try:
        if config.AI_MODE == "tailscale":
            preload_models([config.HAIKU_MODEL])
        for tier in ("sonnet",):
            for persona_name in ("term", "butler"):
                _get_agent(persona_name, tier)
        get_tier_model_fast("haiku").invoke("ok")  # the routing model, so the first classification is fast
    except Exception as e:
        print(f"warm-up skipped: {llm.friendly_error(e)}", flush=True)
