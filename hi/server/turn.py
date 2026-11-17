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
from hi.memory import records, reflection as reflection_agent, transcript
from hi.orchestrator.complexity import classify_or_default
from hi.personas import PERSONAS, get_agent_builder
from hi.router import collapse, fast_route, remember_route
from hi.server.spoken_summary import make_spoken_summary
from hi.speaker import Speaker

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


def _get_agent(persona_name: str, tier: str, isolated: bool = False):
    """The cached agent for (persona, tier). `isolated` gives background runs their own: term remembers the
    conversation, and a background run must neither read your chat nor reset it."""
    model = get_tier_model(tier)
    key = (persona_name, tier, llm.model_name(model), llm.signature(), isolated)
    with _cache_lock:
        if key not in _agent_cache:
            _agent_cache[key] = get_agent_builder(persona_name)(model)
        return _agent_cache[key]


def _context_used(text: str) -> dict | None:
    """What memory the agent is given for this message, so the UI can show it."""
    from hi.memory.context import find_notes

    lines = [l for l in memory.read_memory().splitlines() if l.lstrip().startswith("- ")]
    notes = [path for path, _ in find_notes(text, limit=5)]
    return {"memory": len(lines), "notes": notes} if lines or notes else None


def stream_query_as_agui(
    text: str, forced_persona: str | None = None, fresh: bool = False, context: str = "",
    origin: str = "ui", forced_tier: str | None = None,
):
    """Wraps `_stream_query_as_agui` so a failure while setting up the turn
    (unreachable Ollama, missing model) reaches the client
    as a RUN_ERROR event instead of a silently dropped connection."""
    try:
        yield from _stream_query_as_agui(text, forced_persona, fresh, context, origin, forced_tier)
    except Exception as e:
        records.record_turn(records.TurnRecord(
            forced_persona or "", "", text, error=llm.friendly_error(e), detail=repr(e), origin=origin,
        ))
        yield ag.RunErrorEvent(message=llm.friendly_error(e))


def _stream_query_as_agui(
    text: str, forced_persona: str | None = None, fresh: bool = False, context: str = "",
    origin: str = "ui", forced_tier: str | None = None,
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
    reflection_agent.maybe_reflect_yesterday()  # background, at most once a day
    if forced_persona in PERSONAS:
        persona_name, tier, needs_plan = forced_persona, _FORCED_PERSONA_TIER, False
    else:
        routed = fast_route(text)
        persona_name, tier, needs_plan = (*routed, False) if routed else classify_or_default(text)
        persona_name = collapse(persona_name)
    prof = profiles.profile(origin)
    if forced_tier in TIERS:  # a background run asked for a specific tier
        tier = forced_tier
    tier = profiles.cap_tier(tier, prof.max_tier)  # the island never needs the heaviest model
    if origin in BACKGROUND_ORIGINS:
        state = runpolicy.current()
        if state is not None:
            state.persona = persona_name  # so a proposal knows which agent's tools can run it
    else:
        remember_route(persona_name, tier)  # a background run must not steer the next chat message's route
    route_s = time.monotonic() - started

    yield ag.CustomEvent(name="persona_selected", value={"name": persona_name, "tier": tier, "plan": needs_plan})

    if used := _context_used(text):
        yield ag.CustomEvent(name="context_used", value=used)

    thread_id = uuid.uuid4().hex
    if needs_plan:
        events = stream_orchestrated_as_agui_sync(text + context + prof.style, thread_id)
        log_persona = "orchestrator"
    else:
        agent = _get_agent(persona_name, tier, isolated=origin in BACKGROUND_ORIGINS)
        if fresh and hasattr(agent, "reset"):
            agent.reset()  # a question about the screen right now must not be answered from an earlier one
        events = stream_agent_as_agui(agent, text + context + prof.style, thread_id, [] if fresh else transcript.history())
        log_persona = persona_name

    final_answer = ""
    run_error = ""
    speaker = Speaker()
    speaks = origin in ("ui", "voice")  # the island and background runs show text; they never read it aloud
    first_token_s: float | None = None
    tool_starts: dict[str, tuple[str, float]] = {}
    tool_times: list[dict] = []
    journal_tools: dict[str, dict] = {}  # call id -> {name, args, result}, for the journal
    for event in events:
        now = time.monotonic()
        if first_token_s is None and isinstance(event, ag.TextMessageContentEvent):
            first_token_s = now - started
        if speaks and isinstance(event, ag.TextMessageContentEvent) and not event.subagent_run_id:
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
        yield event
        for line in speaker.ready():
            yield ag.CustomEvent(name="spoken_chunk", value={"text": line})

    for line in speaker.finish():
        yield ag.CustomEvent(name="spoken_chunk", value={"text": line})

    yield ag.CustomEvent(
        name="timing",
        value={
            "route_s": round(route_s, 2),
            "first_token_s": round(first_token_s, 2) if first_token_s is not None else None,
            "total_s": round(time.monotonic() - started, 2),
            "tools": tool_times,
        },
    )

    records.record_turn(records.TurnRecord(
        log_persona, tier, text, final_answer, list(journal_tools.values()), time.monotonic() - started, needs_plan,
        error="" if final_answer else run_error, detail=run_error, origin=origin,
    ))
    if final_answer and speaks:
        if not speaker.has_spoken:  # nothing sayable streamed (tool-only answer, one-liner): summarize
            yield ag.CustomEvent(name="spoken_summary", value={"text": make_spoken_summary(final_answer)})


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
