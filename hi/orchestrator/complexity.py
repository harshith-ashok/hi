"""Extends `hi/router.py`'s classifier with a plan/no-plan signal
(TODO.md Phase 16, `BLOCKERS.md`'s orchestration section): "right now
`router.py` picks exactly one persona and one tier per turn — there's
no notion of a plan." The fix is the SAME haiku-tier classification call
`hi/router.py`'s `classify()` already makes every turn, asking for one
more field instead of a second model call — not a separate check run
alongside it.

This **supersedes** `hi/synthesis/planner.py`'s Phase 14 mechanism
(a cheap regex heuristic gating a *separate* opus-tier `decompose()`
call) rather than coexisting with it — running two independent
"does this need decomposition" checks on every turn would be pure
duplicated cost for the same question. `hi/repl.py` now calls
`classify_with_plan()` in place of both `hi.router.classify()` and
`hi.synthesis.planner`'s heuristic/decompose pair; that module has been
removed (see TODO.md Phase 16's completion note for what replaced it
and why).
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model_fast
from hi.personas import PERSONAS
from hi.router import PERSONA_DESCRIPTIONS, TIER_DESCRIPTIONS, TIERS


def classify_with_plan(prompt: str) -> tuple[str, str, bool]:
    """Returns (persona, tier, needs_plan) from one real model call.

    `needs_plan` is True only for a genuinely multi-step, multi-persona
    request (`BLOCKERS.md`'s own example: "set up my environment for
    kaapi, check whether its dependencies are outdated, and tell me if
    the README is stale") — conservative by design, defaulting to False
    on anything ambiguous. A wrongly-skipped plan just falls through to
    today's single-persona path (cheap); a wrongly-triggered one pays
    `orchestrator/graph.py`'s real DAG-executor cost for what was
    actually one task, so the bias runs the other way from
    `hi/synthesis/planner.py`'s old heuristic (which deliberately erred
    toward *false positives*, since it only gated a cheap follow-up
    check, not the DAG executor itself).
    """
    # Reasoning-off on purpose (get_tier_model_fast, not get_tier_model):
    # measured directly that HAIKU_MODEL's default reasoning=True makes
    # this three-word classification "think" before answering, adding
    # real, avoidable latency to literally every single turn — see
    # models.py's get_tier_model_fast() docstring for the measurement.
    model = get_tier_model_fast("haiku")
    persona_lines = "\n".join(f"- {name}: {desc}" for name, desc in PERSONA_DESCRIPTIONS.items())
    tier_lines = "\n".join(f"- {tier}: {desc}" for tier, desc in TIER_DESCRIPTIONS.items())
    selection_prompt = (
        "Classify the user's request below. Choose exactly one persona, "
        "exactly one tier, and whether it genuinely needs to be broken "
        "into multiple ordered sub-tasks across different "
        "personas/tools to be handled properly. Most requests do NOT "
        "need this — only mark it as needing a plan if the request is "
        "genuinely asking for several distinct things in one turn, e.g. "
        '"check my deadlines, then look up X, and save a note about '
        'it." A single question, even a complex one, does not need a '
        "plan.\n\n"
        f"Personas:\n{persona_lines}\n\n"
        f"Tiers:\n{tier_lines}\n\n"
        f"User request:\n{prompt}\n\n"
        "Reply with ONLY three lowercase words separated by spaces: "
        "<persona> <tier> <plan>, where <plan> is exactly 'yes' or 'no'. "
        "Example: term sonnet no"
    )
    reply = invoke_with_retry(model, [HumanMessage(selection_prompt)]).lower()

    persona = next((p for p in PERSONAS if p in reply), "term")
    tier = next((t for t in TIERS if t in reply), "sonnet")
    needs_plan = "yes" in reply.split()
    return persona, tier, needs_plan
