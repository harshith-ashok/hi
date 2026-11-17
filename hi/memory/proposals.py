"""Proposals: actions an unattended run wanted to take but may not, waiting for the user to approve them.

An append-only log, `<vault>/hi/proposals.jsonl`. Each line is an event for one proposal id, and a proposal's
current status is its latest event:

    created -> approved -> executing -> executed | failed
    created -> denied | expired

`begin_execution` is the only way into `executing`: it moves a proposal from `created` exactly once, under a lock,
so an approval clicked twice (or from two places) runs the tool once.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path

import hi.config as config
from hi.core import jsonl

DAY_S = 86400
_lock = threading.Lock()

CREATED, APPROVED, DENIED, EXECUTING, EXECUTED, FAILED, EXPIRED = (
    "created", "approved", "denied", "executing", "executed", "failed", "expired",
)


def path() -> Path:
    return config.VAULT_PATH / "hi" / "proposals.jsonl"


def _append(event: dict) -> None:
    file = path()
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("a") as f:
        f.write(json.dumps({"ts": time.time(), **event}, ensure_ascii=False) + "\n")


def _read() -> list[dict]:
    return jsonl.read(path())  # cached until the file changes; a torn line is skipped


def _fold(events: list[dict]) -> dict[str, dict]:
    """id -> the proposal: the fields of its `created` event plus `status`, `updated` and `result`."""
    proposals: dict[str, dict] = {}
    for e in events:
        pid = e.get("id")
        if not pid:
            continue
        if e["event"] == CREATED:
            proposals[pid] = {**e, "status": CREATED, "created_at": e["ts"], "updated": e["ts"], "result": ""}
        elif pid in proposals:
            proposals[pid].update(status=e["event"], updated=e["ts"], result=e.get("result", proposals[pid]["result"]))
    return proposals


def create(origin: str, persona: str, tool: str, args: dict, reason: str = "", report_id: str = "") -> str:
    pid = "P-" + secrets.token_hex(3)
    with _lock:
        while pid in _fold(_read()):
            pid = "P-" + secrets.token_hex(3)
        _append({"event": CREATED, "id": pid, "origin": origin, "persona": persona, "tool": tool, "args": args,
                 "reason": reason, "report_id": report_id})
    return pid


def get(pid: str) -> dict | None:
    return _fold(_read()).get(pid)


def all_proposals() -> list[dict]:
    return sorted(_fold(_read()).values(), key=lambda p: p["created_at"], reverse=True)


def pending() -> list[dict]:
    return [p for p in all_proposals() if p["status"] == CREATED]


def mark(pid: str, status: str, result: str = "") -> None:
    with _lock:
        _append({"event": status, "id": pid, "result": result})


def deny(pid: str) -> bool:
    """False if the proposal is not waiting (already answered, expired, or unknown)."""
    with _lock:
        proposal = _fold(_read()).get(pid)
        if proposal is None or proposal["status"] != CREATED:
            return False
        _append({"event": DENIED, "id": pid})
    return True


def begin_execution(pid: str) -> dict | None:
    """Claim a waiting proposal for execution, once. Returns it, or None if it was not waiting."""
    with _lock:
        proposal = _fold(_read()).get(pid)
        if proposal is None or proposal["status"] != CREATED:
            return None
        _append({"event": APPROVED, "id": pid})
        _append({"event": EXECUTING, "id": pid})
    return proposal


def expire_old(ttl_days: int | None = None, now: float | None = None) -> int:
    """Expire proposals that waited longer than the limit. Returns how many."""
    limit = (ttl_days if ttl_days is not None else config.PROPOSAL_TTL_DAYS) * DAY_S
    now = now if now is not None else time.time()
    old = [p["id"] for p in pending() if now - p["created_at"] > limit]
    for pid in old:
        mark(pid, EXPIRED)
    return len(old)


def recover_interrupted() -> int:
    """After a restart, a proposal stuck in `executing` is marked failed. It is never run again: the tool may have
    done part of its work."""
    stuck = [p["id"] for p in all_proposals() if p["status"] == EXECUTING]
    for pid in stuck:
        mark(pid, FAILED, "interrupted; check manually")
    return len(stuck)


def describe(proposal: dict, limit: int = 140) -> str:
    """One line saying exactly what approving would run, e.g. send_email(to='bob@acme.com', subject='Follow-up')."""
    args = ", ".join(f"{k}={str(v)[:40]!r}" for k, v in (proposal.get("args") or {}).items())
    text = f"{proposal['tool']}({args})"
    return text if len(text) <= limit else text[: limit - 1] + "…"
