"""Reflection: a model looks back over the journal and writes what mattered.

    <VAULT_PATH>/hi/reflections/YYYY-MM-DD.md      (a day)
    <VAULT_PATH>/hi/reflections/A..B.md            (several days)

Each note has: Summary, Decisions, Open loops, Lessons (what failed or was
corrected, so it can be done better next time). The newest note's open loops
feed back into the agent's context (hi/vault_context.py). After reflecting,
the memory file is consolidated: duplicates merged, stale or contradicted
items dropped, with the previous version saved under hi/memory/history/.

`maybe_reflect_yesterday()` is called when a turn starts and runs in a
background thread, at most once per day.
"""

from __future__ import annotations

import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from langchain_core.messages import HumanMessage

import hi.config as config
from hi import journal, memory
from hi.frontmatter import with_frontmatter
from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model

MAX_JOURNAL_CHARS = 30_000
CONSOLIDATE_AT_LINES = 25
MIN_KEPT_FRACTION = 0.4  # refuse a consolidation that deletes more than this much

_REFLECT_PROMPT = """You are the reflective part of a personal assistant. Below is its journal for {period}, and what it remembers about the user.
Write a short reflection in Markdown with exactly these sections:
## Summary
2-4 sentences: what the user worked on and what got done.
## Decisions
Bullets: decisions the user made. Omit the section body with "None." if none.
## Open loops
Bullets: things started or promised but not finished, each with enough detail to resume it.
## Lessons
Bullets: where the assistant failed, retried, was corrected, or was slow, and what to do differently. "None." if none.
Base EVERY bullet only on what the journal shows. The memory is background so you can understand the journal; never copy memory items into the sections. An open loop must be something the user or the assistant explicitly left unfinished in the journal: do not suggest follow-ups of your own. Be concrete, reuse [[wikilinks]] exactly as written in the journal, no preamble.

Memory:
{memory}

Journal:
{journal}"""

_CONSOLIDATE_PROMPT = """Below is the long-term memory file of a personal assistant (Markdown, sections of bullets with dates).
Rewrite the whole file: merge duplicates, drop items clearly contradicted by newer ones, keep every other bullet, its date and [[link]], keep the same `## ` sections and the frontmatter.
Do not add anything new. Reply with ONLY the complete file.

{memory}"""

_lock = threading.Lock()
_running = False


def reflections_dir() -> Path:
    return config.VAULT_PATH / "hi" / "reflections"


def _journal_text(days: list[date]) -> str:
    parts = [p.read_text() for d in days if (p := journal.journal_dir() / f"{d.isoformat()}.md").exists()]
    return "\n\n".join(parts)[-MAX_JOURNAL_CHARS:]


def reflect(days: int = 1, end: date | None = None) -> Path | None:
    """Reflect on the `days` days ending at `end` (default: yesterday). Returns the note, or None if the journal is empty."""
    end = end or date.today() - timedelta(days=1)
    span = [end - timedelta(days=i) for i in reversed(range(days))]
    text = _journal_text(span)
    if not text.strip():
        return None
    period = span[-1].isoformat() if days == 1 else f"{span[0].isoformat()} to {span[-1].isoformat()}"
    prompt = _REFLECT_PROMPT.format(period=period, memory=memory.read_memory(3000) or "(empty)", journal=text)
    body = invoke_with_retry(get_tier_model("sonnet"), [HumanMessage(prompt)]).strip()
    if "## " not in body:
        return None
    name = span[-1].isoformat() if days == 1 else f"{span[0].isoformat()}..{span[-1].isoformat()}"
    path = reflections_dir() / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(with_frontmatter(f"# Reflection {period}\n\n{body}\n", {"tags": ["hi", "reflection"], "period": period}))
    journal.record_event("reflection", f"wrote [[hi/reflections/{name}]]")
    return path


def consolidate_memory() -> bool:
    """Merge duplicates/stale items in memory.md. Keeps a copy of the old file; refuses a result that looks like data loss."""
    old = memory.read_memory()
    if sum(1 for line in old.splitlines() if line.startswith("- ")) < CONSOLIDATE_AT_LINES:
        return False
    new = invoke_with_retry(get_tier_model("sonnet"), [HumanMessage(_CONSOLIDATE_PROMPT.format(memory=old))]).strip()
    new = re.sub(r"^```(?:markdown)?\n|\n```$", "", new)
    if not new.startswith("---") or "## " not in new or len(new) < MIN_KEPT_FRACTION * len(old):
        return False
    history = memory.memory_path().parent / "history"
    history.mkdir(parents=True, exist_ok=True)
    (history / f"memory-{datetime.now():%Y%m%d-%H%M%S}.md").write_text(old)
    memory.memory_path().write_text(new + "\n")
    journal.record_event("memory consolidated", "merged duplicates and stale items; previous version kept in hi/memory/history/")
    return True


def latest_reflection() -> str:
    notes = sorted(reflections_dir().glob("*.md")) if reflections_dir().exists() else []
    return notes[-1].read_text() if notes else ""


def latest_open_loops(max_chars: int = 600) -> str:
    notes = sorted(reflections_dir().glob("*.md")) if reflections_dir().exists() else []
    if not notes:
        return ""
    match = re.search(r"## Open loops\n(.*?)(?:\n## |\Z)", notes[-1].read_text(), re.DOTALL)
    loops = match.group(1).strip() if match else ""
    return "" if loops.lower().startswith("none") else loops[:max_chars]


def maybe_reflect_yesterday() -> None:
    """Start a background reflection on yesterday if there is a journal for it and no reflection yet."""
    global _running
    if not config.REFLECTION:
        return
    yesterday = date.today() - timedelta(days=1)
    if (reflections_dir() / f"{yesterday.isoformat()}.md").exists() or not (journal.journal_dir() / f"{yesterday.isoformat()}.md").exists():
        return
    with _lock:
        if _running:
            return
        _running = True

    def work() -> None:
        global _running
        try:
            reflect(1, yesterday)
            consolidate_memory()
        except Exception:
            pass
        finally:
            _running = False

    threading.Thread(target=work, daemon=True).start()
