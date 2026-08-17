"""Generic interactive loop shared by all `hi` personas."""

import readline

from hi.personas import get_persona

EXIT_WORDS = {"exit", "quit"}
CLEAR_WORDS = {"clear", "cls"}

CLEAR_SCREEN = "\033[H\033[2J"


def _bind_clear_screen_key() -> None:
    """Best-effort: bind Ctrl-L to clear the screen during input(). macOS's
    stdlib `readline` module is actually libedit, which needs its own
    editrc-style bind syntax rather than GNU readline's inputrc syntax."""
    try:
        if "libedit" in (readline.__doc__ or ""):
            readline.parse_and_bind("bind ^L ed-clear-screen")
        else:
            readline.parse_and_bind(r'"\C-l": clear-screen')
    except Exception:
        pass


def run_repl(persona_name: str) -> None:
    persona = get_persona(persona_name)
    _bind_clear_screen_key()
    prompt = f"({persona_name}) > "

    if persona.greeting:
        print(persona.greeting)

    while True:
        try:
            query = input(prompt)
        except EOFError:
            break

        stripped = query.strip()
        if stripped.lower() in EXIT_WORDS:
            break
        if stripped.lower() in CLEAR_WORDS:
            print(CLEAR_SCREEN, end="", flush=True)
            continue
        if not stripped:
            continue

        result = persona.agent.invoke({"messages": [{"role": "user", "content": stripped}]})
        response = result["messages"][-1].content
        print(response)

        if persona.on_turn:
            persona.on_turn(stripped, response)
