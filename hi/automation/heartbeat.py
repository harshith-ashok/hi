"""The heartbeat: every half hour, look at what is due, open and on screen, and *prepare* what the user will need.

It is not a chat. One beat:

  1. Gates, with no model: it is on, inside the active hours, and under the hourly limit on background runs.
  2. Signals, found by plain code (hi/automation/signals.py). Screen signals only with a local model.
  3. Fingerprint: the same signals as the last handled beat cost nothing. Most beats end here.
  4. Triage (one cheap model call, JSON): at most three decisions. Each must quote a signal, checked in code, so a small
     model cannot make something up.
  5. Prepare: each `prepare` decision is run as a background task. Reading is free; anything that would act (send,
     write, push) becomes a proposal the user approves.
  6. Deliver once: a single digest (or one line for a nudge), through the inbox gate. If nothing is worth it, nothing.

Every beat is logged to <vault>/hi/heartbeat/YYYY-MM-DD.jsonl, including why it stopped.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import hi.config as config
from hi.automation import context_pack, limits, signals
from hi.automation.deliver import Delivery, deliver, headline_from
from hi.automation.worker import get_worker
from hi.core import runpolicy
from hi.core.runpolicy import UNATTENDED
from hi.llm import registry
from hi.memory import proposals, reports

log = logging.getLogger(__name__)

MAX_DECISIONS = 3
MIN_EVIDENCE_CHARS = 12
MAX_TASK_CHARS = 300
FIRST_BEAT_AFTER_S = 300
PAUSED_MARKER = "Screen context is paused or hidden"

_PROMPT = """You decide whether an assistant should quietly prepare something for its user right now.

Signals (facts found by code):
{signals}

Already prepared recently (never prepare these again):
{prepared}

The user ignored or dismissed these recently (do not suggest anything like them):
{ignored}

Reply with a JSON array of at most {limit} objects, most useful first:
{{"action": "prepare" | "nudge" | "none", "task": "...", "why": "...", "evidence": "..."}}

