"""Screenshot-diff scene-change watchdog (`BLOCKERS.md` -> "Ambient &
real-time gaps" #4): a genuinely *different* privacy posture than every
other tool in `hi/perception/` (`screen.py`/`vision.py`/`browser.py`),
which are strictly one-shot and only ever run in response to an explicit
ask. This one runs on an interval, unattended — which is exactly why it
is opt-in via a new `DIFF_WATCH_ENABLED` flag in `~/.hi/.env`
(`hi/config.py`), **off by default**, rather than silently broadening
what "on-demand" means for the existing tools. `read_screen()`/
`ask_about_screen()` are completely unmodified by this module — this is
new, separately-gated surface area sitting next to them.

Purely change-detection, nothing more: each check takes one screenshot,
hashes the raw PNG bytes (sha256), deletes the file immediately, and
compares the hash to the last one seen. The pixel content itself is
never OCR'd, never inspected, never stored anywhere — only the fact "it
changed" or "it's been unchanged for N minutes" is ever persisted, never
the image. Still runs every single check through
`hi/perception/privacy.py`'s existing `sensitive_context_reason()` gate
first, same as every other perception tool — a check near a password
manager or a private/incognito window is skipped outright for that
cycle, not just its content withheld.

Deliberately a coarse, honest byte-hash comparison rather than a
perceptual diff: a blinking cursor or a ticking menu-bar clock registers
as "changed" just like anything else would. That makes the "unchanged
for N minutes" signal *conservative* (harder to false-positive on
"stuck"), not over-eager — the same trade-off already made picking
macOS `say` over a fancier TTS engine (hi/tts.py): the honest
zero-dependency version, not a more precise one nothing here has yet
proven necessary.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from hi.perception.privacy import sensitive_context_reason

STATE_PATH = Path.home() / ".hi" / "diff_watch_state.json"

POLL_INTERVAL_SECONDS = 120  # ~2min, per BLOCKERS.md
UNCHANGED_THRESHOLD_SECONDS = 10 * 60  # BLOCKERS.md's own "stuck for 10 minutes" example


@dataclass
class _State:
    file_hash: str | None
    since: float  # epoch seconds this hash first became (continuously) current


def _load_state() -> _State | None:
    if not STATE_PATH.exists():
        return None
    try:
        data = json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return _State(file_hash=data.get("file_hash"), since=data.get("since", 0.0))


def _save_state(state: _State) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"file_hash": state.file_hash, "since": state.since}))


def _screenshot_hash() -> str | None:
    """One screenshot, hashed, deleted — never held onto, never OCR'd."""
    path = Path(tempfile.mktemp(suffix=".png"))
    try:
        result = subprocess.run(["screencapture", "-x", str(path)], capture_output=True, text=True)
        if result.returncode != 0 or not path.exists():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    finally:
        path.unlink(missing_ok=True)


def poll_once() -> None:
    """Check the screen once and update persisted hash/dwell state if it
    changed. Refuses silently (no-op, same as any other perception tool's
    refusal) near a password manager or private/incognito window — never
    even takes the screenshot in that case. Safe to call on a long
    interval (~2min); does nothing more than a hash comparison either
    way."""
    if sensitive_context_reason():
        return
    file_hash = _screenshot_hash()
    if file_hash is None:
        return
    state = _load_state()
    if state is None or state.file_hash != file_hash:
        _save_state(_State(file_hash=file_hash, since=time.time()))


def unchanged_suggestion(threshold_seconds: int = UNCHANGED_THRESHOLD_SECONDS) -> int | None:
    """Returns the number of minutes the screen has been unchanged (by
    poll_once()'s persisted hash state), if at least `threshold_seconds`
    — else None. A pure read with no side effects; hi/suggest/engine.py
    turns this into an actual, gated Suggestion (only when
    DIFF_WATCH_ENABLED is set — this function itself doesn't check the
    flag, since a caller with no persisted state simply gets None either
    way, and the flag gate belongs at the call site that decides whether
    to poll at all)."""
    state = _load_state()
    if state is None or state.file_hash is None:
        return None
    dwell = time.time() - state.since
    if dwell < threshold_seconds:
        return None
    return int(dwell // 60)
