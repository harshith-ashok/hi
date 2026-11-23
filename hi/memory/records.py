"""One call that writes a finished turn to every log.

Callers build a TurnRecord and call `record_turn`; they don't know which logs exist. Each sink is
isolated: one that fails (disk full, a bad path) is logged and skipped, and never breaks the turn
or stops the other sinks.

    transcript   always: the raw record, kept whole (also for failed turns)
    conversation only when there is an answer, and not for background runs: the readable Markdown log
    journal      an activity entry for an answered turn, or an "error" event for a failed one
    extraction   only for an answered turn you were part of: learn durable facts in the background
    artifacts    pages, documents and diagrams the answer marked with `artifact`, saved as versions
    session      the chat session the turn belongs to: its count, time and title

An incognito chat (hi/memory/sessions.py) skips conversation, journal and extraction.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Callable

from hi.core.runpolicy import BACKGROUND_ORIGINS
from hi.memory import artifacts, extraction, journal, sessions, transcript, vault

log = logging.getLogger(__name__)

STOPPED = "stopped"  # the error text of a turn the user stopped; not a failure


@dataclass
class TurnRecord:
    persona: str
    tier: str
    ask: str
    answer: str = ""
    tools: list[dict] = field(default_factory=list)  # [{"name", "args" (JSON string), "result"}]
    seconds: float = 0.0
    plan: bool = False
    error: str = ""  # the user-facing error message, or "" for a turn that worked
    detail: str = ""  # the raw exception text for the transcript, when it differs from `error`
    origin: str = "ui"  # ui | island | voice | schedule | heartbeat | drop
    session: str = ""  # the chat session this turn belongs to ("" for none)
    visual: str = ""  # a mermaid diagram drawn for the answer
    id: str = ""  # this turn's id ("" = made when it is written)
    parent: str | None = None  # the id of the turn it follows in its session; None = the session's current head, "" = none
    artifacts: list[dict] = field(default_factory=list)  # filled in when the turn is recorded: {slug, title, kind, version}


def _transcript(rec: TurnRecord) -> None:
    transcript.record_turn(
        rec.persona, rec.tier, rec.ask, rec.answer, rec.tools, rec.seconds, rec.plan, rec.detail or rec.error, rec.origin,
        rec.session, rec.visual, rec.id, rec.parent,
    )


def _artifacts(rec: TurnRecord) -> None:
    if rec.session and rec.answer and not rec.error and rec.origin not in BACKGROUND_ORIGINS:
        rec.artifacts = [artifacts.save(rec.session, rec.id, a) for a in artifacts.extract(rec.answer)]


def _conversation(rec: TurnRecord) -> None:
    if rec.answer and rec.origin not in BACKGROUND_ORIGINS:
        vault.log_conversation(rec.persona, rec.ask, rec.answer)


def _journal(rec: TurnRecord) -> None:
    if rec.error == STOPPED:
        return
    if rec.error:
        journal.record_event("error", f"{rec.ask[:120]} — {rec.error}")
    elif rec.answer:
        journal.record_turn(rec.persona, rec.tier, rec.ask, rec.answer, rec.tools, rec.seconds, rec.origin)


def _extraction(rec: TurnRecord) -> None:
    if rec.answer and not rec.error and rec.origin not in BACKGROUND_ORIGINS:
        extraction.extract_async(rec.ask, rec.answer, [t["name"] for t in rec.tools])


def _session(rec: TurnRecord) -> None:
    if not rec.session:
        return
    s = sessions.touch(rec.session, rec.ask, head=rec.id)
    if s is not None and s.turns == 1 and s.title_auto and rec.answer and not rec.error:
        sessions.retitle_async(rec.session, rec.ask, rec.answer)


SINKS: list[Callable[[TurnRecord], None]] = [_transcript, _artifacts, _conversation, _journal, _extraction, _session]


# Not written for an incognito chat: the readable log, the activity journal and what is learned about you.
PRIVATE_SKIPS = (_conversation, _journal, _extraction)


def record_turn(rec: TurnRecord) -> None:
    rec.id = rec.id or uuid.uuid4().hex[:12]
    if rec.parent is None:
        rec.parent = sessions.head_of(rec.session) if rec.session else ""
    chat = sessions.get(rec.session) if rec.session else None
    private = bool(chat and chat.incognito)  # an incognito chat is kept only as far as it needs to continue
    for sink in SINKS:
        if private and sink in PRIVATE_SKIPS:
            continue
        try:
            sink(rec)
        except Exception:  # boundary: a failing log must not break the turn or the other logs
            log.exception("could not record turn in %s", sink.__name__.lstrip("_"))