prepare = concrete work the assistant can do now by reading: search the web, read notes or a repo, summarise, draft text.
Write `task` as an instruction to do that work (for example "Summarise the failing CI log for PR 41 and propose a
fix"). It never sends or changes anything itself.
nudge = one short sentence for something time-critical (a meeting soon, a deadline today).
none = nothing is worth doing. Prefer none.
`evidence` must be an exact quote, at least {min_chars} characters, copied from one signal above. Reply with the JSON only."""


@dataclass
class Decision:
    action: str
    task: str
    why: str
    evidence: str


@dataclass
class BeatResult:
    skipped: str = ""  # why the beat stopped early, "" if it ran to the end
    fingerprint: str = ""
    decisions: list[Decision] = field(default_factory=list)
    delivered: list[str] = field(default_factory=list)  # report ids
    status: str = ""  # the digest's delivery status
    notes: list[str] = field(default_factory=list)


# --- gates and logging ----------------------------------------------------------------------------------------

def in_active_hours(now: datetime, spec: str | None = None) -> bool:
    """`spec` is "08-22" (from 08:00 up to 22:00); "22-06" wraps past midnight."""
    match = re.fullmatch(r"\s*(\d{1,2})\s*-\s*(\d{1,2})\s*", spec if spec is not None else config.HEARTBEAT_HOURS)
    if not match:
        return True
    start, end = int(match.group(1)), int(match.group(2))
    return start <= now.hour < end if start < end else (now.hour >= start or now.hour < end)


def _log_path(now: datetime):
    return config.VAULT_PATH / "hi" / "heartbeat" / f"{now:%Y-%m-%d}.jsonl"


def _log(now: datetime, entry: dict) -> None:
    path = _log_path(now)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"ts": now.isoformat(timespec="seconds"), **entry}, ensure_ascii=False) + "\n")


def previous_fingerprint(now: datetime) -> str:
    """The fingerprint of the last beat that was fully handled (today, else yesterday). A beat that failed is not
    handled: the same situation must be tried again."""
    for offset in (0, 1):
        path = _log_path(datetime.fromtimestamp(now.timestamp() - offset * 86400))
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("handled"):
                return entry.get("fingerprint", "")
    return ""


def fingerprint(found: list[signals.Signal]) -> str:
    return hashlib.sha1("|".join(sorted(s.key for s in found)).encode()).hexdigest()[:16]


# --- triage -----------------------------------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def build_prompt(found: list[signals.Signal], prepared: list[str], ignored: list[str]) -> str:
    return _PROMPT.format(
        signals="\n".join(f"- {s.text}" for s in found) or "(none)",
        prepared="\n".join(f"- {h}" for h in prepared) or "(nothing yet)",
        ignored="\n".join(f"- {i}" for i in ignored) or "(nothing)",
        limit=MAX_DECISIONS, min_chars=MIN_EVIDENCE_CHARS,
    )


def parse_decisions(reply: str, found: list[signals.Signal]) -> list[Decision]:
    """The valid, grounded decisions in the model's reply. Anything that does not quote a real signal is dropped."""
    match = re.search(r"\[.*\]", reply, re.DOTALL)
    if not match:
        return []
    try:
        raw = json.loads(match.group(0))
    except ValueError:
        return []
    haystack = _norm(" ".join(s.text for s in found))
    decisions: list[Decision] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or item.get("action") not in ("prepare", "nudge"):
            continue
        evidence, task = str(item.get("evidence", "")).strip(' "\'`'), str(item.get("task", "")).strip()
        if len(_norm(evidence)) < MIN_EVIDENCE_CHARS or _norm(evidence) not in haystack or not task:
            continue
        decisions.append(Decision(item["action"], task[:MAX_TASK_CHARS], str(item.get("why", ""))[:200], evidence))
        if len(decisions) >= MAX_DECISIONS:
            break
    return decisions


def _default_triage(prompt: str) -> str:
    from langchain_core.messages import HumanMessage

    from hi.llm.resilience import invoke_with_retry

    return invoke_with_retry(registry.get_tier_model_fast("haiku"), [HumanMessage(prompt)])


def ignored_messages(limit: int = 10) -> list[str]:
    """What the user ignored lately, from the Mac's inbox log."""
    import sys

    if sys.platform == "darwin":
        from hi.context import inbox

        return [m for m, _ in inbox.recent_outcomes(limit)]
    from hi import host

    text = host.call("recent_outcomes", {"limit": limit})
    if text.startswith(("Can't reach", "The Mac bridge", "Mac bridge error")):
        return []
    return [line.rsplit(" | ", 1)[0] for line in text.splitlines() if line.strip()]


# --- one beat ---------------------------------------------------------------------------------------------------

def _prepare(decision: Decision, now: datetime, run_turn, pack_screen: bool, tier: str, described: str | None):
    pack = context_pack.build({"vault", "screen"} if pack_screen else {"vault"}, decision.task, tier, now, described)
    policy = runpolicy.replace_policy(UNATTENDED, allow_web=True, allow_screen=pack.screen_included,
                                      max_tool_calls=config.MAX_BACKGROUND_TOOL_CALLS)
    return run_turn(decision.task, origin="heartbeat", policy=policy, tier=tier, context=pack.text,
                    profile="heartbeat.prepare"), pack


def beat(now: datetime, run_turn, deliver_fn=deliver, *, described: str | None = None,
         triage_fn: Callable[[str], str] | None = None, ignored: list[str] | None = None) -> BeatResult:
    """One heartbeat. Never raises."""
    result = BeatResult()
    try:
        _beat(now, run_turn, deliver_fn, described, triage_fn or _default_triage, ignored, result)
    except Exception as e:  # boundary: a heartbeat failure is logged and never reaches the worker
        log.exception("heartbeat failed")
        result.skipped = f"failed: {e}"
        _log(now, {"attempt": True, "skipped": result.skipped})
    return result


def _beat(now, run_turn, deliver_fn, described, triage_fn, ignored, result: BeatResult) -> None:
    if not config.HEARTBEAT:
        result.skipped = "off"
        return
    if not in_active_hours(now):
        result.skipped = "outside active hours"
        return
    if reason := limits.check_run(now.timestamp()):
        result.skipped = reason
        _log(now, {"attempt": True, "skipped": reason})
        return

    if described is None:
        from hi.context import now as live

        described = live.describe(include_screen=True)
    screen_ok = registry.is_local("haiku") and bool(described) and not described.startswith(PAUSED_MARKER)
    if not screen_ok:
        result.notes.append("screen left out")
    found = signals.collect(now, described or "", include_screen=screen_ok)
    result.fingerprint = fingerprint(found)
    if not found:
        result.skipped = "no signals"
        _log(now, {"fingerprint": result.fingerprint, "handled": True, "skipped": "no signals"})
        return
    if result.fingerprint == previous_fingerprint(now):
        result.skipped = "unchanged"
        _log(now, {"fingerprint": result.fingerprint, "handled": True, "skipped": "unchanged"})
        return

    prompt = build_prompt(found, reports.recent_headlines(8), ignored if ignored is not None else ignored_messages())
    result.decisions = parse_decisions(triage_fn(prompt), found)
    prepared = _run_decisions(now, result, run_turn, deliver_fn, screen_ok, described)
    proposals.expire_old()
    _log(now, {"fingerprint": result.fingerprint, "handled": True, "signals": [s.key for s in found],
               "decisions": [d.__dict__ for d in result.decisions], "delivered": result.delivered,
               "status": result.status, "prepared": prepared})


def _run_decisions(now, result: BeatResult, run_turn, deliver_fn, screen_ok: bool, described: str | None) -> int:
    items: list[tuple[str, str, list[str]]] = []  # (headline, report id, proposal ids)
    tier = limits.choose_tier("sonnet", now.timestamp())
    for decision in [d for d in result.decisions if d.action == "prepare"][:MAX_DECISIONS]:
        if tier is None or limits.check_run(now.timestamp()):
            result.notes.append("stopped preparing: background run limit reached")
            break
        run, pack = _prepare(decision, now, run_turn, screen_ok, tier, described)
        if run.error or not run.answer:
            result.notes.append(f"could not prepare '{decision.task[:50]}': {run.error or 'no answer'}")
            continue
        headline = headline_from(run.answer) or decision.task[:80]
        items.append((headline, run.answer, list(run.proposals)))
        result.notes += pack.notes

    if items:
        many = len(items) > 1
        reports_made: list[tuple[str, str]] = []
        for headline, answer, ids in items:
            out = deliver_fn(Delivery(
                headline=headline, body=answer, kind="info", origin="heartbeat", proposals=tuple(ids),
                popup="no" if many else "yes", dedupe_key="" if many else f"heartbeat:{result.fingerprint}",
            ))
            result.delivered.append(out.report_id)
            reports_made.append((headline, out.report_id))
            result.status = out.status
        if many:
            lines = "\n".join(f"- {h} (report {rid})" for h, rid in reports_made)
            all_ids = tuple(p for _, _, ids in items for p in ids)
            out = deliver_fn(Delivery(
                headline=f"{len(items)} things ready: {items[0][0]}", body=f"## Prepared for you\n\n{lines}",
                kind="digest", origin="heartbeat", proposals=all_ids, dedupe_key=f"heartbeat:{result.fingerprint}",
            ))
            result.status = out.status
            result.delivered.append(out.report_id)
        return len(items)

    nudge = next((d for d in result.decisions if d.action == "nudge"), None)
    if nudge:
        out = deliver_fn(Delivery(headline=nudge.task, kind="info", origin="heartbeat",
                                  dedupe_key=f"heartbeat:{result.fingerprint}"))
        result.status = out.status
    return 0


# --- the job ----------------------------------------------------------------------------------------------------

_last_beat: float | None = None


def maybe_beat(run_turn, submit=None, now: datetime | None = None) -> bool:
    """Called every minute by a job: queue a beat if one is due. HEARTBEAT_EVERY is read live. Returns whether a beat
    was queued."""
    global _last_beat
    now = now or datetime.now()
    every = max(60, config.HEARTBEAT_EVERY)
    if _last_beat is None:  # the first beat comes soon after start, not a full interval later
        _last_beat = now.timestamp() - every + min(FIRST_BEAT_AFTER_S, every)
    if now.timestamp() - _last_beat < every:
        return False
    _last_beat = now.timestamp()
    submit = submit or get_worker().submit
    return bool(submit("heartbeat", lambda: beat(now, run_turn)))


def start(run_turn) -> None:
    from hi.core import jobs

    jobs.every("heartbeat", 60, lambda: maybe_beat(run_turn))
