"""Builds one scoped agent per DAG node (TODO.md Phase 16): a plain,
stateless `create_agent()` ReAct agent for exactly one task — built
directly, not through each persona's own `build_agent(model)` factory,
since that wraps `term` in cross-turn conversation memory
(`_StatefulAgent`) and vault grounding (`hi/memory_graph.py`) that a
single scoped task within one orchestrated run doesn't need (a
deliberate simplification: a DAG subagent answers one self-contained
task and reports back, it doesn't carry a session forward). Every
persona module already exposes the same two things this needs —
`PROMPT_PATH` and `TOOLS` — so this is a thin, uniform builder over all
four, not four bespoke cases.

Least privilege: `tool_scope`, if given, narrows the subagent to only
the named subset of that persona's own tools, instead of always handing
over the full list — the planner (`planner.py`) decides which tools
each task actually needs.

Named archetypes (TODO.md Phase 20): `archetype`, if given, layers a
short role-framing instruction ("you're also acting as a Researcher/
Coder/Reviewer/Fixer for this task") onto the persona's own system
prompt. Deliberately orthogonal to `persona` rather than a replacement
for it — persona still governs which real tools exist (term's shell
access vs. docs' vault tools vs. web's search), archetype only governs
*how* the task is approached with whichever tools that persona already
has. The planner (`planner.py`) assigns both per task.
"""

from __future__ import annotations

import importlib

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel

_PERSONA_MODULES = {
    "term": "hi.agents.term.term",
    "butler": "hi.agents.butler.butler",
    "docs": "hi.agents.docs.docs",
    "web": "hi.agents.web.web",
}

# TODO.md Phase 20's four named archetypes. Kept short and generic on
# purpose — this is a framing nudge layered onto whichever persona
# prompt already carries the real tool-specific instructions, not a
# second full system prompt competing with it.
ARCHETYPES: dict[str, str] = {
    "researcher": (
        "You are also acting as a Researcher for this specific task: "
        "prioritize gathering accurate, well-sourced information over "
        "speed, and say plainly when something couldn't be confirmed "
        "rather than guessing or filling a gap with a plausible-sounding "
        "invention."
    ),
    "coder": (
        "You are also acting as a Coder for this specific task: write "
        "correct, minimal code, and verify it actually runs and produces "
        "the right output (don't just assert that it does) before "
        "reporting it as done."
    ),
    "reviewer": (
        "You are also acting as a Reviewer for this specific task: "
        "critically check another task's own output (given to you as "
        "context above) for correctness, safety, and whether it actually "
        "satisfies what was asked — don't assume it's fine just because "
        "it looks complete."
    ),
    "fixer": (
        "You are also acting as a Fixer for this specific task: given a "
        "described failure or gap, diagnose the actual root cause first, "
        "then propose or make the smallest change that addresses it — "
        "don't guess at a fix before understanding why it broke."
    ),
}


def persona_tool_names(persona: str) -> list[str]:
    """The real tool names available to `persona` — used by the planner
    to ground its `tool_scope` choices in tools that actually exist,
    rather than letting a model guess at plausible-sounding names."""
    tools, _prompt = _persona_tools_and_prompt(persona)
    return [t.name for t in tools]


def _persona_tools_and_prompt(persona: str):
    if persona not in _PERSONA_MODULES:
        raise ValueError(f"Unknown persona '{persona}'. Expected one of: {sorted(_PERSONA_MODULES)}")
    module = importlib.import_module(_PERSONA_MODULES[persona])
    return module.TOOLS, module.PROMPT_PATH.read_text()


def build_subagent(
    model: BaseChatModel,
    persona: str,
    tool_scope: list[str] | None = None,
    archetype: str | None = None,
):
    """Builds a scoped ReAct agent for one DAG task.

    Args:
        model: the tier-resolved chat model for this task.
        persona: which persona's system prompt/tools to use.
        tool_scope: if given, only these tool names from that persona's
            full list. An empty match (every name in tool_scope was
            unrecognized — a planner mistake, not assumed to be
            deliberate) falls back to the full tool list rather than
            leaving the subagent with zero tools and no way to do
            anything.
        archetype: if given and recognized (see `ARCHETYPES`), layers
            that role's framing onto the persona's own system prompt.
            An unrecognized value is silently ignored rather than
            raising — a planner-invented archetype name shouldn't sink
            an otherwise-valid task.
    """
    tools, prompt = _persona_tools_and_prompt(persona)
    if tool_scope:
        allowed = set(tool_scope)
        scoped = [t for t in tools if t.name in allowed]
        tools = scoped or tools
    if archetype:
        overlay = ARCHETYPES.get(archetype.lower())
        if overlay:
            prompt = f"{prompt}\n\n{overlay}"
    return create_agent(model=model, tools=tools, system_prompt=prompt)
