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

**Always rewritten, not just condensed when long** (reported live: a
mechanical action confirmation like "I opened www.youtube.com in Safari"
was read completely literally — including the URL, dot by dot — because
it was short enough to skip the old length-gated model call entirely).
`SHORT_ANSWER_MAX_CHARS` used to mean "skip rewriting under this length";
it's now only a fallback truncation if the rewrite call itself fails, and
the rewrite always runs through get_tier_model_fast() (no reasoning) —
this is a plain rewrite, not a judgment call that benefits from visible
chain-of-thought, and reasoning-on here would add several seconds of
dead air before TTS starts speaking, same latency cost this project has
already found and fixed for other single-purpose classification/rewrite
calls (hi/memory_graph.py, hi/router.py's classify()).
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage

from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model_fast

_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_WHITESPACE_RE = re.compile(r"\s+")

# Fallback truncation length if the rewrite call fails outright — not a
# "skip rewriting" threshold anymore (see module docstring).
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

    model = get_tier_model_fast("haiku")
    prompt = (
        "Rewrite the following into ONE short, natural sentence a voice "
        "assistant would actually say out loud — describe what happened "
        "or answer the question in plain spoken English, in your own "
        "words, not a literal reading of the text. No markdown, no code, "
        "no lists. Never read a URL, file path, or raw technical string "
        "literally — say what it means instead (e.g. \"YouTube is now "
        "open\", not \"I opened www dot youtube dot com\"; \"Wi-Fi is "
        "off\", not \"toggle_wifi returned false\"). Reply with only the "
        "sentence, nothing else:\n\n"
        f"{cleaned[:2000]}"
    )
    summary = invoke_with_retry(model, [HumanMessage(prompt)]).strip()
    return summary or cleaned[:SHORT_ANSWER_MAX_CHARS]
