"""Multi-turn negotiation for the arbiter (TODO.md Phase 15,
`BLOCKERS.md` -> "Ambient & real-time gaps" #5): today, "what should I
work on" -> a recommendation -> "no, something else" is three unrelated
turns — the pushback has no way to know it's rejecting the previous
turn's specific answer, since `hi/router.py`'s `classify()` classifies
every turn independently with no concept of "responding to the
assistant's own prior turn." Calling `what_next()` again from scratch
would just recommend the exact same task, since it has no memory of
what was already turned down.

Two small pieces, deliberately kept out of `hi/repl.py` itself so the
main loop stays readable:

- `find_arbiter_tool_result(messages)`: scans ONE turn's own messages
  (not the whole session history — `hi/repl.py` passes only the slice
  after the turn's HumanMessage) for a `what_next`/`what_next_smart`
  tool call+result. This is how a pushback gets detected from the
  outside — `term`'s own tools don't need to separately notify
  anything; the ReAct loop's real message history already records
  which tool ran and what it returned.
- `looks_like_pushback(text)`: a cheap regex check, no model call —
  only ever consulted by `hi/repl.py` when the *previous* turn's
  answer actually came from the arbiter, so it can't misfire on an
  unrelated "no" turns later.
"""

from __future__ import annotations

import re

_PUSHBACK_RE = re.compile(
    r"^(no+|nah|nope)\b|\b(something else|not that|a different (one|task)|"
    r"another one|anything else|something different|pick (another|a "
    r"different) one)\b",
    re.IGNORECASE,
)


def looks_like_pushback(text: str) -> bool:
    """Cheap, model-free check for whether `text` is rejecting a prior
    recommendation — only meaningful when the caller already knows the
    previous turn was an arbiter answer."""
    return bool(_PUSHBACK_RE.search(text.strip()))


def find_arbiter_tool_result(messages: list) -> str | None:
    """Scans `messages` (expected to be just this turn's own messages,
    from its HumanMessage onward — the whole session history would
    wrongly match an arbiter call from many turns ago) for a
    what_next/what_next_smart tool result. Returns its raw text
    ("<task>\\n(<rationale>)") if found, else None."""
    for m in messages:
        if getattr(m, "name", None) in ("what_next", "what_next_smart"):
            return m.content
    return None
