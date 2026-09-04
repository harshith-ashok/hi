"""A second, cheap-tier check on a shell command already flagged as
destructive (TODO.md Phase 20: "Reviewer-verifies-Coder for destructive
plans") — run right before `hi/action_tiers.py`'s `confirm_destructive()`
gate, so whoever approves the action (a human at the y/N prompt, or the
voice companion's pending-approval queue) sees a second opinion on what
the command actually does, not just the fact that it's already known to
be destructive.

Deliberately haiku-tier and a single plain model call, not a full
`create_agent()` ReAct loop: judging one already-written shell command
string needs no tools, and this runs on the hot path of every single
destructive command (interactive or orchestrated), so keeping it cheap
and fast matters more than squeezing out marginal extra caution from a
bigger model. It's conceptually the `subagent.py` Reviewer archetype's
same framing ("critically check another [task/command]'s own output,
don't assume it's fine") applied to a Coder subagent's proposed shell
command instead of another subagent's text output.

This is unrelated to `hi/orchestrator/graph.py`'s tier-escalation retry
— that escalates a *failed* subagent's own task; this always runs once,
never escalates, and never blocks anything itself — it only adds
information to what `confirm_destructive()`'s approver sees.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model_fast

_NO_CONCERN = "NONE"


def review_shell_command(command: str) -> str | None:
    """Returns a short human-readable concern string if the reviewer
    flags something worth a human's extra attention beyond the command's
    own already-declared destructive nature, else None. Fails open
    (returns None) on any model error — a broken reviewer must never be
    the reason a legitimate action can't proceed at all."""
    instruction = (
        "A terminal assistant is about to run this shell command, which "
        "has already been flagged as destructive/hard-to-reverse and is "
        "about to be shown to a human for y/N approval:\n\n"
        f"    {command}\n\n"
        "Look specifically for anything that goes further than a normal, "
        "reasonably-scoped destructive command would — an unusually "
        "broad path (deleting outside a project directory, a wildcard or "
        "root-level path), a command chained onto something unrelated "
        "via && or ;, or a command whose actual effect doesn't match "
        f"what it looks like it's meant to do. Reply with EXACTLY the "
        f"single word {_NO_CONCERN} if nothing like that stands out, or "
        "otherwise one short sentence (under 25 words) naming the "
        "specific concern."
    )
    try:
        # get_tier_model_fast, not get_tier_model: a plain yes/no-style
        # safety check doesn't need visible chain-of-thought, and this
        # runs on the hot path of every destructive command — see
        # models.py's get_tier_model_fast() docstring for why.
        model = get_tier_model_fast("haiku")
        reply = invoke_with_retry(model, [HumanMessage(instruction)]).strip()
    except Exception:
        return None

    if not reply or reply.upper().startswith(_NO_CONCERN):
        return None
    return reply
