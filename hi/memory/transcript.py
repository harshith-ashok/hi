"""The raw transcript: everything that happens in a turn, kept whole, one JSON line per turn.

    <VAULT_PATH>/hi/transcripts/YYYY-MM-DD.jsonl

Unlike the conversation log (hi/vault.py: user and assistant text, for reading) and the journal
(hi/journal.py: clipped one-liners), nothing is shortened here: the full question, the route, every
tool call with its complete arguments and result, the answer, errors and timings. It is the record
to dig through when something went wrong.

It is also what makes the assistant remember the conversation: `history()` returns the last few
exchanges, and the server passes them to the agent ahead of each new message, so "what are the
changes that need to be committed?" is read in light of "I'm working on the hi project".
Plain files, no index. Kept out of the vault search because it only reads .md notes.
"""

from __future__ import annotations

import json
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path

import hi.config as config

HISTORY_TURNS = 8        # exchanges handed to the agent with each new message
HISTORY_DAYS = 3         # how far back to look for them
ASK_CHARS = 1500         # per question, in the history only; the file keeps everything
ANSWER_CHARS = 2000      # per answer, in the history only
TOOLS_CHARS = 300        # how much of the tool trail is shown with an answer


def transcript_dir() -> Path:
    return config.VAULT_PATH / "hi" / "transcripts"


def _day_file(day: date) -> Path:
    return transcript_dir() / f"{day.isoformat()}.jsonl"


def record_turn(
    persona: str, tier: str, ask: str, answer: str, tools: list[dict], seconds: float,
    plan: bool = False, error: str = "",
) -> None:
    """tools: [{"name", "args" (JSON string), "result"}] in call order, kept in full."""
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "persona": persona, "tier": tier, "plan": plan, "seconds": round(seconds, 2),
        "ask": ask, "tools": tools, "answer": answer, "error": error,
    }
    path = _day_file(date.today())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _recent_entries(limit: int) -> list[dict]:
    """The newest `limit` answered turns, oldest first."""
    found: deque[dict] = deque(maxlen=limit)
    for offset in range(HISTORY_DAYS - 1, -1, -1):
        path = _day_file(date.today() - timedelta(days=offset))
        if not path.exists():
            continue
        for line in path.read_text(errors="ignore").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("answer"):
                found.append(entry)
    return list(found)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " …[clipped]"


def _assistant_text(entry: dict) -> str:
    answer = _clip(entry["answer"], ANSWER_CHARS)
    names = [t["name"] for t in entry.get("tools", [])]
    if not names:
        return answer
    return f"{answer}\n\n[tools used this turn: {_clip(', '.join(names), TOOLS_CHARS)}]"


def history(turns: int = HISTORY_TURNS) -> list[dict]:
    """The latest exchanges as chat messages, ready to go in front of a new user message."""
    messages: list[dict] = []
    for entry in _recent_entries(turns):
        messages.append({"role": "user", "content": _clip(entry["ask"], ASK_CHARS)})
        messages.append({"role": "assistant", "content": _assistant_text(entry)})
    return messages
