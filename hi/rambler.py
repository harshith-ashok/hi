"""The "rambler": turns a spoken ramble (fillers, false starts, self-corrections,
several asks in one breath) into a clean, structured request *before* it goes
to the agent. Runs on the haiku tier with reasoning off, like the router.

Short utterances skip the model call entirely.
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage

from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model_fast

SKIP_BELOW_WORDS = 8

PROMPT = """You clean up a spoken transcript into a request for an AI assistant.

Rules:
- Keep the speaker's meaning and voice ("I", "my"). Never add facts, names, or steps they did not say.
- Drop filler (um, like, you know), repeats, and false starts.
- Apply self-corrections: when the speaker says "no", "actually", "I mean" or "sorry" and restates something, ONLY the restated version survives. "remind me Thursday, no, Friday" -> "remind me Friday" (never "Thursday or Friday"). "email Priya, actually Rahul" -> "email Rahul".
- One simple ask: output it as one clear sentence.
- Several asks or details: output exactly this, omitting empty parts:
Goal: <one line>
Details:
- <fact or constraint they gave>
Steps:
1. <thing to do, in the order they want it>
- If something is genuinely unclear, keep their wording instead of guessing.
- Output only the cleaned request, nothing else.

Transcript:
"""


def structure(transcript: str) -> str:
    """Cleaned/structured version of `transcript` (the original on failure)."""
    text = transcript.strip()
    if len(text.split()) < SKIP_BELOW_WORDS:
        return text
    try:
        result = invoke_with_retry(get_tier_model_fast("haiku"), [HumanMessage(PROMPT + text)]).strip()
    except Exception:
        return text
    # drop a section header the model left empty ("Details:" then nothing)
    result = re.sub(r"^(Goal|Details|Steps):[ \t]*\n(?=(Goal|Details|Steps):|\Z)", "", result, flags=re.MULTILINE).strip()
    return result or text
