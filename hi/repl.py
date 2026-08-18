"""Generic interactive loop shared by all `hi` personas."""

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings

from hi.models import get_tier_model
from hi.personas import get_agent_builder, get_persona
from hi.router import classify
from hi.streaming import stream_and_print
from hi.vault import log_conversation

EXIT_WORDS = {"exit", "quit"}
CLEAR_WORDS = {"clear", "cls"}


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
    session: PromptSession = PromptSession(key_bindings=_build_key_bindings())
    agent_cache: dict[tuple[str, str], object] = {}
    prompt_label = "hi"

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

        persona_name, tier = classify(stripped)
        key = (persona_name, tier)
        if key not in agent_cache:
            agent_cache[key] = get_agent_builder(persona_name)(get_tier_model(tier))
        agent = agent_cache[key]

        final_messages = stream_and_print(agent, [{"role": "user", "content": stripped}])
        response = final_messages[-1].content

        log_conversation(persona_name, stripped, response)
        prompt_label = persona_name
