"""One call that writes a finished turn to every log.

Callers build a TurnRecord and call `record_turn`; they don't know which logs exist. Each sink is
isolated: one that fails (disk full, a bad path) is logged and skipped, and never breaks the turn
or stops the other sinks.

    transcript   always: the raw record, kept whole (also for failed turns)
    conversation only when there is an answer, and not for background runs: the readable Markdown log
    journal      an activity entry for an answered turn, or an "error" event for a failed one
    extraction   only for an answered turn you were part of: learn durable facts in the background
    session      the chat session the turn belongs to: its count, time and title
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from hi.core.runpolicy import BACKGROUND_ORIGINS
from hi.memory import extraction, journal, sessions, transcript, vault

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


def _transcript(rec: TurnRecord) -> None:
    transcript.record_turn(
        rec.persona, rec.tier, rec.ask, rec.answer, rec.tools, rec.seconds, rec.plan, rec.detail or rec.error, rec.origin,
        rec.session, rec.visual,
    )


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
    s = sessions.touch(rec.session, rec.ask)
    if s is not None and s.turns == 1 and s.title_auto and rec.answer and not rec.error:
        sessions.retitle_async(rec.session, rec.ask, rec.answer)


SINKS: list[Callable[[TurnRecord], None]] = [_transcript, _conversation, _journal, _extraction, _session]


def record_turn(rec: TurnRecord) -> None:
    for sink in SINKS:
        try:
            sink(rec)
        except Exception:  # boundary: a failing log must not break the turn or the other logs
            log.exception("could not record turn in %s", sink.__name__.lstrip("_"))
