"""A running summary of the turns of a chat that no longer fit the model's context window.

The summary lives in the session note's body (hi/memory/sessions.py). When a turn had to leave older turns out, a
background job folds them into the summary with the fast model; the next turn puts it at the top of the history.
If the summary model is down the chat carries on without it (health records the failure and the job backs off).
"""

from __future__ import annotations

import logging
from typing import Callable

from hi.core import health, jobs
from hi.memory import sessions, transcript

log = logging.getLogger(__name__)

DEP = "chat-summary"
MAX_CHARS = 2400
PER_TURN_CHARS = 600

_PROMPT = (
    "You keep a running summary of a long conversation between a user and their assistant, so the assistant can "
    "carry on after the oldest messages are forgotten. Update the summary with the new messages. Keep decisions, "
    "facts, names, numbers, preferences, files and open questions; drop small talk. Plain text, at most 250 words. "
    "Reply with the summary only.\n\nSummary so far:\n{previous}\n\nNew messages:\n{turns}"
)


def messages(summary: str) -> list[dict]:
    """The summary as the first exchange of a history."""
    return [
        {"role": "user", "content": f"Summary of the earlier messages in this chat, which are no longer in front of you:\n{summary}"},
        {"role": "assistant", "content": "Understood. I'll use that as background."},
    ]


def _fold(previous: str, turns: list[dict]) -> str:
    from langchain_core.messages import HumanMessage

    from hi.llm.registry import get_tier_model_fast
    from hi.llm.resilience import invoke_with_retry

    text = "\n\n".join(f"User: {t['ask'][:PER_TURN_CHARS]}\nAssistant: {(t.get('answer') or '')[:PER_TURN_CHARS]}" for t in turns)
    reply = invoke_with_retry(get_tier_model_fast("haiku"), [HumanMessage(_PROMPT.format(previous=previous or "(none yet)", turns=text))])
    return str(reply).strip()[:MAX_CHARS]


def summarise(session: str, head: str, dropped: int, fold: Callable[[str, list[dict]], str] = _fold) -> bool:
    """Bring the summary of `session` up to date with the `dropped` oldest turns on the branch ending at `head`.
    Returns True when it was updated."""
    if not health.is_up(DEP):
        return False
    omitted = transcript.counted_turns(session, head)[:dropped]
    s = sessions.get(session)
    if not omitted or s is None or s.summary_through == omitted[-1]["id"]:
        return False
    ids = [t["id"] for t in omitted]
    continues = s.summary_through in ids  # the saved summary covers the start of this very branch
    new = omitted[ids.index(s.summary_through) + 1:] if continues else omitted
    try:
        text = fold(s.summary if continues else "", new)
    except Exception as e:  # boundary: a model failure must never break a chat
        health.mark_down(DEP, e)
        log.warning("could not summarise %s: %r", session, e)
        return False
    if not text:
        return False
    health.mark_ok(DEP)
    return sessions.set_summary(session, text, omitted[-1]["id"])


def summarise_async(session: str, head: str, dropped: int) -> None:
    jobs.run_background(f"summary-{session}", lambda: summarise(session, head, dropped))
