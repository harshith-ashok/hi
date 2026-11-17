"""Run scheduled tasks. `tick` is called every 30 seconds by a background job.

For each enabled schedule it works out which slots have come due since the last one it handled:

  - the newest due slot runs, if it is within the schedule's `catch_up` window (a laptop that slept through 8:00 still
    gives you the brief at 8:40; one that slept all day does not give you yesterday's)
  - older due slots are recorded as `missed`, once, so waking up never floods you
  - each slot is claimed before it runs, so it runs at most once

A reminder is delivered as written, with no model. A task is run by the agent under the unattended policy, in the
single background worker, and its result goes through `deliver`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import datetime
from typing import Callable

import hi.config as config
from hi.automation import context_pack, limits, profiles
from hi.automation.deliver import Delivery, deliver, headline_from
from hi.automation.worker import get_worker
from hi.core.runpolicy import UNATTENDED, RunPolicy
from hi.llm import registry
from hi.memory import schedules
from hi.memory.schedules import Schedule

log = logging.getLogger(__name__)

TICK_S = 30
RunTurn = Callable[..., object]
_run_turn: RunTurn | None = None


def configure(run_turn: RunTurn) -> None:
    """Called once at startup with the server's headless runner."""
    global _run_turn
    _run_turn = run_turn


def policy_for(s: Schedule) -> RunPolicy:
    prof = profiles.profile("schedule")
    return replace(
        UNATTENDED, allowed=UNATTENDED.allowed | frozenset(s.allow), allow_web=s.allow_web,
        allow_screen="screen" in s.context and registry.is_local(s.tier),
        max_tool_calls=config.MAX_BACKGROUND_TOOL_CALLS, timeout_s=prof.timeout_s,
    )


