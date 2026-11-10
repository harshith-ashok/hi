"""Proactive nudges: the assistant speaks first, about what the user is doing right now, or says nothing.

`nudge()` is called by the context daemon every few minutes. It shows a local model the live context
(app, window, activity, visible text), the open loops and the recent nudges, and asks for ONE specific,
useful remark or NONE. Gates, cheapest first: user is active (not idle), context is fresh and not private,
the interruption budget (hi/suggest/engine.py) has room, the model says it is worth it, and it is not a
repeat. Notification only; speech is for urgent things and is not used here.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from hi.context import now

NUDGE_EVERY = 300  # seconds between considerations
ACTIVE_WITHIN = 120  # the user must have touched the keyboard/mouse this recently
STATE = now.DIR / "nudges.json"
RECENT_KEPT = 8

_PROMPT = """You are the user's always-present assistant. You can see what they are doing on their Mac.
Decide whether to say ONE thing right now unprompted.

{context}

Open loops and reminders:
{loops}

Things you already said recently (never repeat or rephrase these):
{recent}

Speak ONLY if you can be specific and genuinely useful about what is on screen right now: a visible error you
can explain, the user visibly stuck on the same thing for a long time, a deadline that matches what they have
open, an obvious next step. Never greet, never list options, never ask "what do you want to do", never comment
on routine activity. It must be about the screen text or window above, not about the task list alone.
Reply in exactly this format:
EVIDENCE: <an exact quote, 12+ characters, copied from the screen text or window title above>
MESSAGE: <one sentence, max 25 words, addressed to the user, ending with an offer or question>
If there is nothing clearly worth interrupting for, reply exactly: NONE"""


def _recent() -> list[str]:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return []


def _loops() -> str:
    from hi import reflection_agent
    from hi.agents.butler.todo import pending_tasks_greeting

    parts = [reflection_agent.latest_open_loops() or "", pending_tasks_greeting() or ""]
    return "\n".join(p for p in parts if p).strip() or "(none)"


def compose(include_screen: bool = True) -> str | None:
    """One contextual remark, or None. Local models only: screen text never goes to a hosted model."""
    from langchain_core.messages import HumanMessage

    from hi.context.daemon import local_model_ok
    from hi.models import get_tier_model_fast

    context = now.describe(include_screen)
    if not context or not local_model_ok():
        return None
    recent = _recent()
    prompt = _PROMPT.format(context=context, loops=_loops(), recent="\n".join(f"- {r}" for r in recent) or "(nothing yet)")
    reply = get_tier_model_fast("haiku").invoke([HumanMessage(prompt)]).content.strip()
    return _grounded(reply, context, recent)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _grounded(reply: str, context: str, recent: list[str]) -> str | None:
    """The message, only if the model quoted real text from the context as evidence (a code check,
    because a small model otherwise speaks up about things it invented)."""
    evidence = re.search(r"EVIDENCE:\s*(.+)", reply)
    message = re.search(r"MESSAGE:\s*(.+)", reply)
    if not evidence or not message:
        return None
    quote, text = _norm(evidence.group(1).strip(' "\'`')), message.group(1).strip(' "')
    if len(quote) < 12 or quote not in _norm(context) or text in recent:
        return None
    return text


def nudge() -> str | None:
    """Consider interrupting; notify and record if worthwhile. Returns what was said."""
    from hi.suggest import engine

    snapshot = now.read()
    if not snapshot or snapshot.get("paused") or snapshot.get("private") or snapshot.get("idle", 0) > ACTIVE_WITHIN:
        return None
    if engine._budget_left() <= 0:
        return None
    message = compose()
    if message is None:
        return None
    engine._notify(message)
    engine._record_notification()
    STATE.write_text(json.dumps((_recent() + [message])[-RECENT_KEPT:]))
    return message


def due(last: float) -> bool:
    return time.time() - last >= NUDGE_EVERY
