"""Normalizes arbitrary raw text — a hotkey capture, an inbox item, a
persona tool call — into a structured Task or Event and writes it to the
vault via hi/capture/store.py. One shared classifier so every capture path
(Phase 1's planned global-hotkey inbox, and any persona that wants to jot
something down right now) agrees on what "task" vs. "event" means, instead
of each guessing on its own.
"""

from __future__ import annotations

import json
from datetime import date

from langchain_core.messages import HumanMessage

from hi.capture.schema import Event, Task
from hi.capture.store import save
from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model

_PROMPT = """Classify the following raw note into either a task (something \
to do, with no fixed time) or an event (something happening at a specific \
date/time). Reply with ONLY a JSON object, no other text, in exactly one of \
these two shapes:

{{"kind": "task", "text": "...", "category": "...", "priority": "...", "due": "..."}}
{{"kind": "event", "text": "...", "category": "...", "when": "..."}}

- "text" is a short, cleaned-up restatement of the note.
- "category" is one of: assignment, test, hackathon, application, milestone, \
other — pick "other" if unclear.
- "due" (task) / "when" (event) is an ISO date (YYYY-MM-DD) or datetime if a \
specific time is mentioned, resolved relative to today, {today}. Omit the \
key entirely if the note doesn't mention a date.
- "priority" (task only) is one of: low, medium, high — omit if unclear.

Raw note: {raw_text}"""


def normalize_ambient(
    raw_text: str,
    source_persona: str | None = None,
    project: str | None = None,
) -> Task | Event:
    """Classify `raw_text` into a Task or Event via the haiku tier (cheap,
    high-volume classification — same reasoning as hi/router.py using haiku
    for per-turn routing), save it to the vault, and return the saved item.
    Falls back to a plain pending Task holding the raw text verbatim if the
    model's reply isn't parseable, so a capture is never silently dropped."""
    model = get_tier_model("haiku")
    prompt = _PROMPT.format(today=date.today().isoformat(), raw_text=raw_text)
    reply = invoke_with_retry(model, [HumanMessage(prompt)])
    item = _parse_reply(reply, raw_text, source_persona, project)
    return save(item)


def _parse_reply(
    reply: str,
    raw_text: str,
    source_persona: str | None,
    project: str | None,
) -> Task | Event:
    try:
        start, end = reply.index("{"), reply.rindex("}") + 1
        data = json.loads(reply[start:end])
    except (ValueError, json.JSONDecodeError):
        return Task(text=raw_text, source_persona=source_persona, project=project)

    text = str(data.get("text") or raw_text).strip() or raw_text
    category = data.get("category") or None

    if data.get("kind") == "event" and data.get("when"):
        return Event(
            text=text,
            when=str(data["when"]),
            category=category,
            source_persona=source_persona,
            project=project,
        )
    return Task(
        text=text,
        category=category,
        priority=data.get("priority") or None,
        due=data.get("due") or None,
        source_persona=source_persona,
        project=project,
    )
