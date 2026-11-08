"""Memory extraction: after each turn, a small model pulls out durable things
worth remembering (preferences, facts about the user, projects, people,
decisions) and appends them to one Markdown file in the vault:

    <VAULT_PATH>/hi/memory/memory.md

It runs in a background thread after the answer is already sent, so it never
adds latency. It only sees what the user said, the assistant's answer and the
names of the tools used, never raw tool output, so a web page or file cannot
instruct it to "remember" something. Secrets are filtered out. Edit or delete
any line by hand in Obsidian; hi/reflection_agent.py consolidates the file.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import date
from pathlib import Path

from langchain_core.messages import HumanMessage

import hi.config as config
from hi import journal
from hi.frontmatter import with_frontmatter
from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model_fast

KINDS = ("Preferences", "Facts", "Projects", "People", "Decisions")
MIN_ASK_WORDS = 4
_SECRET = re.compile(r"password|passwd|secret|api[ _-]?key|token|\botp\b|cvv|credit card|[A-Za-z0-9_\-]{28,}", re.IGNORECASE)

_PROMPT = """You maintain a long-term memory about the user of a personal assistant.
From this exchange, extract ONLY durable things worth remembering for weeks: a stated preference or habit,
a fact about the user, their projects, people in their life, or a decision they made.
Rules: the user must have said or clearly confirmed it. No small talk, no one-off questions, no
speculation, no secrets (keys, tokens, passwords). Skip anything already in Existing memory.
Each item is one short, self-contained sentence in the third person ("Prefers ...", "Is building ...").
Reply with ONLY a JSON list like [{{"kind": "Preferences", "text": "..."}}], kinds: {kinds}. Reply [] if nothing qualifies.

Existing memory:
{existing}

User said: {ask}
Tools used: {tools}
Assistant answered: {answer}"""


def memory_path() -> Path:
    return config.VAULT_PATH / "hi" / "memory" / "memory.md"


def read_memory(max_chars: int | None = None) -> str:
    path = memory_path()
    text = path.read_text() if path.exists() else ""
    return text[-max_chars:] if max_chars else text


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _parse(reply: str) -> list[dict]:
    match = re.search(r"\[.*\]", reply, re.DOTALL)
    try:
        items = json.loads(match.group(0)) if match else []
    except json.JSONDecodeError:
        return []
    return [i for i in items if isinstance(i, dict) and i.get("kind") in KINDS and isinstance(i.get("text"), str)]


def forget_line(line: str) -> bool:
    """Remove one bullet from the memory file (matched exactly); True if it was there."""
    path = memory_path()
    lines = read_memory().splitlines()
    kept = [l for l in lines if l.strip() != line.strip() or not l.lstrip().startswith("- ")]
    if len(kept) == len(lines):
        return False
    path.write_text("\n".join(kept) + "\n")
    return True


def add_items(items: list[dict]) -> list[dict]:
    """Append new items under their kind heading; returns the ones actually added."""
    path = memory_path()
    existing = read_memory()
    known = {_normalize(line) for line in existing.splitlines()}
    added = []
    for item in items:
        text = item["text"].strip().rstrip(".")
        if not text or _SECRET.search(text) or any(_normalize(text) in k for k in known):
            continue
        added.append({"kind": item["kind"], "text": text})
        known.add(_normalize(text))
    if not added:
        return []

    path.parent.mkdir(parents=True, exist_ok=True)
    if not existing:
        existing = with_frontmatter("", {"tags": ["hi", "memory"]})
    today = date.today().isoformat()
    for item in added:
        line = f"- {item['text']} ({today}, [[hi/journal/{today}]])"
        heading = f"## {item['kind']}"
        if heading in existing:
            head, _, rest = existing.partition(heading + "\n")
            section, sep, tail = rest.partition("\n## ")
            existing = f"{head}{heading}\n{section.rstrip(chr(10))}\n{line}\n{sep}{tail}" if sep else f"{head}{heading}\n{section.rstrip(chr(10))}\n{line}\n"
        else:
            existing = f"{existing.rstrip(chr(10))}\n\n{heading}\n{line}\n"
    path.write_text(existing)
    return added


def extract(ask: str, answer: str, tool_names: list[str]) -> list[dict]:
    if len(ask.split()) < MIN_ASK_WORDS and not tool_names:
        return []
    prompt = _PROMPT.format(
        kinds=", ".join(KINDS), existing=read_memory(3000) or "(empty)", ask=ask[:1200],
        tools=", ".join(tool_names) or "none", answer=answer[:1200],
    )
    reply = invoke_with_retry(get_tier_model_fast("haiku"), [HumanMessage(prompt)])
    return add_items(_parse(reply))


def extract_async(ask: str, answer: str, tool_names: list[str]) -> None:
    """Fire and forget: failures are dropped, never surfaced to the user."""
    if not config.MEMORY_EXTRACTION:
        return

    def work() -> None:
        try:
            if added := extract(ask, answer, tool_names):
                journal.record_event("remembered", "; ".join(f"[{i['kind']}] {i['text']}" for i in added))
        except Exception:
            pass

    threading.Thread(target=work, daemon=True).start()
