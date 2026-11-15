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


def start_background_jobs() -> None:
    jobs.every("triage-inbox", HOUR_S, triage_inbox)
    jobs.every("weekly-retro", HOUR_S, maybe_generate_weekly_retro)
