"""Generic interactive loop shared by all `hi` personas."""

from hi.personas import get_persona

EXIT_WORDS = {"exit", "quit"}


def run_repl(persona_name: str) -> None:
    persona = get_persona(persona_name)
    prompt = f"({persona_name}) > "

    while True:
        try:
            query = input(prompt)
        except EOFError:
            break

        stripped = query.strip()
        if stripped.lower() in EXIT_WORDS:
            break
        if not stripped:
            continue

        result = persona.agent.invoke({"messages": [{"role": "user", "content": stripped}]})
        response = result["messages"][-1].content
        print(response)

        if persona.on_turn:
            persona.on_turn(stripped, response)
