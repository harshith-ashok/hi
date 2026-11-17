"""How much unattended work is allowed, and the record of what ran.

    ~/.hi/state/usage.jsonl   one line per background run: {ts, origin, tier, hosted, tool_calls, seconds, first_token_s}

Two limits keep a loop or a misconfiguration from running up a bill or a fan: runs per hour, and runs per day on a
hosted (cloud) model. Past the daily hosted limit a run is moved to a local tier, or skipped if there is none.
The record also holds per-origin latency, which is how the island's "fast" target is measured.
"""

from __future__ import annotations

import json
import time

import hi.config as config
from hi.core import jsonl
from hi.core.runpolicy import BACKGROUND_ORIGINS
from hi.llm import registry

KEEP_LINES = 2000
TRIM_AT = 5000  # lines read when counting
TRIM_BYTES = 1_000_000  # the file is trimmed to KEEP_LINES once it passes this size
LOCAL_TIERS = ("sonnet", "haiku")  # tried in this order when a hosted run is over its limit


def _path():
    return config.state_dir() / "usage.jsonl"


def record(origin: str, tier: str, hosted: bool, tool_calls: int, seconds: float,
           first_token_s: float | None = None, now: float | None = None) -> None:
    entry = {"ts": now if now is not None else time.time(), "origin": origin, "tier": tier, "hosted": hosted,
             "tool_calls": tool_calls, "seconds": round(seconds, 2), "first_token_s": first_token_s}
    path = _path()
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    if path.stat().st_size > TRIM_BYTES:  # a size check, not a read of the whole file on every turn
        lines = path.read_text().splitlines()
        path.write_text("\n".join(lines[-KEEP_LINES:]) + "\n")


def _entries(since: float) -> list[dict]:
    return [e for e in jsonl.read(_path())[-TRIM_AT:] if e.get("ts", 0) >= since]


def background_runs_last_hour(now: float | None = None) -> int:
    now = now if now is not None else time.time()
    return sum(1 for e in _entries(now - 3600) if e.get("origin") in BACKGROUND_ORIGINS)


def hosted_runs_today(now: float | None = None) -> int:
    now = now if now is not None else time.time()
    midnight = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    return sum(1 for e in _entries(midnight) if e.get("hosted") and e.get("origin") in BACKGROUND_ORIGINS)


def check_run(now: float | None = None) -> str:
    """"" if another background run may start, else why not."""
    used = background_runs_last_hour(now)
    if used >= config.MAX_BACKGROUND_RUNS_PER_HOUR:
        return f"the limit of {config.MAX_BACKGROUND_RUNS_PER_HOUR} background runs per hour is reached"
    return ""


def choose_tier(tier: str, now: float | None = None) -> str | None:
    """`tier`, or a local tier when `tier` is hosted and today's hosted limit is used up; None if neither is possible."""
    if registry.is_local(tier) or hosted_runs_today(now) < config.MAX_HOSTED_CALLS_PER_DAY:
        return tier
    return next((t for t in LOCAL_TIERS if registry.is_local(t)), None)


def latency_by_origin(now: float | None = None, hours: float = 24) -> dict[str, dict]:
    """{origin: {runs, avg_seconds, avg_first_token_s}} over the last `hours`."""
    now = now if now is not None else time.time()
    groups: dict[str, list[dict]] = {}
    for e in _entries(now - hours * 3600):
        groups.setdefault(e.get("origin", ""), []).append(e)
    out = {}
    for origin, rows in groups.items():
        firsts = [r["first_token_s"] for r in rows if r.get("first_token_s") is not None]
        out[origin] = {"runs": len(rows), "avg_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 2),
                       "avg_first_token_s": round(sum(firsts) / len(firsts), 2) if firsts else None}
    return out
