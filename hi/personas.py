"""Registry mapping persona names to their agent and per-turn behavior."""

from dataclasses import dataclass
from typing import Callable, Optional

PERSONAS = ("code", "butler", "docs", "web")


@dataclass(frozen=True)
class Persona:
    name: str
    agent: object
    on_turn: Optional[Callable[[str, str], None]] = None


def get_persona(name: str) -> Persona:
    """Build the requested persona, importing lazily so unrelated personas'
    dependencies (and model clients) aren't loaded."""
    if name == "code":
        from hi.agents.code.graph import agent
        from hi.agents.code.tools import log_conversation

        return Persona(name="code", agent=agent, on_turn=log_conversation)
    if name == "butler":
        from hi.agents.butler.butler import agent

        return Persona(name="butler", agent=agent)
    if name == "docs":
        from hi.agents.docs.docs import agent

        return Persona(name="docs", agent=agent)
    if name == "web":
        from hi.agents.web.web import agent

        return Persona(name="web", agent=agent)
    raise ValueError(f"Unknown persona: {name}")
