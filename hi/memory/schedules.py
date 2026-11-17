"""Scheduled tasks, kept as notes in the vault so you can read and edit them in Obsidian.

    <vault>/hi/schedules/<id>.md       frontmatter (when, kind, tier, ...) + the task prompt as the body
    <vault>/hi/schedules/runs.jsonl    append-only: {id, slot, status, ts, report, error}

`when` is a five-field cron expression ("0 8 * * 1-5", local time) or "once 2026-11-20T15:00". A slot is one
scheduled moment, identified by its time. `claim` records that a slot is being handled and refuses a second claim,
which is what stops a slot from running twice (two ticks, a restart, two processes).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from croniter import croniter

import hi.config as config
from hi.memory.frontmatter import dump_frontmatter, parse_frontmatter

log = logging.getLogger(__name__)

_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,59}")
KINDS = ("task", "reminder")
DELIVER_MODES = ("notify", "report", "silent")
CONTEXT_PARTS = ("vault", "screen")
DEFAULT_CATCH_UP_S = 7200
MAX_FIRES = 500
STATUSES = ("claimed", "done", "failed", "missed", "skipped")
_lock = threading.Lock()


@dataclass
class Schedule:
    id: str
    when: str
    prompt: str
    enabled: bool = True
    kind: str = "task"  # task: runs the agent; reminder: delivers the prompt as it is, no model
    persona: str = "term"
    tier: str = "sonnet"
    deliver: str = "notify"  # notify: report and pop-up; report: report (pop-up only for approvals); silent: report only
    context: tuple[str, ...] = ("vault",)
    allow_web: bool = False
    allow: tuple[str, ...] = ()  # tools beyond read-only that may run without approval
    catch_up_s: int = DEFAULT_CATCH_UP_S
    created: str = ""


def schedules_dir() -> Path:
    return config.VAULT_PATH / "hi" / "schedules"


def runs_path() -> Path:
    return schedules_dir() / "runs.jsonl"


def valid_id(schedule_id: str) -> bool:
    return bool(_ID.fullmatch(schedule_id))


# --- reading and writing the notes ---------------------------------------------------------------------------

def parse_duration(text: str) -> int:
    """"2h", "30m", "1d", "90s" or plain seconds -> seconds."""
    match = re.fullmatch(r"\s*(\d+)\s*([smhd]?)\s*", str(text))
    if not match:
        raise ValueError(f"not a duration: {text!r} (use 30m, 2h, 1d)")
    return int(match.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]


def _format_duration(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _unquote(value: str) -> str:
    value = value.strip()
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'" else value


def _as_list(value) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(v for v in value if v)
    return tuple(v.strip() for v in str(value).split(",") if v.strip())


def from_markdown(schedule_id: str, content: str) -> Schedule:
    """Raises ValueError with a message the user can act on."""
    fields, body = parse_frontmatter(content)
    when = _unquote(str(fields.get("when", "")))
    if error := validate_when(when):
        raise ValueError(error)
    kind = str(fields.get("kind", "task"))
    deliver = str(fields.get("deliver", "notify"))
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if deliver not in DELIVER_MODES:
        raise ValueError(f"deliver must be one of {', '.join(DELIVER_MODES)}")
    context = _as_list(fields.get("context", "vault"))
    if bad := [c for c in context if c not in CONTEXT_PARTS]:
        raise ValueError(f"unknown context {bad}; use {', '.join(CONTEXT_PARTS)}")
    prompt = body.strip()
    if not prompt:
        raise ValueError("the note has no text: put the task in the body")
    return Schedule(
        id=schedule_id, when=when, prompt=prompt,
        enabled=str(fields.get("enabled", "true")).lower() != "false",
        kind=kind, persona=str(fields.get("persona", "term")), tier=str(fields.get("tier", "sonnet")),
        deliver=deliver, context=context,
        allow_web=str(fields.get("allow_web", "false")).lower() == "true",
        allow=_as_list(fields.get("allow", [])),
        catch_up_s=parse_duration(str(fields.get("catch_up", "2h"))),
        created=str(fields.get("created", "")),
    )


def to_markdown(s: Schedule) -> str:
    fields = {
        "id": s.id, "when": f'"{s.when}"', "enabled": str(s.enabled).lower(), "kind": s.kind, "persona": s.persona,
        "tier": s.tier, "deliver": s.deliver, "context": list(s.context), "allow_web": str(s.allow_web).lower(),
        "allow": list(s.allow), "catch_up": _format_duration(s.catch_up_s), "created": s.created,
        "tags": ["hi", "schedule"],
    }
    return f"{dump_frontmatter(fields)}\n{s.prompt.strip()}\n"


def load(schedule_id: str) -> Schedule | None:
    if not valid_id(schedule_id):
        return None
    try:
        return from_markdown(schedule_id, (schedules_dir() / f"{schedule_id}.md").read_text())
    except (OSError, ValueError):
        return None


def load_all(errors: list[str] | None = None) -> list[Schedule]:
    """Every schedule note. A note that does not parse is skipped and described in `errors`, so one typo in
    Obsidian never stops the others."""
    found: list[Schedule] = []
    folder = schedules_dir()
    if not folder.exists():
        return found
    for path in sorted(folder.glob("*.md")):
        try:
            if not valid_id(path.stem):
                raise ValueError("the file name must be lowercase letters, digits and dashes")
            s = from_markdown(path.stem, path.read_text())
            s.created = s.created or datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
            found.append(s)
        except (OSError, ValueError) as e:
            if errors is not None:
                errors.append(f"{path.name}: {e}")
            log.warning("schedule %s ignored: %s", path.name, e)
    return found


def save(s: Schedule) -> Path:
    if not valid_id(s.id):
        raise ValueError(f"bad schedule id {s.id!r}")
    s.created = s.created or datetime.now().isoformat(timespec="seconds")
    path = schedules_dir() / f"{s.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(to_markdown(s))
    tmp.replace(path)  # atomic: Obsidian and the scheduler never see half a file
    return path


def delete(schedule_id: str) -> bool:
    if not valid_id(schedule_id):
        return False
    path = schedules_dir() / f"{schedule_id}.md"
    if not path.exists():
        return False
    path.unlink()
    return True


def set_enabled(schedule_id: str, enabled: bool) -> bool:
    s = load(schedule_id)
    if s is None:
        return False
    s.enabled = enabled
    save(s)
    return True


def new_id(text: str) -> str:
    """A readable id from the first words of `text`, unique among the existing schedules."""
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30].strip("-") or "schedule"
    taken, candidate, n = {s.id for s in load_all()}, base, 1
    while candidate in taken:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


# --- when -----------------------------------------------------------------------------------------------------

def validate_when(when: str) -> str:
    """"" if `when` is usable, else what is wrong."""
    when = when.strip()
    if when.lower().startswith("once"):
        try:
            datetime.fromisoformat(when[4:].strip())
        except ValueError:
            return 'a one-time schedule looks like "once 2026-11-20T15:00"'
        return ""
    if not croniter.is_valid(when) or len(when.split()) != 5:
        return 'use five cron fields, like "0 8 * * 1-5" (8:00 on weekdays), or "once 2026-11-20T15:00"'
    return ""


def fires_between(s: Schedule, after: datetime, upto: datetime, limit: int = MAX_FIRES) -> list[datetime]:
    """Scheduled moments in (after, upto], local time, oldest first."""
    if s.when.lower().startswith("once"):
        at = datetime.fromisoformat(s.when[4:].strip())
        return [at] if after < at <= upto else []
    fires: list[datetime] = []
    it = croniter(s.when, after)
    while len(fires) < limit:
        nxt = it.get_next(datetime)
        if nxt > upto:
            break
        fires.append(nxt)
    return fires


def next_fires(s: Schedule, n: int, now: datetime) -> list[datetime]:
    if s.when.lower().startswith("once"):
        return fires_between(s, now, datetime.max)[:n]
    it = croniter(s.when, now)
    return [it.get_next(datetime) for _ in range(n)]


def say_time(moment: datetime) -> str:
    return f"{moment:%a} {moment.day} {moment:%b} {moment:%H:%M}"


# --- the run log ----------------------------------------------------------------------------------------------

def _read_runs() -> list[dict]:
    try:
        lines = runs_path().read_text().splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _append_run(entry: dict) -> None:
    path = runs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"ts": time.time(), **entry}, ensure_ascii=False) + "\n")


def claim(schedule_id: str, slot: str) -> bool:
    """Record that `slot` is being handled. False if it already was: the caller must not run it."""
    with _lock:
        if any(r["id"] == schedule_id and r["slot"] == slot for r in _read_runs()):
            return False
        _append_run({"id": schedule_id, "slot": slot, "status": "claimed"})
    return True


def finish(schedule_id: str, slot: str, status: str, report: str = "", error: str = "") -> None:
    with _lock:
        _append_run({"id": schedule_id, "slot": slot, "status": status, "report": report, "error": error})


def last_slot(schedule_id: str) -> datetime | None:
    """The newest scheduled moment already handled (manual runs do not count)."""
    slots = []
    for r in _read_runs():
        if r["id"] == schedule_id and r["slot"][:1].isdigit():
            try:
                slots.append(datetime.fromisoformat(r["slot"]))
            except ValueError:
                continue
    return max(slots) if slots else None


def runs(schedule_id: str | None = None, limit: int = 20) -> list[dict]:
    """The newest outcome per slot, newest first."""
    latest: dict[tuple[str, str], dict] = {}
    for r in _read_runs():
        if schedule_id is None or r["id"] == schedule_id:
            latest[(r["id"], r["slot"])] = r
    return sorted(latest.values(), key=lambda r: r["ts"], reverse=True)[:limit]
