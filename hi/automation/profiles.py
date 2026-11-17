"""How each kind of turn is run: which tier, how it should write, and how long it may take.

One table, read by the turn pipeline (hi/server/turn.py) and by every background job, so "fast and short for the
island, thorough for a report" is decided in one place.
"""

from __future__ import annotations

from dataclasses import dataclass

CONCISE_STYLE = (
    "\n\n(Answer in at most three short sentences of plain text: no headings, no lists, no preamble.)"
)
REPORT_STYLE = (
    "\n\n(This is a background task and nobody is chatting with you. Write a report in Markdown. Start with a "
    "one-line headline that says what the reader needs to know. Then short sections. Cite sources. Do not end with a "
    "question or an offer.)"
)
JSON_STYLE = "\n\n(Reply with the JSON only: no prose, no code fence.)"


@dataclass(frozen=True)
class Profile:
    tier: str | None = None  # None: let the router choose
    max_tier: str | None = None  # the router may not go above this
    style: str = ""
    timeout_s: float = 0.0  # 0: no limit
    reasoning: bool = True


PROFILES: dict[str, Profile] = {
    "ui": Profile(),
    "voice": Profile(),
    "island": Profile(max_tier="sonnet", style=CONCISE_STYLE, timeout_s=30, reasoning=False),
    "heartbeat.triage": Profile(tier="haiku", style=JSON_STYLE, timeout_s=20, reasoning=False),
    "heartbeat.prepare": Profile(tier="sonnet", style=REPORT_STYLE, timeout_s=180),
    "schedule": Profile(tier="sonnet", style=REPORT_STYLE, timeout_s=300),
    "drop.describe": Profile(tier="haiku", style=REPORT_STYLE, timeout_s=120, reasoning=False),
    "drop.file": Profile(tier="sonnet", style=REPORT_STYLE, timeout_s=120),
}
_TIER_ORDER = ("haiku", "sonnet", "opus")


def profile(name: str) -> Profile:
    """The profile for an origin or a `origin.role` name; an unknown name is treated as an ordinary UI turn."""
    return PROFILES.get(name) or PROFILES.get(name.split(".")[0]) or PROFILES["ui"]


def cap_tier(tier: str, max_tier: str | None) -> str:
    """`tier`, lowered to `max_tier` if it is higher."""
    if max_tier is None or tier not in _TIER_ORDER or max_tier not in _TIER_ORDER:
        return tier
    return min(tier, max_tier, key=_TIER_ORDER.index)
