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

import hashlib
import json
import uuid
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
    turn_id: str = "", parent: str = "",
) -> str:
    """Append one turn and return its id. tools: [{"name", "args" (JSON string), "result"}] in call order, kept in full.

    `parent` is the id of the turn this one follows in its session ("" for the first). Turns of one session form a tree:
    a second attempt at the same question is a sibling with the same parent, and the session's `head` says which branch
    is showing."""
    turn_id = turn_id or uuid.uuid4().hex[:12]
    entry = {
        "id": turn_id, "parent": parent,
        "time": datetime.now().isoformat(timespec="seconds"),
        "persona": persona, "tier": tier, "plan": plan, "seconds": round(seconds, 2),
        "ask": ask, "tools": tools, "answer": answer, "error": error, "origin": origin,
        "session": session, "visual": visual,
    }
    path = _day_file(date.today())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return turn_id


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


def _counts_as_history(entry: dict) -> bool:
    # A turn that ended by showing a form or asking a question has tools but no answer text: it still belongs in
    # the history, or the assistant could not see what it had asked when the reply comes back.
    failed = entry.get("error") not in ("", None, "stopped")  # a stopped turn is not a failed one
    spoke = entry.get("answer") or (entry.get("tools") and not failed)
    return bool(spoke) and entry.get("origin") not in BACKGROUND_ORIGINS


def _recent_entries(limit: int, session: str = "", head: str = "") -> list[dict]:
    """The newest `limit` answered turns of `session` (on the branch ending at `head`), oldest first. With no session
    ("") these are the turns that belong to no session, from the last HISTORY_DAYS days."""
    if session:
        return [e for e in session_path(session, head, SESSION_DAYS) if _counts_as_history(e)][-limit:]
    found: deque[dict] = deque(maxlen=limit)
    for offset in range(HISTORY_DAYS - 1, -1, -1):
        for entry in _entries_on(date.today() - timedelta(days=offset)):
            if _counts_as_history(entry) and entry.get("session", "") == "":
                found.append(entry)
    return list(found)


def _legacy_id(entry: dict) -> str:
    """A stable id for a turn written before turns had ids: its time plus a hash of its question."""
    return f"{entry.get('time', '')}-{hashlib.sha1(str(entry.get('ask', '')).encode()).hexdigest()[:6]}"


def _session_entries(session: str, days: int | None = None) -> list[dict]:
    """Every turn of `session` as written, oldest first, each with an `id` and a `parent`. Turns from before ids existed
    get a made-up id and are chained one after another."""
    found: list[dict] = []
    previous = ""
    if not transcript_dir().exists():
        return found
    oldest = date.today() - timedelta(days=days) if days else None
    for path in sorted(transcript_dir().glob("*.jsonl")):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if oldest and day < oldest:
            continue
        for entry in _entries_on(day):
            if entry.get("session", "") != session:
                continue
            if not entry.get("id"):
                entry = {**entry, "id": _legacy_id(entry), "parent": previous}
            found.append(entry)
            previous = entry["id"]
    return found


def session_path(session: str, head: str = "", days: int | None = None) -> list[dict]:
    """The turns on the branch of `session` that ends at `head`, oldest first. With no `head` (or an unknown one) the
    newest turn is the head. Other branches (earlier attempts at a question) are not included."""
    entries = _session_entries(session, days)
    by_id = {e["id"]: e for e in entries}
    node = by_id.get(head) or (entries[-1] if entries else None)
    path: list[dict] = []
    seen: set[str] = set()
    while node is not None and node["id"] not in seen:
        seen.add(node["id"])
        path.append(node)
        node = by_id.get(node.get("parent", ""))
    return path[::-1]


def session_turns(session: str, head: str = "") -> list[dict]:
    """Every turn on the showing branch of `session`, oldest first (answered or not), for showing the conversation again."""
    return session_path(session, head)


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


def _assistant_text(entry: dict, limit: int = ANSWER_CHARS) -> str:
    answer = _clip(entry.get("answer") or "", limit)
    notes = [n for t in entry.get("tools", []) if (n := _waiting_note(t))]
    if notes and not answer:
        answer = "[" + "; ".join(notes) + "]"
    names = [t["name"] for t in entry.get("tools", [])]
    if not names:
        return answer
    return f"{answer}\n\n[tools used this turn: {_clip(', '.join(names), TOOLS_CHARS)}]"


def history(turns: int = HISTORY_TURNS, session: str = "", head: str = "") -> list[dict]:
    """The latest exchanges of `session` (up to `head`) as chat messages, ready to go in front of a new user message."""
    messages: list[dict] = []
    for entry in _recent_entries(turns, session, head):
        messages.append({"role": "user", "content": _clip(entry["ask"], ASK_CHARS)})
        messages.append({"role": "assistant", "content": _assistant_text(entry)})
    return messages


# --- a history that fits the model's context window -------------------------------------------------------------------

ANSWER_RESERVE_TOKENS = 4096    # left free for the model's reply
PROMPT_OVERHEAD_TOKENS = 7000   # the system prompt, tool definitions and vault context: a rough allowance, not measured


def estimate_tokens(text: str) -> int:
    """A cheap token count (about three characters a token, a little generous for code). No tokenizer dependency."""
    return len(text) // 3 + 1


def history_budget(message: str) -> int:
    """Tokens left for earlier turns once the prompt, this message (with any attached context) and the reply are paid for."""
    return config.CONTEXT_TOKENS - ANSWER_RESERVE_TOKENS - PROMPT_OVERHEAD_TOKENS - estimate_tokens(message)


def history_within(budget_tokens: int, session: str, head: str = "") -> tuple[list[dict], int]:
    """The newest turns of `session` (on the branch ending at `head`) that fit in `budget_tokens`, as chat messages, and
    how many earlier turns had to be left out. Oldest turns go first; the newest exchange is always kept. A turn is
    clipped only when it alone is bigger than a quarter of the budget (and never below the usual per-turn limits)."""
    entries = [e for e in session_path(session, head, SESSION_DAYS) if _counts_as_history(e)]
    cap = max(budget_tokens, 0) // 4 * 3  # characters
    kept: list[list[dict]] = []
    used = 0
    for entry in reversed(entries):
        pair = [
            {"role": "user", "content": _clip(entry["ask"], max(ASK_CHARS, cap))},
            {"role": "assistant", "content": _assistant_text(entry, max(ANSWER_CHARS, cap))},
        ]
        cost = sum(estimate_tokens(m["content"]) for m in pair)
        if kept and used + cost > budget_tokens:
            break
        kept.append(pair)
        used += cost
    return [m for pair in reversed(kept) for m in pair], len(entries) - len(kept)
