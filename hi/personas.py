"""Registry mapping persona names to their agent and per-turn behavior."""

from dataclasses import dataclass
from functools import partial
from typing import Callable, Optional

from hi.model_warmup import warm_up
from hi.vault import log_conversation

PERSONAS = ("code", "butler", "docs", "web")


@dataclass(frozen=True)
class Persona:
    name: str
    agent: object
    on_turn: Optional[Callable[[str, str], None]] = None


def get_persona(name: str) -> Persona:
    """Build the requested persona, importing lazily so unrelated personas'
    dependencies (and model clients) aren't loaded."""
    on_turn = partial(log_conversation, name)
    if name == "code":
        from hi.agents.code.graph import agent, model
    elif name == "butler":
        from hi.agents.butler.butler import agent, model
    elif name == "docs":
        from hi.agents.docs.docs import agent, model
    elif name == "web":
        from hi.agents.web.web import agent, model
    else:
        raise ValueError(f"Unknown persona: {name}")

    warm_up(model)
    return Persona(name=name, agent=agent, on_turn=on_turn)
