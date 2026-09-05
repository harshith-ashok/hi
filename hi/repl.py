"""Generic interactive loop shared by all `hi` personas."""

import asyncio
import threading

from langchain_core.messages import HumanMessage
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings

from hi.capture.store import find_task
from hi.fast_commands import maybe_fast_reply
from hi.model_warmup import start_keepalive
from hi.models import get_tier_model, get_tier_model_fast
from hi.orchestrator.budget import get_budget, set_budget
from hi.orchestrator.complexity import classify_with_plan
from hi.orchestrator.graph import DAGEvent, run_orchestrated
from hi.orchestrator.pending_server import start_pending_server
from hi.personas import get_agent_builder, get_persona
from hi.streaming import stream_and_print
from hi.synthesis.arbiter import pick_next_task_for_session
from hi.synthesis.negotiation import find_arbiter_tool_result, looks_like_pushback
from hi.vault import log_conversation

EXIT_WORDS = {"exit", "quit"}
CLEAR_WORDS = {"clear", "cls"}
AFFIRMATIVE_WORDS = {"y", "yes", "yeah", "yep", "sure", "ok", "okay"}


def _build_key_bindings() -> KeyBindings:
    """Ctrl-L clears the screen; Ctrl-V records voice input and inserts the
    transcript for the user to review/edit — it does not submit it, so a
    misheard word can be fixed before Enter. Real key-binding callbacks
    (not just readline's fixed set of named functions) are exactly why
    this REPL uses prompt_toolkit instead of plain input() — Ctrl-V needs
    to run actual Python code (start recording) mid-line, which readline
    can't do."""
    bindings = KeyBindings()

    @bindings.add("c-l")
    def _clear(event) -> None:
        event.app.renderer.clear()

    @bindings.add("c-v")
    def _voice(event) -> None:
        from hi.voice import listen_and_transcribe

        buffer = event.current_buffer
        buffer.text = "listening..."
        buffer.cursor_position = len(buffer.text)
        event.app.invalidate()

        try:
            text = listen_and_transcribe()
        except Exception as e:
            buffer.text = ""
            event.app.invalidate()
            print(f"\nVoice input failed: {e}")
            return

        buffer.text = text
        buffer.cursor_position = len(buffer.text)
        event.app.invalidate()

    return bindings


def _print_dag_event(event: DAGEvent) -> None:
    """TODO.md Phase 19: a live status line while subagents run — even
    a plain [task: persona] milestone beats a silent wait. Tasks that
    genuinely run in parallel will interleave here, which is honest
    (they really are happening concurrently), not a bug."""
    if event.kind == "subagent_started":
        print(f"  [{event.task_id}: {event.persona}] starting…")
    elif event.kind == "subagent_retrying":
        print(f"  [{event.task_id}: {event.persona}] failed, retrying at a higher tier ({event.text})")
    elif event.kind == "subagent_error":
        print(f"  [{event.task_id}: {event.persona}] failed after retry ({event.text})")
    elif event.kind == "subagent_finished":
        print(f"  [{event.task_id}: {event.persona}] done")


async def _run_orchestrated_with_status(prompt: str):
    """Runs run_orchestrated() while concurrently draining its
    event_queue for live status prints (TODO.md Phase 19) — a plain
    asyncio.run(run_orchestrated(prompt)) would only show something
    once the ENTIRE DAG finishes, silent the whole time it's actually
    working."""
    queue: asyncio.Queue[DAGEvent] = asyncio.Queue()
    task = asyncio.create_task(run_orchestrated(prompt, event_queue=queue))

    while not task.done():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        _print_dag_event(event)

    while not queue.empty():
        _print_dag_event(queue.get_nowait())

    return await task


