"""Registry mapping persona names to their agent and per-turn behavior."""

import os
import threading
from dataclasses import dataclass
from datetime import date
from functools import partial
from typing import Callable, Optional

from hi.capture.triage import triage_inbox
from hi.model_warmup import warm_up
from hi.synthesis.reflection import run_weekly_reflection
from hi.synthesis.retro import generate_weekly_retro, this_weeks_retro_exists
from hi.vault import log_conversation

PERSONAS = ("butler", "docs", "web", "term")
LAUNCH_CWD_ENV_VAR = "HI_LAUNCH_CWD"
_SUNDAY = 6


def _maybe_generate_weekly_retro() -> None:
    """Auto-trigger for the weekly retro (TODO.md Phase 3 item 9): "next
    hi session on a Sunday" stands in for a genuinely separate cron/timer,
    the same pattern triage_inbox() already established for the inbox.

    The reflection pass (TODO.md Phase 14, hi/synthesis/reflection.py)
    rides along here deliberately, rather than being a fourth separate
    scheduling mechanism — "run alongside the existing weekly retro" was
    the explicit ask. Guarded by the same not-already-done check via
    this_weeks_retro_exists() (there's no separate "reflection already
    ran this week" marker — the retro note's existence is a fine proxy,
    since both are meant to fire on the same Sunday session) and, unlike
    the retro itself, failure-tolerant on its own terms too
    (run_weekly_reflection() already swallows model failures so one bad
    week doesn't block the retro from generating)."""
    if date.today().weekday() == _SUNDAY and not this_weeks_retro_exists():
        generate_weekly_retro()
        run_weekly_reflection()


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
    if name == "butler":
        from hi.agents.butler.butler import agent, model
        from hi.agents.butler.todo import pending_tasks_greeting

        greeting = pending_tasks_greeting()
    elif name == "docs":
        from hi.agents.docs.docs import agent, model
    elif name == "web":
        from hi.agents.web.web import agent, model
    elif name == "term":
        from hi.agents.term.resume import build_resume_context, matching_dev_flow_name
        from hi.agents.term.term import agent, model

        launch_cwd = os.environ.get(LAUNCH_CWD_ENV_VAR)
        if launch_cwd and matching_dev_flow_name(launch_cwd):
            greeting = build_resume_context(launch_cwd)
    else:
        raise ValueError(f"Unknown persona: {name}")

    # Warm the model up in the background rather than blocking here, so the
    # prompt appears and accepts input immediately instead of waiting on a
    # network round-trip before the user can even start typing. The inbox
    # triage pass (hi/capture/hotkey.py's untriaged captures) is the same
    # kind of "don't block startup" background work, so it rides along on
    # its own thread here too rather than needing a separate daemon.
    threading.Thread(target=warm_up, args=(model,), daemon=True).start()
    threading.Thread(target=triage_inbox, daemon=True).start()
    threading.Thread(target=_maybe_generate_weekly_retro, daemon=True).start()

    return Persona(name=name, agent=agent, on_turn=on_turn, greeting=greeting)


def get_agent_builder(name: str) -> Callable:
    """Lazily import and return a persona module's build_agent(model)
    factory, without constructing a default instance — used by
    hi/router.py to build a persona bound to a router-selected tier
    instead of that module's own fixed default model."""
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
