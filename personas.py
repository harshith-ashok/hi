"""Registry mapping persona names to their agent and per-turn behavior."""

from dataclasses import dataclass
from typing import Callable, Optional

PERSONAS = ("alfred", "jarvis", "vivilio")


@dataclass(frozen=True)
class Persona:
    name: str
    agent: object
    on_turn: Optional[Callable[[str, str], None]] = None


def get_persona(name: str) -> Persona:
    """Build the requested persona, importing lazily so unrelated personas'
    dependencies (and model clients) aren't loaded."""
    if name == "jarvis":
        from graph import agent
        from tools import log_conversation

        return Persona(name="jarvis", agent=agent, on_turn=log_conversation)
    if name == "alfred":
        from alfred import agent

        return Persona(name="alfred", agent=agent)
    if name == "vivilio":
        from vivilio import agent

        return Persona(name="vivilio", agent=agent)
    raise ValueError(f"Unknown persona: {name}")
