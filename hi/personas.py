"""Registry mapping persona names to their agent and per-turn behavior."""

import threading
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
    greeting: Optional[str] = None


def get_persona(name: str) -> Persona:
    """Build the requested persona, importing lazily so unrelated personas'
    dependencies (and model clients) aren't loaded."""
    on_turn = partial(log_conversation, name)
    greeting = None
    if name == "code":
        from hi.agents.code.graph import agent, model
    elif name == "butler":
        from hi.agents.butler.butler import agent, model
        from hi.agents.butler.todo import pending_tasks_greeting

        greeting = pending_tasks_greeting()
    elif name == "docs":
        from hi.agents.docs.docs import agent, model
    elif name == "web":
        from hi.agents.web.web import agent, model
    else:
        raise ValueError(f"Unknown persona: {name}")

    # Warm the model up in the background rather than blocking here, so the
    # prompt appears and accepts input immediately instead of waiting on a
    # network round-trip before the user can even start typing.
    threading.Thread(target=warm_up, args=(model,), daemon=True).start()

    return Persona(name=name, agent=agent, on_turn=on_turn, greeting=greeting)
