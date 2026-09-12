"""Deliberately minimal stand-in for TODO.md Phase 4 item 1's full
"weekday agents" (Mon-Sun context binding, not built — no persona/context
system genuinely bound to the day of week exists yet, and building one
speculatively without a concrete second consumer beyond the Phase 3
arbiter below isn't warranted). What Phase 3's arbiter actually needs is
just "does today have any special context" — satisfied here by an
optional, hand-maintained vault note per weekday
(<VAULT_PATH>/hi/knowledge/weekdays/<day>.md, e.g. monday.md) that, if
present, nudges scoring toward whatever it mentions.
"""

from __future__ import annotations

from datetime import date

from hi.vault import knowledge_dir

def _weekdays_dir():
    return knowledge_dir() / "weekdays"


def todays_context_note() -> str | None:
    day_name = date.today().strftime("%A").lower()
    path = _weekdays_dir() / f"{day_name}.md"
    if not path.exists():
        return None
    return path.read_text()
