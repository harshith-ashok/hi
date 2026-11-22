"""Chat sessions: named conversations, kept as notes in the vault.

    <vault>/hi/sessions/<id>.md      frontmatter: id, title, created, updated, pinned, archived, turns, title_auto

The turns themselves are in the transcript (hi/memory/transcript.py), tagged with the session id; this module holds
only what a session list needs. A session's title starts as the first words of its first question and is replaced by a
short model-written title once the first answer exists, unless you have renamed it yourself.
"""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import hi.config as config
from hi.core import jobs
from hi.memory import transcript
from hi.memory.frontmatter import dump_frontmatter, parse_frontmatter

log = logging.getLogger(__name__)

_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{4}")
TITLE_WORDS = 7
TITLE_CHARS = 80
DEFAULT_TITLE = "New chat"


@dataclass
class Session:
    id: str
    title: str = DEFAULT_TITLE
    created: str = ""
    updated: str = ""
    pinned: bool = False
    archived: bool = False
    turns: int = 0
    title_auto: bool = True  # False once you rename it: a model never overwrites your title
    head: str = ""  # the id of the newest turn on the branch that is showing ("" = the newest turn written)


def sessions_dir() -> Path:
    return config.VAULT_PATH / "hi" / "sessions"


def valid_id(session_id: str) -> bool:
    return bool(_ID.fullmatch(session_id))


def _clean_title(text: str) -> str:
    line = re.sub(r"\s+", " ", re.sub(r"[`*_#>\[\]]", "", text)).strip(" -:\"'")
    return line[:TITLE_CHARS] or DEFAULT_TITLE


def auto_title(ask: str) -> str:
    """The first words of a question, as a provisional title."""
    words = re.sub(r"\s+", " ", ask).strip().split(" ")
    return _clean_title(" ".join(words[:TITLE_WORDS]) + ("…" if len(words) > TITLE_WORDS else ""))


def _path(session_id: str) -> Path:
    return sessions_dir() / f"{session_id}.md"


def _write(s: Session) -> None:
    fields = {
        "id": s.id, "title": _clean_title(s.title), "created": s.created, "updated": s.updated,
        "pinned": str(s.pinned).lower(), "archived": str(s.archived).lower(), "turns": str(s.turns),
        "title_auto": str(s.title_auto).lower(), "tags": ["hi", "session"],
    }
    if s.head:
        fields["head"] = s.head
    path = _path(s.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(f"{dump_frontmatter(fields)}\n")
    tmp.replace(path)


def _load(path: Path) -> Session | None:
    try:
        fields, _ = parse_frontmatter(path.read_text())
    except OSError:
        return None
    if not valid_id(str(fields.get("id", ""))):
        return None
    return Session(
        id=str(fields["id"]), title=str(fields.get("title") or DEFAULT_TITLE), created=str(fields.get("created", "")),
        updated=str(fields.get("updated", "")), pinned=fields.get("pinned") == "true",
        archived=fields.get("archived") == "true", turns=int(str(fields.get("turns", "0")) or 0),
        title_auto=fields.get("title_auto") != "false", head=str(fields.get("head", "")),
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def create(title: str = "") -> Session:
    s = Session(id=new_id(), title=_clean_title(title) if title.strip() else DEFAULT_TITLE, created=_now(), updated=_now(),
                title_auto=not title.strip())
    _write(s)
    return s


def get(session_id: str) -> Session | None:
    return _load(_path(session_id)) if valid_id(session_id) else None


EMPTY_GRACE_S = 600  # an untitled session with no turns is hidden once it is older than this


def _abandoned(s: Session) -> bool:
    """A chat that was created and never used: nothing in it and no name given."""
    try:
        age = (datetime.now() - datetime.fromisoformat(s.created)).total_seconds()
    except ValueError:
        return False
    return s.turns == 0 and s.title_auto and age > EMPTY_GRACE_S


def list_sessions(include_archived: bool = False) -> list[Session]:
    """Pinned first, then most recently used. Abandoned empty chats are left out."""
    folder = sessions_dir()
    found = [s for p in folder.glob("*.md") if (s := _load(p)) and (include_archived or not s.archived) and not _abandoned(s)] if folder.exists() else []
    found.sort(key=lambda s: s.updated, reverse=True)
    return sorted(found, key=lambda s: not s.pinned)  # a stable sort: pinned first, each group newest first


def update(session_id: str, title: str | None = None, pinned: bool | None = None, archived: bool | None = None) -> Session | None:
    s = get(session_id)
    if s is None:
        return None
    if title is not None and title.strip():
        s.title, s.title_auto = _clean_title(title), False
    if pinned is not None:
        s.pinned = pinned
    if archived is not None:
        s.archived = archived
    _write(s)
    return s


def delete(session_id: str) -> bool:
    """Remove the session and its turns."""
    if get(session_id) is None:
        return False
    _path(session_id).unlink(missing_ok=True)
    transcript.delete_session(session_id)
    return True


def head_of(session_id: str) -> str:
    """The id of the turn a new turn in this session follows: the session's head, else (a chat from before turns had ids)
    its newest turn, else ""."""
    if not valid_id(session_id):
        return ""
    s = get(session_id)
    if s is not None and s.head:
        return s.head
    path = transcript.session_path(session_id)
    return path[-1]["id"] if path else ""


def touch(session_id: str, ask: str, head: str = "") -> Session | None:
    """Record a turn in `session_id` (created if the id is valid but unknown): bump its count and time, make `head` (the
    turn's id) the head, and give it a provisional title from the first question. Returns None for an invalid id."""
    if not valid_id(session_id):
        return None
    s = get(session_id) or Session(id=session_id, created=_now())
    s.turns += 1
    s.updated = _now()
    if head:
        s.head = head
    if s.title_auto and s.title == DEFAULT_TITLE:
        s.title = auto_title(ask)
    _write(s)
    return s


def set_generated_title(session_id: str, title: str) -> bool:
    """Replace the provisional title, unless the user has set one."""
    s = get(session_id)
    if s is None or not s.title_auto or not title.strip():
        return False
    s.title = _clean_title(title)
    _write(s)
    return True


_TITLE_PROMPT = ("Write a title of at most six words for this conversation. Plain words, no quotes, no trailing "
                 "punctuation. Reply with the title only.\n\nUser: {ask}\n\nAssistant: {answer}")


def generate_title(ask: str, answer: str) -> str:
    from langchain_core.messages import HumanMessage

    from hi.llm.registry import get_tier_model_fast
    from hi.llm.resilience import invoke_with_retry

    reply = invoke_with_retry(get_tier_model_fast("haiku"), [HumanMessage(_TITLE_PROMPT.format(ask=ask[:600], answer=answer[:900]))])
    return _clean_title(reply.strip().splitlines()[0]) if reply.strip() else ""


def retitle_async(session_id: str, ask: str, answer: str, make=generate_title) -> None:
    """Give a new session a model-written title in the background. A failure keeps the provisional title."""
    def work() -> None:
        title = make(ask, answer)
        if title and title != DEFAULT_TITLE:
            set_generated_title(session_id, title)

    jobs.run_background(f"title-{session_id}", work)