def _slot(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _popup(s: Schedule, proposals: tuple[str, ...]) -> str:
    return {"notify": "yes", "report": "approvals" if proposals else "no", "silent": "no"}[s.deliver]


def run_reminder(s: Schedule, slot: str, deliver_fn=deliver) -> str:
    out = deliver_fn(Delivery(headline=s.prompt, kind="reminder", origin="schedule", dedupe_key=f"schedule:{s.id}:{slot}"))
    schedules.finish(s.id, slot, "done" if out.status != "error" else "failed", error="" if out.status != "error" else "could not deliver")
    return "done"


def run_task(s: Schedule, slot: str, run_turn: RunTurn, deliver_fn=deliver, now: datetime | None = None) -> str:
    """Run one task slot to completion and deliver the result. Returns the final status."""
    at = now.timestamp() if now else None
    reason = limits.check_run(at)
    if reason:
        schedules.finish(s.id, slot, "skipped", error=reason)
        deliver_fn(Delivery(headline=f"Skipped {s.id}: {reason}", kind="failure", origin="schedule",
                            dedupe_key=f"skip:{s.id}:{slot[:13]}"))
        return "skipped"
    tier = limits.choose_tier(s.tier, at)
    if tier is None:
        schedules.finish(s.id, slot, "skipped", error="the daily limit on hosted models is used up and no local model is set")
        deliver_fn(Delivery(headline=f"Skipped {s.id}: the daily hosted-model limit is used up", kind="failure",
                            origin="schedule", dedupe_key=f"skip:{s.id}:{slot[:10]}"))
        return "skipped"
    pack = context_pack.build(set(s.context), s.prompt, tier, now)
    result = run_turn(s.prompt, origin="schedule", policy=policy_for(s), persona=s.persona, tier=tier,
                      context=pack.text, profile="schedule")
    if result.error or not result.answer:
        error = result.error or "the run produced no answer"
        schedules.finish(s.id, slot, "failed", error=error)
        deliver_fn(Delivery(headline=f"{s.id} failed: {error}", kind="failure", origin="schedule",
                            dedupe_key=f"fail:{s.id}:{slot}"))
        return "failed"
    out = deliver_fn(Delivery(
        headline=headline_from(result.answer) or f"{s.id} finished", body=result.answer, kind="digest", origin="schedule",
        dedupe_key=f"schedule:{s.id}:{slot}", proposals=tuple(result.proposals), popup=_popup(s, tuple(result.proposals)),
        notes=tuple(pack.notes + result.notes),
    ))
    schedules.finish(s.id, slot, "done", report=out.report_id)
    return "done"


def _finish_once(s: Schedule) -> None:
    if s.when.lower().startswith("once"):
        schedules.set_enabled(s.id, False)


def _handle(s: Schedule, slot: str, run_turn: RunTurn, deliver_fn, now: datetime | None = None) -> None:
    try:
        if s.kind == "reminder":
            run_reminder(s, slot, deliver_fn)
        else:
            run_task(s, slot, run_turn, deliver_fn, now)
    except Exception as e:  # boundary: a schedule's failure is recorded and reported, never raised into the worker
        log.exception("schedule %s failed", s.id)
        schedules.finish(s.id, slot, "failed", error=str(e) or type(e).__name__)
        deliver_fn(Delivery(headline=f"{s.id} failed: {e}", kind="failure", origin="schedule", dedupe_key=f"fail:{s.id}:{slot}"))
    finally:
        _finish_once(s)


def tick(now: datetime | None = None, run_turn: RunTurn | None = None, submit=None, deliver_fn=deliver) -> list[str]:
    """Handle everything due at `now`. Returns the slots that were started. `submit(key, fn)` defaults to the
    background worker; tests pass one that runs `fn` at once."""
    now = now or datetime.now()
    run_turn = run_turn or _run_turn
    submit = submit or get_worker().submit
    started: list[str] = []
    for s in schedules.load_all():
        if not s.enabled:
            continue
        last = schedules.last_slot(s.id)
        base = last or (datetime.fromisoformat(s.created) if s.created else now)  # a new schedule starts from its creation
        fires = schedules.fires_between(s, base, now)
        if not fires:
            continue
        *older, newest = fires
        for moment in older:
            if schedules.claim(s.id, _slot(moment)):
                schedules.finish(s.id, _slot(moment), "missed", error="not run: a later slot was due")
        slot = _slot(newest)
        if (now - newest).total_seconds() > s.catch_up_s:
            if schedules.claim(s.id, slot):
                schedules.finish(s.id, slot, "missed", error=f"not run: more than {s.catch_up_s // 60} minutes late")
            _finish_once(s)
            continue
        if not schedules.claim(s.id, slot):
            continue
        if s.kind == "task" and run_turn is None:
            schedules.finish(s.id, slot, "failed", error="the background runner is not started")
            continue
        started.append(slot)
        if s.kind == "reminder":  # no model: deliver now, do not wait behind a long run
            _handle(s, slot, run_turn, deliver_fn, now)
        else:
            submit(f"schedule:{s.id}:{slot}", lambda s=s, slot=slot: _handle(s, slot, run_turn, deliver_fn, now))
    return started


def run_now(schedule_id: str, submit=None, deliver_fn=deliver) -> str:
    """Start a schedule now, outside its timetable. Returns a sentence about what happened."""
    s = schedules.load(schedule_id)
    if s is None:
        return f"No schedule called '{schedule_id}'."
    if s.kind == "task" and _run_turn is None:
        return "The background runner is not started (the backend is not fully up)."
    slot = f"manual-{int(time.time())}"
    schedules.claim(s.id, slot)
    submit = submit or get_worker().submit
    queued = submit(f"schedule:{s.id}:{slot}", lambda: _handle_manual(s, slot, deliver_fn))
    return f"Started '{s.id}'." if queued else f"'{s.id}' is already running."


def _handle_manual(s: Schedule, slot: str, deliver_fn) -> None:
    try:
        if s.kind == "reminder":
            run_reminder(s, slot, deliver_fn)
        else:
            run_task(s, slot, _run_turn, deliver_fn)
    except Exception as e:  # boundary, as in _handle
        log.exception("schedule %s failed", s.id)
        schedules.finish(s.id, slot, "failed", error=str(e) or type(e).__name__)


def start(run_turn: RunTurn) -> None:
    """Called by the lifespan: remember the runner and tick every TICK_S seconds."""
    from hi.core import jobs

    configure(run_turn)
    jobs.every("scheduler", TICK_S, tick)
