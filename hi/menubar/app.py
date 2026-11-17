"""What the menu bar app and notch island do besides drawing (hi --menubar; the UI is in island.py).

`capture_screen()` screenshots BEFORE any window of ours shows (so the assistant's own UI is not in the shot),
OCRs it on-device in the background and pins the text to ~/.hi/context/pinned.json, which the assistant's prompt
picks up (hi/context/now.py). `stream_answer()` sends a prompt to the backend's /query and streams the reply.
Private apps are never captured. Native PyObjC, no extra dependencies.
"""

from __future__ import annotations

import atexit
import json
import re
import signal
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from hi.context import now
from hi.menubar.lock import already_running
from hi.menubar.supervisor import Supervisor
from hi.perception import privacy

BACKEND_QUERY = "http://127.0.0.1:8765/query"


def _write_pinned(app: str, title: str, screen: str) -> None:
    now.DIR.mkdir(parents=True, exist_ok=True)
    now.PINNED.write_text(json.dumps({"ts": time.time(), "app": app, "title": title, "screen": screen}))


def capture_screen() -> threading.Thread | None:
    """Screenshot now (synchronously, before any window of ours shows), then OCR + pin it in a thread.
    None when the frontmost app is private or the capture failed."""
    from hi.context.daemon import frontmost
    from hi.perception.screen import _ocr_image

    app, title = frontmost()
    now.PINNED.unlink(missing_ok=True)  # never leave an older screen around as if it were this one
    if privacy.reason_for(app, title) or now.PAUSED.exists():
        return None
    path = Path(tempfile.mktemp(suffix=".png"))
    if subprocess.run(["screencapture", "-x", str(path)], capture_output=True).returncode != 0 or not path.exists():
        return None

    def ocr() -> None:
        try:
            _write_pinned(app, title, "\n".join(_ocr_image(path)))
        finally:
            path.unlink(missing_ok=True)  # the image is never kept

    thread = threading.Thread(target=ocr, daemon=True)
    thread.start()
    return thread


PLOT_RE = re.compile(r"/plots/([\w-]+\.(?:svg|png|jpg|webp))")


def fetch_plot(name: str) -> str | None:
    """Download /plots/<name> from the backend into a temp file the island can load; None if it can't."""
    try:
        with urllib.request.urlopen(f"{BACKEND_QUERY.removesuffix('/query')}/plots/{name}", timeout=15) as response:
            data = response.read()
    except OSError:
        return None
    path = Path(tempfile.gettempdir()) / f"hi-plot-{name}"
    path.write_bytes(data)
    return str(path)


def stream_answer(text: str, on_text, on_status, on_image=None) -> None:
    """POST /query and feed the AG-UI event stream to the callbacks: on_text(delta), on_status(line),
    on_image(local file path) for each diagram or chart a tool made."""
    request = urllib.request.Request(
        BACKEND_QUERY, json.dumps({"text": text, "fresh": True, "origin": "island"}).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:])
            kind = event.get("type")
            if kind == "TEXT_MESSAGE_CONTENT":
                on_text(event.get("delta", ""))
            elif kind == "TOOL_CALL_RESULT" and on_image is not None:
                for name in PLOT_RE.findall(str(event.get("content", ""))):
                    if path := fetch_plot(name):
                        on_image(path)
            elif kind in ("THINKING_START", "RUN_STARTED"):
                on_status("thinking…")
            elif kind == "TOOL_CALL_START":
                on_status(f"using {event.get('toolCallName', 'a tool')}…")
            elif kind == "RUN_ERROR":
                on_text(f"\n⚠️ {event.get('message', 'error')}")


def run_menubar() -> None:
    import objc  # noqa: F401  (PyObjC must be importable before AppKit classes are defined)
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
    from PyObjCTools import AppHelper

    from hi.menubar.island import Delegate

    if already_running():
        print("hi menu bar app is already running.")
        return
    supervisor = Supervisor()
    supervisor.start()  # the context daemon and host bridge live and die with this app
    atexit.register(supervisor.stop)
    for sig in (signal.SIGTERM, signal.SIGHUP):  # `kill`, logout: quit properly so applicationWillTerminate runs
        signal.signal(sig, lambda *_: AppHelper.callAfter(NSApplication.sharedApplication().terminate_, None))
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # menu bar and notch only, no Dock icon
    delegate = Delegate.alloc().init()
    delegate.supervisor = supervisor
    app.setDelegate_(delegate)
    AppHelper.runEventLoop()
