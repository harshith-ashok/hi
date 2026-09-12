"""Real data for the web frontend's home dashboard (`frontend/`'s own
`ui-vue.html` template) — system vitals, vault/task stats, and the
most-recently-opened project. Every value here is genuinely read from
the machine/vault, never fabricated: a stat this project can't actually
read (macOS Focus/DND state has no stable read API — see
`hi/agents/butler/mac_control.py`'s own `toggle_dnd()` docstring; there's
no calendar integration built at all) is simply not exposed here rather
than shown as a guessed or hardcoded placeholder.
"""

from __future__ import annotations

import subprocess
import time
from datetime import date

import psutil

from hi.briefing import _last_edited_note, _last_opened_project
from hi.capture.store import list_items
import hi.config as config
from hi.tracking.deadlines import get_deadlines

# Updated by hi/ipc/server.py after every real /query response completes
# — the only way to report a genuine "last latency" number instead of a
# fabricated one; None until at least one real query has happened this
# process.
_last_query_latency_ms: float | None = None


def record_query_latency(seconds: float) -> None:
    global _last_query_latency_ms
    _last_query_latency_ms = seconds * 1000


def get_vitals(active_model: str) -> dict:
    battery = psutil.sensors_battery()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_percent": psutil.virtual_memory().percent,
        "battery_percent": battery.percent if battery else None,
        "wifi_ssid": _wifi_ssid(),
        "active_model": active_model,
        "last_latency_ms": _last_query_latency_ms,
    }


def _wifi_ssid() -> str | None:
    # Correction, found live: an earlier version of this used
    # `networksetup -getairportnetwork` — it claimed "not associated"
    # even while genuinely connected (confirmed by cross-checking
    # `route -n get default` and `ipconfig getifaddr` against it on the
    # exact same real connection at the exact same time). That CoreWLAN-
    # backed API is gated behind macOS's Location Services permission
    # for the calling process on modern macOS, which this backend
    # doesn't have — it wasn't reporting real state, just failing
    # silently into a wrong-but-plausible-looking answer. `ipconfig
    # getsummary <device>` reads link-layer/DHCP info instead, which
    # isn't behind that gate, and correctly returned the real SSID on
    # the same live test. `_wifi_device()`, not a hardcoded "en0": not
    # every Mac's Wi-Fi hardware is en0.
    from hi.agents.butler.mac_control import _wifi_device

    device = _wifi_device()
    if not device:
        return None
    try:
        result = subprocess.run(
            ["ipconfig", "getsummary", device], capture_output=True, text=True, timeout=2,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("SSID "):
            _, _, value = stripped.partition(" : ")
            return value.strip() or None
    return None


def get_vault_stats() -> dict:
    today = date.today()
    hi_dir = config.VAULT_PATH / "hi"
    touched_today = 0
    if config.VAULT_PATH.is_dir():
        for note in config.VAULT_PATH.rglob("*.md"):
            if note.is_relative_to(hi_dir):
                continue  # same exclusion hi/briefing.py's own _last_edited_note() makes
            if date.fromtimestamp(note.stat().st_mtime) == today:
                touched_today += 1
    return {
        "notes_touched_today": touched_today,
        "last_edited_note": _last_edited_note(),
    }


def get_today_stats() -> dict:
    today_str = date.today().isoformat()
    pending_tasks = [
        t for t in list_items(kind="task") if t.status == "pending"
    ]
    tasks_due_today = sum(1 for t in pending_tasks if t.due and t.due.startswith(today_str))
    deadlines = get_deadlines()
    next_deadline = f"{deadlines[0].due} — {deadlines[0].title}" if deadlines else None
    return {"tasks_due_today": tasks_due_today, "next_deadline": next_deadline}


def get_last_project() -> str | None:
    return _last_opened_project()
