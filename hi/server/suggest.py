"""Inline completion for the chat box: given the words typed so far, a few likely next words."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage

from hi.llm.registry import get_tier_model_fast

log = logging.getLogger(__name__)

MIN_CHARS = 6
MAX_TYPED_CHARS = 400
MAX_SUGGESTION_CHARS = 120
MAX_RECENT = 5


def clean_completion(typed: str, raw: str) -> str:
    """The continuation to show after `typed`: one line, never repeating what is already typed, '' if unusable."""
    text = raw.strip().splitlines()[0].strip('"') if raw.strip() else ""
    if text.lower().startswith(typed.lower()):  # the model echoed the start; keep only what follows
        text = text[len(typed):]
    if not text.strip():
        return ""
    joiner = "" if typed.endswith((" ", "\n")) or text.startswith((" ", ",", ".", "?", "!", ":", ";")) else " "
    if typed.endswith(" "):
        text = text.lstrip()
    return (joiner + text)[:MAX_SUGGESTION_CHARS].rstrip()


def suggest(typed: str, recent: list[str]) -> str:
    """The suggested continuation of `typed` ('' when there is none or the model is unavailable). A failure is
    not an error to the user: the box simply shows no suggestion."""
    typed = typed[:MAX_TYPED_CHARS]
    if len(typed.strip()) < MIN_CHARS or "\n" in typed or typed.startswith("/"):
        return ""
    examples = "\n".join(f"- {m[:200]}" for m in recent[-MAX_RECENT:])
    prompt = (
        "You complete the message a user is typing to their personal assistant. Reply with ONLY the words that "
        "come next, continuing exactly where the text stops: no quotes, no repeat of the typed text, one short "
        "phrase (at most about 12 words). If you cannot tell, reply with nothing.\n"
        + (f"Their recent messages, for style and topics:\n{examples}\n" if examples else "")
        + f"\nTyped so far: {typed}"
    )
    try:
        return clean_completion(typed, str(get_tier_model_fast("haiku").invoke([HumanMessage(prompt)]).content))
    except Exception as e:  # a suggestion is optional; never surface this
        log.debug("suggestion failed: %r", e)
        return ""
