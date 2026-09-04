"""Decomposes a complex turn into a task DAG (TODO.md Phase 16):
`{persona, tier, tool_scope, depends_on}` nodes, built at runtime per
turn via one real opus-tier call — the strongest model, same as
`hi/synthesis/planner.py`'s Phase 14 `decompose()` used for its
(now-superseded) flat ordered-list version, but asked here for real
dependency structure too, since the whole point of a DAG over a flat
list is letting genuinely independent tasks run *in parallel*
(`orchestrator/graph.py`) rather than always sequentially.

Structured JSON, not free-text lines like Phase 14's `decompose()` —
that format only needed to carry an order; this one needs ids,
dependency edges, and a tool subset per task, which free text can't
express reliably.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage

from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model
from hi.orchestrator.budget import default_tier, max_tasks
from hi.orchestrator.subagent import ARCHETYPES, persona_tool_names
from hi.personas import PERSONAS


@dataclass(frozen=True)
class TaskSpec:
    id: str
    description: str
    persona: str
    tier: str
    tool_scope: list[str] = field(default_factory=list)  # empty = full tool list
    depends_on: list[str] = field(default_factory=list)
    archetype: str = ""  # "" = no role overlay; else one of subagent.ARCHETYPES


def _tools_reference() -> str:
    lines = []
    for persona in PERSONAS:
        names = ", ".join(persona_tool_names(persona))
        lines.append(f"- {persona}: {names}")
    return "\n".join(lines)


def plan_tasks(prompt: str) -> list[TaskSpec] | None:
    """Returns an ordered list of 2+ `TaskSpec`s forming a real DAG, or
    None if the request doesn't actually decompose into one (including
    on any parsing/model failure — a planning failure must fall back to
    today's single-persona path, never crash the turn)."""
    task_cap = max_tasks()
    preferred_tier = default_tier()
    archetype_names = ", ".join(ARCHETYPES)
    instruction = (
        "Decompose the user's request below into a task DAG for a "
        "terminal assistant with four specialized personas. Each task "
        "must be assigned to exactly one persona, and may declare which "
        "other task ids it depends on (needs that task's result before "
        "it can run) — tasks with no shared dependency should be marked "
        "independent so they can run in parallel; don't force a "
        "sequential chain when tasks genuinely don't need each other's "
        "output.\n\n"
        f"Personas and their real tool names:\n{_tools_reference()}\n\n"
        "Reply with ONLY a JSON array (no other text), each element "
        "shaped exactly like this:\n"
        '{"id": "t1", "description": "<a complete, self-contained '
        'instruction>", "persona": "term", "tier": "sonnet", '
        '"tool_scope": ["read_project_file"], "depends_on": [], '
        '"archetype": "coder"}\n\n'
        f"tier is one of haiku/sonnet/opus ({preferred_tier} for most "
        "tasks; opus only for a genuinely hard one). tool_scope lists "
        "ONLY real tool names from that persona's list above — omit it "
        "(or leave empty) to allow that persona's full tool set. "
        "depends_on lists other tasks' ids, or is empty if independent. "
        f"archetype is OPTIONAL — one of {archetype_names} if a task "
        "genuinely fits one of those roles (e.g. a task that writes code "
        "is \"coder\", a task that double-checks another task's own "
        "output is \"reviewer\"), omit it entirely if none fits. "
        f"At most {task_cap} tasks — group related work together "
        "instead of exceeding that.\n\n"
        "If this request is really just one task and doesn't need "
        'decomposition, reply with exactly: []\n\n'
        f"Request:\n{prompt}"
    )
    try:
        model = get_tier_model("opus")
        reply = invoke_with_retry(model, [HumanMessage(instruction)]).strip()
        # A model reply is occasionally fenced in ```json ... ``` despite
        # the "no other text" instruction — strip that before parsing
        # rather than failing outright on an otherwise-valid response.
        if reply.startswith("```"):
            reply = reply.strip("`").removeprefix("json").strip()
        raw_tasks = json.loads(reply)
    except Exception:
        return None

    if not isinstance(raw_tasks, list) or len(raw_tasks) < 2:
        return None

    tasks: list[TaskSpec] = []
    valid_ids: set[str] = set()
    for raw in raw_tasks[:task_cap]:
        try:
            task_id = str(raw["id"])
            raw_archetype = str(raw.get("archetype") or "").strip().lower()
            tasks.append(
                TaskSpec(
                    id=task_id,
                    description=str(raw["description"]),
                    persona=raw["persona"] if raw.get("persona") in PERSONAS else "term",
                    tier=raw.get("tier") if raw.get("tier") in ("haiku", "sonnet", "opus") else preferred_tier,
                    tool_scope=[str(t) for t in raw.get("tool_scope") or []],
                    depends_on=[str(d) for d in raw.get("depends_on") or []],
                    archetype=raw_archetype if raw_archetype in ARCHETYPES else "",
                )
            )
            valid_ids.add(task_id)
        except (KeyError, TypeError):
            continue  # one malformed task shouldn't sink an otherwise-usable plan

    if len(tasks) < 2:
        return None

    # A depends_on referencing an id that doesn't exist in this plan
    # (a model mistake) would leave that task permanently unreachable in
    # the DAG — drop the dangling reference rather than let the whole
    # run deadlock on an edge to nowhere.
    cleaned = [
        TaskSpec(
            id=t.id,
            description=t.description,
            persona=t.persona,
            tier=t.tier,
            tool_scope=t.tool_scope,
            depends_on=[d for d in t.depends_on if d in valid_ids and d != t.id],
            archetype=t.archetype,
        )
        for t in tasks
    ]
    return _break_cycles(cleaned)


def _break_cycles(tasks: list[TaskSpec]) -> list[TaskSpec]:
    """A model-produced dependency graph can accidentally contain a
    cycle (t1 depends on t2, t2 depends on t1) — undetectable from
    either task in isolation, and fatal to graph.py's executor (a cycle
    with no conditional edge deadlocks LangGraph's own execution rather
    than erroring cleanly). Detected via plain DFS with a recursion
    stack; the specific edge that closes each cycle found is dropped
    (not the whole task) so the rest of the plan stays intact."""
    edges: dict[str, list[str]] = {t.id: list(t.depends_on) for t in tasks}

    def has_path(start: str, target: str, seen: set[str]) -> bool:
        if start == target:
            return True
        seen.add(start)
        return any(nxt not in seen and has_path(nxt, target, seen) for nxt in edges.get(start, []))

    for task_id, deps in edges.items():
        kept = []
        for dep in deps:
            # dep -> task_id is the edge about to exist; it closes a
            # cycle only if task_id can already reach dep through some
            # other already-kept path.
            if has_path(dep, task_id, set()):
                continue
            kept.append(dep)
        edges[task_id] = kept

    return [
        TaskSpec(
            id=t.id,
            description=t.description,
            persona=t.persona,
            tier=t.tier,
            tool_scope=t.tool_scope,
            depends_on=edges[t.id],
            archetype=t.archetype,
        )
        for t in tasks
    ]
