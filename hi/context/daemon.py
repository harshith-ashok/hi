"""Always-on context agent: keeps ~/.hi/context/now.json describing what the user is doing, so the
assistant already knows when they ask (hi --context-daemon). Native on the Mac: needs Screen Recording
and Accessibility permission for the terminal/Python that runs it.

Cheap every few seconds (frontmost app, window title, idle time); heavier work only on a change:
- screenshot + on-device Apple Vision OCR when the app/window changes, or every OCR_EVERY seconds;
- a one-sentence "what is the user doing" from the LOCAL model, at most every SUMMARY_EVERY seconds.

Privacy: private/denylisted apps (hi/perception/privacy.py + CONTEXT_DENYLIST) are never captured; `touch
~/.hi/context/paused` (or the pause_screen_context tool) stops everything; screenshots are deleted at once;
only the latest OCR text is kept (now.json is overwritten); history keeps app + one-line activity, no text.
Screen text is only ever sent to a local model, never to a cloud/hosted one.
"""

from __future__ import annotations

import json
import subprocess
import time

import hi.config as config
from hi import proactive
from hi.context import now as store
from hi.perception import privacy

POLL_SECONDS = 3
OCR_EVERY = 45
SUMMARY_EVERY = 60
HISTORY_MAX = 1000
_FRONT_SCRIPT = (
    'tell application "System Events" to tell (first application process whose frontmost is true)\n'
    '  set t to ""\n  try\n    set t to name of front window\n  end try\n'
    '  return (name & "|||" & t)\nend tell'
)


TITLE_EVERY = 9  # seconds; the window title needs System Events, which is the expensive call
_last_title: tuple[str, str, float] = ("", "", 0.0)


def frontmost() -> tuple[str, str]:
    """(app, window title). The app comes free from NSWorkspace every poll; the title is re-read
    only when the app changes or every TITLE_EVERY seconds."""
    global _last_title
    from AppKit import NSWorkspace

    app = str(NSWorkspace.sharedWorkspace().frontmostApplication().localizedName() or "")
    if _last_title[0] == app and time.time() - _last_title[2] < TITLE_EVERY:
        return app, _last_title[1]
    title = _front_title()
    _last_title = (app, title, time.time())
    return app, title


def _front_title() -> str:
    out = subprocess.run(["osascript", "-e", _FRONT_SCRIPT], capture_output=True, text=True).stdout.strip()
    return out.partition("|||")[2]


def idle_seconds() -> float:
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "HIDIdleTime" in line:
            return int(line.split("=")[-1]) / 1e9
    return 0.0


def top_processes(n: int = 5) -> list[str]:
    out = subprocess.run(["ps", "-Arco", "pcpu,comm"], capture_output=True, text=True).stdout.splitlines()[1 : n + 1]
    return [f"{line.split(None, 1)[1]} {line.split()[0]}%" for line in out if line.strip()]


def local_model_ok() -> bool:
    """Screen text may only reach a model running on the user's own hardware."""
    models = [config.HAIKU_MODEL]
    return config.AI_MODE != "openrouter" and not any("cloud" in m for m in models)


def summarize(app: str, title: str, screen: str) -> str:
    from langchain_core.messages import HumanMessage

    from hi.models import get_tier_model_fast

    prompt = (
        "In ONE short sentence (max 20 words), say what the user is doing right now, from this. "
        "Be specific (the file, page or problem), no preamble.\n"
        f"App: {app}\nWindow: {title}\nVisible text:\n{screen[:1500]}"
    )
    try:
        return get_tier_model_fast("haiku").invoke([HumanMessage(prompt)]).content.strip().splitlines()[0][:200]
    except Exception:
        return ""


def _append_history(entry: dict) -> None:
    store.DIR.mkdir(parents=True, exist_ok=True)
    with store.HISTORY.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    lines = store.HISTORY.read_text().splitlines()
    if len(lines) > HISTORY_MAX:
        store.HISTORY.write_text("\n".join(lines[-HISTORY_MAX // 2 :]) + "\n")


def _write(snapshot: dict) -> None:
    store.DIR.mkdir(parents=True, exist_ok=True)
    tmp = store.NOW.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot))
    tmp.replace(store.NOW)  # atomic: readers never see half a file


def run_context_daemon() -> None:
    from hi.perception.screen import ocr_screen

    summarizing = local_model_ok()
    print(f"Context daemon running every {POLL_SECONDS}s ({'with' if summarizing else 'WITHOUT'} local summaries). Ctrl-C to stop.")
    key, since, last_ocr, last_summary = None, time.time(), 0.0, 0.0
    screen, activity = "", ""
    last_nudge = time.time()  # first consideration after a full interval, not at startup
    while True:
        try:
            app, title = frontmost()
            if store.PAUSED.exists() or privacy.reason_for(app, title):
                # Deliberately blank: nothing about a private/paused moment is recorded.
                _write({"ts": time.time(), "app": "", "paused": store.PAUSED.exists(), "private": not store.PAUSED.exists()})
                screen, activity, key = "", "", None
                time.sleep(POLL_SECONDS)
                continue
            changed = (app, title) != key
            if changed:
                key, since, screen, activity = (app, title), time.time(), "", ""
            if changed or time.time() - last_ocr >= OCR_EVERY:
                time.sleep(2 if changed else 0)  # let a new window finish drawing
                if privacy.reason_for(*frontmost()) is None:
                    screen, last_ocr = "\n".join(ocr_screen()), time.time()
                if summarizing and screen and time.time() - last_summary >= SUMMARY_EVERY:
                    activity, last_summary = summarize(app, title, screen), time.time()
                if changed or activity:
                    _append_history({"ts": time.time(), "app": app, "title": title[:80], "activity": activity})
            if summarizing and proactive.due(last_nudge):
                last_nudge = time.time()
                if said := proactive.nudge():
                    print(f"[nudge] {said}", flush=True)
            _write({
                "ts": time.time(), "app": app, "title": title, "since": since, "idle": idle_seconds(),
                "processes": top_processes(), "screen": screen[:4000], "activity": activity,
            })
        except Exception as e:  # a bad poll must never kill an always-on daemon
            print(f"context poll failed: {e}", flush=True)
        time.sleep(POLL_SECONDS)
