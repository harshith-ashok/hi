"""What the backend starts in the background when it boots. Explicit, so importing a module never
starts anything (MAKE.md, principle 3)."""

from __future__ import annotations

from datetime import date

from hi.core import jobs

_SUNDAY = 6
HOUR_S = 3600.0


def maybe_generate_weekly_retro() -> None:
    """On a Sunday, write this week's retro and run the weekly reflection, once."""
    from hi.synthesis.reflection import run_weekly_reflection
    from hi.synthesis.retro import generate_weekly_retro, this_weeks_retro_exists

    if date.today().weekday() == _SUNDAY and not this_weeks_retro_exists():
        generate_weekly_retro()
        run_weekly_reflection()


def triage_inbox() -> None:
    from hi.capture.triage import triage_inbox as triage

    triage()


def announce_pending_approval(action) -> None:
    """Show a live approval (an interactive turn is waiting on it) in the menu bar island, so it can be answered
    without tinyui open."""
    from hi.automation.deliver import Delivery, deliver

    deliver(Delivery(
        headline=action.description, kind="approval", priority="urgent", origin="approval",
        dedupe_key=f"approval:{action.id}", payload={"action_id": action.id},
    ))


def start_background_jobs(run_turn=None) -> None:
    """Start every background job. `run_turn` is the server's headless runner (hi/server/headless.py); automation
    jobs use it to run agent turns without importing the server."""
    from hi.memory import proposals
    from hi.orchestrator.pending_actions import set_on_pending

    set_on_pending(announce_pending_approval)
    proposals.recover_interrupted()  # a proposal stuck mid-execution is failed, never re-run
    if run_turn is not None:
        from hi.automation import scheduler

        scheduler.start(run_turn)
        from hi.automation import heartbeat

        heartbeat.start(run_turn)
        from hi.automation import drop

        drop.start()
    jobs.every("triage-inbox", HOUR_S, triage_inbox)
    jobs.every("weekly-retro", HOUR_S, maybe_generate_weekly_retro)
