"""Background triage pass: classifies every untriaged item in
<VAULT_PATH>/hi/tasks/inbox/ (raw hotkey captures, hi/capture/hotkey.py)
into a real Task/Event via hi/capture/ambient.py, then removes the inbox
file. Run once at the start of every `hi` session (hi/personas.py), per
TODO.md's own "next hi session, or on a timer" — no separate background
daemon needed for this part.
"""

from __future__ import annotations

from hi.capture.ambient import normalize_ambient
from hi.capture.inbox import list_inbox_items


def triage_inbox() -> int:
    """Classify and remove every pending inbox item; returns how many
    were processed. Safe to call every session start — a no-op once the
    inbox is empty."""
    items = list_inbox_items()
    for path in items:
        raw_text = path.read_text().strip()
        if raw_text:
            normalize_ambient(raw_text, source_persona="capture-inbox")
        path.unlink()
    return len(items)
