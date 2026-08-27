"""Periodic reflection pass over the week's conversation logs (TODO.md
Phase 14, `BLOCKERS.md` -> "Suggested feature improvements" F):
`hi/vault.py`'s `hi/conversations/` logs are already written for every
persona, every turn, but nothing ever looks back over them for durable
facts/preferences worth remembering beyond that one exchange — the only
way a fact reaches `hi/knowledge/preferences.md` today is the user (or
the model, mid-conversation) explicitly writing it there.

Deliberately run alongside the existing weekly retro trigger
(`hi/personas.py`'s `_maybe_generate_weekly_retro`), not a new daemon —
one more "next Sunday session" job, the same pattern this codebase
already uses three times over (inbox triage, weekly retro, and now
this), rather than a fourth different scheduling mechanism.

Proposals are appended to `hi/knowledge/preferences.md` under a dated
header, framed plainly as suggestions from the week's conversations —
never silently merged into existing content or presented as fact. It's
just a Markdown file: trivially prunable/editable by hand, same as
every other note in the vault, matching this project's own "filesystem
is the single source of truth" philosophy (`hi/CLAUDE.md`).
"""

from __future__ import annotations

from datetime import date, timedelta

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model
from hi.vault import CONVERSATIONS_DIR, KNOWLEDGE_DIR, with_frontmatter

PREFERENCES_PATH = KNOWLEDGE_DIR / "preferences.md"
_LOOKBACK_DAYS = 7
_MAX_LOG_CHARS = 40_000  # a real ceiling on what goes into the prompt, not a guess

_NOTHING_MARKER = "NOTHING"


def _recent_conversation_text(day: date, lookback_days: int = _LOOKBACK_DAYS) -> str:
    parts = []
    for i in range(lookback_days):
        log_path = CONVERSATIONS_DIR / f"{(day - timedelta(days=i)).isoformat()}.md"
        if log_path.exists():
            parts.append(log_path.read_text())
    text = "\n\n".join(parts)
    if len(text) > _MAX_LOG_CHARS:
        # Keep the most recent content (the tail), not the oldest — a
        # week-old exchange matters less than yesterday's for "durable
        # preference right now".
        text = text[-_MAX_LOG_CHARS:]
    return text


def propose_preferences(day: date | None = None) -> str | None:
    """Reads the last `_LOOKBACK_DAYS` of conversation logs and asks a
    model to propose durable facts/preferences worth saving — real
    recurring signals (a stated preference, a corrected assumption, a
    recurring project/tool/habit), not one-off small talk or anything
    already obviously in `hi/knowledge/preferences.md`. Returns None if
    there's nothing to propose (no logs, or the model found nothing
    durable) rather than writing a hollow "nothing found" entry."""
    day = day or date.today()
    conversation_text = _recent_conversation_text(day)
    if not conversation_text.strip():
        return None

    existing = PREFERENCES_PATH.read_text() if PREFERENCES_PATH.exists() else "(empty)"

    prompt = (
        "Below are this week's real conversation logs across all "
        "personas, followed by what's already saved in "
        "preferences.md. Propose ONLY genuinely durable facts or "
        "preferences worth remembering long-term — a stated "
        "preference, a corrected assumption, a recurring project/tool/ "
        "habit — never one-off small talk, never anything that's "
        "already in preferences.md below. Be conservative: if nothing "
        "durable stands out, reply with exactly the single word "
        f"{_NOTHING_MARKER} and nothing else.\n\n"
        f"Already saved in preferences.md:\n{existing}\n\n"
        f"This week's conversation logs:\n{conversation_text}\n\n"
        "If there is something worth saving, reply with a short "
        "Markdown bullet list, each bullet one durable fact/preference, "
        "nothing else — no preamble, no restating the instructions."
    )
    model = get_tier_model("sonnet")
    reply = invoke_with_retry(model, [HumanMessage(prompt)]).strip()
    if not reply or reply.strip().upper() == _NOTHING_MARKER:
        return None
    return reply


def run_weekly_reflection(day: date | None = None) -> bool:
    """Proposes preferences from the week's conversations and appends
    them to preferences.md if there's anything durable — returns
    whether anything was written. Safe to call unattended: any model
    failure just means nothing gets proposed this week, not a crash."""
    day = day or date.today()
    try:
        proposal = propose_preferences(day)
    except Exception:
        return False
    if not proposal:
        return False

    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    if not PREFERENCES_PATH.exists():
        PREFERENCES_PATH.write_text(with_frontmatter("", ["hi"]))
    with PREFERENCES_PATH.open("a") as f:
        if PREFERENCES_PATH.stat().st_size > 0:
            f.write("\n")
        f.write(f"## Proposed from the week of {day.isoformat()} (auto-reflection)\n\n{proposal}\n")
    return True


@tool
def reflect_on_week() -> str:
    """Look back over this week's conversation logs across all personas
    and propose durable facts/preferences worth saving to
    preferences.md — recurring signals, not one-off small talk. Runs
    automatically alongside the weekly retro too; this is for triggering
    it on demand instead of waiting for that."""
    wrote = run_weekly_reflection()
    if wrote:
        return "Proposed new preferences from this week's conversations — see hi/knowledge/preferences.md."
    return "Nothing durable stood out in this week's conversations."