def _messages_this_turn(messages: list) -> list:
    """The suffix of `messages` starting at the most recent HumanMessage
    — i.e. just this turn's own exchange, not the whole (possibly
    multi-turn, possibly truncated) session history term's
    _StatefulAgent accumulates. TODO.md Phase 15's pushback detection
    needs exactly this scope: a what_next() call from three turns ago
    must never be mistaken for "the arbiter answered THIS turn"."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return messages[i:]
    return messages


def run_repl(persona_name: str) -> None:
    persona = get_persona(persona_name)
    session: PromptSession = PromptSession(key_bindings=_build_key_bindings())
    prompt = f"({persona_name}) > "

    if persona.greeting:
        print(persona.greeting)

    while True:
        try:
            query = session.prompt(prompt)
        except (EOFError, KeyboardInterrupt):
            break

        stripped = query.strip()
        if stripped.lower() in EXIT_WORDS:
            break
        if stripped.lower() in CLEAR_WORDS:
            print("\033[H\033[2J", end="", flush=True)
            continue
        if not stripped:
            continue

        final_messages = stream_and_print(persona.agent, [{"role": "user", "content": stripped}])
        response = final_messages[-1].content

        if persona.on_turn:
            persona.on_turn(stripped, response)


def run_router_repl() -> None:
    """Auto-routing mode (`hi`, no persona flag): each turn is classified
    into a (persona, tier) pair and handled by that persona, built on the
    tier's model instead of the persona's own fixed default. Agents are
    cached per (persona, tier) for the session, so e.g. term's cross-turn
    memory and every model's warm/keep_alive state survive across turns —
    only rebuilt the first time a given combination is actually used."""
    # TODO.md Phase 17: this process is the only place an orchestrated
    # run (Phase 16) can currently trigger a destructive-action
    # approval, so its own pending-actions HTTP server starts here —
    # see hi/orchestrator/pending_server.py's docstring for why this
    # is a separate server/port from the voice companion's.
    threading.Thread(target=start_pending_server, daemon=True).start()

    # Latency fix: classify_with_plan() runs before every single turn and
    # always uses the haiku tier — keeping it warm through idle gaps
    # between commands avoids silently paying model_warmup.py's own
    # documented double-round-trip "cold reload" tax on that call. See
    # start_keepalive()'s own docstring for why only haiku, not every tier.
    start_keepalive(get_tier_model_fast("haiku"))

    session: PromptSession = PromptSession(key_bindings=_build_key_bindings())
    agent_cache: dict[tuple[str, str], object] = {}
    prompt_label = "hi"
    # TODO.md Phase 15: which task the arbiter (what_next/what_next_smart)
    # most recently recommended this session, and what's already been
    # turned down — None/empty unless the previous turn was genuinely an
    # arbiter answer, so an unrelated later "no" can't misfire.
    last_arbiter_task_id: str | None = None
    arbiter_rejects: set[str] = set()

    from hi.briefing import build_briefing

    briefing = build_briefing()
    suggested_action = None
    if briefing:
        context, suggestion, suggested_action = briefing
        print(f"{context}\n\n{suggestion}" if suggestion else context)

    while True:
        try:
            query = session.prompt(f"({prompt_label}) > ")
        except (EOFError, KeyboardInterrupt):
            break

        stripped = query.strip()
        if stripped.lower() in EXIT_WORDS:
            break
        if stripped.lower() in CLEAR_WORDS:
            print("\033[H\033[2J", end="", flush=True)
            continue
        if not stripped:
            continue

        # Latency fix (hi/fast_commands.py): a fixed set of common,
        # unambiguous requests — greetings, "show my tasks", "mute",
        # "quit Safari", etc. — skip BOTH classify_with_plan()'s call and
        # a full persona agent's own generation call, calling the real
        # tool directly. See that module's docstring for exactly what's
        # covered and, just as importantly, what's deliberately excluded.
        fast_reply = maybe_fast_reply(stripped)
        if fast_reply is not None:
            fast_persona, fast_response = fast_reply
            print(fast_response)
            log_conversation(fast_persona, stripped, fast_response)
            prompt_label = fast_persona
            continue

        # TODO.md Phase 20: a user-settable quick/thorough budget for
        # orchestrated (multi-subagent) runs — "budget" alone shows the
        # current value, "budget quick"/"budget thorough" sets it. Not
        # routed through classify()/term's ReAct loop at all, same as
        # exit/clear above — this is a REPL-level setting, not something
        # for a model to interpret.
        if stripped.lower() == "budget":
            print(f"Current orchestration budget: {get_budget()} (quick | thorough)")
            continue
        if stripped.lower().startswith("budget "):
            value = stripped.split(None, 1)[1].strip()
            if set_budget(value):
                print(f"Orchestration budget set to '{get_budget()}'.")
            else:
                print(f"Unknown budget '{value}' — expected 'quick' or 'thorough'.")
            continue

        # If the briefing showed a suggestion and this is a bare
        # affirmative, run the suggested action instead of trying to
        # classify/route the literal word "yes" on its own.
        if suggested_action and stripped.lower() in AFFIRMATIVE_WORDS:
            stripped = suggested_action
        suggested_action = None

        # Multi-turn arbiter negotiation (TODO.md Phase 15): only checked
        # when the PREVIOUS turn was itself an arbiter recommendation, so
        # a "no" three turns later about something unrelated can't
        # misfire. Re-runs the same real deterministic scoring pass
        # (arbiter.py's pick_next_task_for_session()) with the rejected
        # task excluded, instead of routing through classification/term's
        # ReAct loop again for what's really just "try again, minus one".
        if last_arbiter_task_id and looks_like_pushback(stripped):
            arbiter_rejects.add(last_arbiter_task_id)
            picked = pick_next_task_for_session(frozenset(arbiter_rejects))
            if picked is None:
                response = "No other pending task to recommend — everything else was already ruled out this session."
                last_arbiter_task_id = None
            else:
                task, rationale = picked
                response = f"{task.text}\n({rationale})"
                last_arbiter_task_id = task.id
            print(response)
            log_conversation("term", stripped, response)
            prompt_label = "term"
            continue
        last_arbiter_task_id = None
        arbiter_rejects = set()

        # Orchestrated multi-subagent DAG (TODO.md Phase 16), superseding
        # Phase 14's separate regex-heuristic-then-opus-call planner:
        # classify_with_plan() is the SAME haiku-tier classification
        # call every turn already makes, now also returning whether this
        # genuinely needs decomposing — one model call either way, not
        # two competing "does this need a plan" checks. A wrongly-set
        # needs_plan still self-corrects: run_orchestrated() itself
        # falls back to None if its own (separate, opus-tier) planner
        # decides there's nothing to decompose, and the persona/tier
        # already known from THIS SAME classify call is reused for the
        # normal single-persona path below — no second classification.
        persona_name, tier, needs_plan = classify_with_plan(stripped)

        if needs_plan:
            print("\nThis looks like a multi-step request — planning a task DAG...")
            orchestrated = asyncio.run(_run_orchestrated_with_status(stripped))
            if orchestrated:
                response, tasks, _results = orchestrated
                print(response)
                print(f"\n(ran {len(tasks)} tasks — see hi/conversations/runs/ for the full trace)")
                log_conversation("orchestrator", stripped, response)
                prompt_label = "orchestrator"
                continue
            # run_orchestrated() itself decided this wasn't really a
            # multi-step request after all — fall through to the normal
            # single-persona path below using the persona/tier already
            # picked above, same as if needs_plan had been False.

        key = (persona_name, tier)
        if key not in agent_cache:
            # Latency fix: "haiku" is this project's own designated
            # "trivial/simple requests needing minimal reasoning" tier
            # (router.py's TIER_DESCRIPTIONS) — a simple butler command
            # or a repeated/simple lookup routinely lands here. Using
            # get_tier_model_fast() (reasoning off) for the ANSWER, not
            # just classify_with_plan()'s own haiku call, closes the gap
            # where a request already correctly classified as "quick"
            # still paid a "thinking" tax on the response that generates
            # it. Sonnet/opus keep full reasoning — those tiers are
            # exactly where a user might want to see the real chain of
            # thought on a genuinely hard question.
            model = get_tier_model_fast(tier) if tier == "haiku" else get_tier_model(tier)
            agent_cache[key] = get_agent_builder(persona_name)(model)
        agent = agent_cache[key]

        final_messages = stream_and_print(agent, [{"role": "user", "content": stripped}])
        response = final_messages[-1].content

        # TODO.md Phase 15: did this turn's answer come from the
        # arbiter? Detected from the real ReAct message history (this
        # turn's own slice only — see _messages_this_turn), not by
        # term's tools separately notifying anything. Sets up the
        # pushback check above to fire on the NEXT turn if it's a "no".
        arbiter_result = find_arbiter_tool_result(_messages_this_turn(final_messages))
        if arbiter_result:
            task_text = arbiter_result.split("\n", 1)[0].strip()
            matched = find_task(task_text, pending_only=True)
            last_arbiter_task_id = matched.id if matched else None
            arbiter_rejects = set()

        log_conversation(persona_name, stripped, response)
        prompt_label = persona_name
