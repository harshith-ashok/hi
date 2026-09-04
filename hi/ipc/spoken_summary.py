"""Condenses a full agent response into one short, speakable sentence for
the voice companion app's TTS output (TODO.md Phase 5's "selective TTS":
don't read code blocks/tables/tool logs aloud, and never read a long
answer verbatim — reading out entire code blocks or long lists aloud is
what makes voice assistants unusable in practice).

Hard skip rules run first and unconditionally, before any model call:
code fences and pipe-table rows are stripped from what could be spoken at
all. If nothing speakable is left, no spoken summary is produced — the
app should show text silently rather than force something misleading to
be read aloud.
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage

from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model

_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_WHITESPACE_RE = re.compile(r"\s+")

# Below this length, the cleaned text is just spoken as-is — no model
# call needed for an answer that's already a sentence or two.
SHORT_ANSWER_MAX_CHARS = 220


def _strip_unspeakable(text: str) -> str:
    text = _CODE_FENCE_RE.sub(" ", text)
    text = _TABLE_ROW_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def make_spoken_summary(full_text: str) -> str | None:
    """Returns a short sentence to speak aloud, or None if there's
    nothing safely speakable left (pure code/table, or an empty answer)."""
    cleaned = _strip_unspeakable(full_text)
    if not cleaned:
        return None
    if len(cleaned) <= SHORT_ANSWER_MAX_CHARS:
        return cleaned

    model = get_tier_model("haiku")
    prompt = (
        "Condense the following into ONE short, natural spoken sentence a "
        "voice assistant could say aloud — no markdown, no code, no lists, "
        "just plain spoken English summarizing the key point:\n\n"
        f"{cleaned[:2000]}"
    )
    summary = invoke_with_retry(model, [HumanMessage(prompt)]).strip()
    return summary or cleaned[:SHORT_ANSWER_MAX_CHARS]
