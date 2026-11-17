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
from hi.core.runpolicy import BACKGROUND_ORIGINS

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
    plan: bool = False, error: str = "", origin: str = "", session: str = "", visual: str = "",
) -> None:
    """tools: [{"name", "args" (JSON string), "result"}] in call order, kept in full."""
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "persona": persona, "tier": tier, "plan": plan, "seconds": round(seconds, 2),
        "ask": ask, "tools": tools, "answer": answer, "error": error, "origin": origin,
        "session": session, "visual": visual,
    }
    path = _day_file(date.today())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


SESSION_DAYS = 90        # how far back a session's history is looked for (it may be resumed after weeks)


def _entries_on(day: date) -> list[dict]:
    try:
        lines = _day_file(day).read_text(errors="ignore").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            found.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return found


def _recent_entries(limit: int, session: str = "") -> list[dict]:
    """The newest `limit` answered turns of `session` ("" = turns that belong to no session), oldest first."""
    found: deque[dict] = deque(maxlen=limit)
    days = SESSION_DAYS if session else HISTORY_DAYS
    for offset in range(days - 1, -1, -1):
        for entry in _entries_on(date.today() - timedelta(days=offset)):
            # A turn that ended by showing a form or asking a question has tools but no answer text: it still belongs in
            # the history, or the assistant could not see what it had asked when the reply comes back.
            failed = entry.get("error") not in ("", None, "stopped")  # a stopped turn is not a failed one
            spoke = entry.get("answer") or (entry.get("tools") and not failed)
            if spoke and entry.get("origin") not in BACKGROUND_ORIGINS and entry.get("session", "") == session:
                found.append(entry)
    return list(found)


def session_turns(session: str) -> list[dict]:
    """Every turn of `session`, oldest first (answered or not), for showing the conversation again."""
    turns = []
    if not transcript_dir().exists():
        return turns
    for path in sorted(transcript_dir().glob("*.jsonl")):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        turns += [e for e in _entries_on(day) if e.get("session", "") == session]
    return turns


def delete_session(session: str) -> int:
    """Remove a session's turns from every day's file. Returns how many were removed."""
    removed = 0
    if not transcript_dir().exists():
        return removed
    for path in sorted(transcript_dir().glob("*.jsonl")):
        try:
            lines = path.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        keep = []
        for line in lines:
            try:
                drop = json.loads(line).get("session", "") == session
            except json.JSONDecodeError:
                drop = False
            removed += drop
            if not drop:
                keep.append(line)
        if len(keep) != len(lines):
            tmp = path.with_suffix(".tmp")
            tmp.write_text("".join(f"{line}\n" for line in keep))
            tmp.replace(path)
    return removed


def search_sessions(query: str, limit: int = 30) -> dict[str, str]:
    """{session id: a snippet around the match} for sessions whose questions or answers contain `query`."""
    needle, found = query.strip().lower(), {}
    if not needle or not transcript_dir().exists():
        return found
    for path in sorted(transcript_dir().glob("*.jsonl"), reverse=True):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        for entry in reversed(_entries_on(day)):
            sid = entry.get("session", "")
            if not sid or sid in found:
                continue
            for text in (entry.get("ask", ""), entry.get("answer", "")):
                at = text.lower().find(needle)
                if at >= 0:
                    found[sid] = ("…" if at > 40 else "") + text[max(0, at - 40): at + 80].replace("\n", " ")
                    break
            if len(found) >= limit:
                return found
    return found


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " …[clipped]"


def _waiting_note(tool: dict) -> str:
    """What a tool that waits for the user put on screen, in a line, for the history."""
    try:
        args = json.loads(tool.get("args") or "{}")
    except json.JSONDecodeError:
        return ""
    if tool.get("name") == "ask_user":
        return "asked the user: " + " | ".join(str(q) for q in (args.get("questions") or [])[:4])
    if tool.get("name") == "show_ui" and isinstance(args.get("ui"), (dict, list)):
        ui = args["ui"] if isinstance(args["ui"], dict) else {}
        return f"showed the user an interactive UI ({ui.get('title') or args.get('title') or ui.get('type', 'form')}) and waited for their response"
    return ""


def _assistant_text(entry: dict) -> str:
    answer = _clip(entry.get("answer") or "", ANSWER_CHARS)
    notes = [n for t in entry.get("tools", []) if (n := _waiting_note(t))]
    if notes and not answer:
        answer = "[" + "; ".join(notes) + "]"
    names = [t["name"] for t in entry.get("tools", [])]
    if not names:
        return answer
    return f"{answer}\n\n[tools used this turn: {_clip(', '.join(names), TOOLS_CHARS)}]"


def history(turns: int = HISTORY_TURNS, session: str = "") -> list[dict]:
    """The latest exchanges of `session` as chat messages, ready to go in front of a new user message."""
    messages: list[dict] = []
    for entry in _recent_entries(turns, session):
        messages.append({"role": "user", "content": _clip(entry["ask"], ASK_CHARS)})
        messages.append({"role": "assistant", "content": _assistant_text(entry)})
    return messages
