"""The agents `hi` can run, and how to build one for a model.

term and butler are what the router picks between. docs and web are narrower agents: the
orchestrator uses them as scoped subagents, and tinyui can force one for a turn.
"""

from typing import Callable

PERSONAS = ("butler", "docs", "web", "term")


def get_agent_builder(name: str) -> Callable:
    """Lazily import and return a persona module's build_agent(model) factory, so unrelated
    personas' dependencies aren't loaded."""
    if name == "butler":
        from hi.agents.butler.butler import build_agent
    elif name == "docs":
        from hi.agents.docs.docs import build_agent
    elif name == "web":
        from hi.agents.web.web import build_agent
    elif name == "term":
        from hi.agents.term.term import build_agent
    else:
        raise ValueError(f"Unknown persona: {name}")
    return build_agent
