"""One call that writes a finished turn to every log.

Callers build a TurnRecord and call `record_turn`; they don't know which logs exist. Each sink is
isolated: one that fails (disk full, a bad path) is logged and skipped, and never breaks the turn
or stops the other sinks.

    transcript   always: the raw record, kept whole (also for failed turns)
    conversation only when there is an answer, and not for background runs: the readable Markdown log
    journal      an activity entry for an answered turn, or an "error" event for a failed one
    extraction   only for an answered turn you were part of: learn durable facts in the background
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from hi.core.runpolicy import BACKGROUND_ORIGINS
from hi.memory import extraction, journal, transcript, vault

log = logging.getLogger(__name__)


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


def _transcript(rec: TurnRecord) -> None:
    transcript.record_turn(
        rec.persona, rec.tier, rec.ask, rec.answer, rec.tools, rec.seconds, rec.plan, rec.detail or rec.error, rec.origin,
    )


def _conversation(rec: TurnRecord) -> None:
    if rec.answer and rec.origin not in BACKGROUND_ORIGINS:
        vault.log_conversation(rec.persona, rec.ask, rec.answer)


def _journal(rec: TurnRecord) -> None:
    if rec.error:
        journal.record_event("error", f"{rec.ask[:120]} — {rec.error}")
    elif rec.answer:
        journal.record_turn(rec.persona, rec.tier, rec.ask, rec.answer, rec.tools, rec.seconds, rec.origin)


def _extraction(rec: TurnRecord) -> None:
    if rec.answer and not rec.error and rec.origin not in BACKGROUND_ORIGINS:
        extraction.extract_async(rec.ask, rec.answer, [t["name"] for t in rec.tools])


SINKS: list[Callable[[TurnRecord], None]] = [_transcript, _conversation, _journal, _extraction]


def record_turn(rec: TurnRecord) -> None:
    for sink in SINKS:
        try:
            sink(rec)
        except Exception:  # boundary: a failing log must not break the turn or the other logs
            log.exception("could not record turn in %s", sink.__name__.lstrip("_"))
