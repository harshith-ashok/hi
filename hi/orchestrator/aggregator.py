"""Synthesizes one final answer from an orchestrated run's per-task
results (TODO.md Phase 16) — the same "combine several real results
into one coherent answer" shape `hi/synthesis/planner.py`'s Phase 14
`run_plan()` used for a flat ordered list of steps (that module is now
retired — see Phase 16's completion note), now over a real DAG's
results instead, some of which may have run in parallel.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model
from hi.orchestrator.planner import TaskSpec


def synthesize(original_prompt: str, tasks: list[TaskSpec], results: dict[str, str]) -> str:
    """Sonnet tier — this is summarizing already-gathered results, not
    the harder decomposition judgment call planner.py's opus-tier call
    already made, so it doesn't need opus."""
    tasks_summary = "\n\n".join(
        f"Task {t.id} ({t.persona}): {t.description}\nResult: {results.get(t.id, '(no result — this task did not complete)')}"
        for t in tasks
    )
    prompt = (
        f"The user originally asked:\n{original_prompt}\n\n"
        "This was broken into a task DAG, each task carried out "
        "separately (some in parallel) by a specialized assistant. "
        "Write ONE coherent final answer addressing the user's original "
        "request, based on these real results — don't just restate the "
        "tasks, synthesize an actual answer a person would find useful. "
        "If a task has no result, acknowledge that rather than "
        "inventing one.\n\n"
        f"{tasks_summary}"
    )
    model = get_tier_model("sonnet")
    return invoke_with_retry(model, [HumanMessage(prompt)])
