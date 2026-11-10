"""Menu bar companion (hi --menubar): click the icon, type a prompt, and the screen you were just looking at
is the context.

On click the screen is captured BEFORE the popover appears (so the popover is not in the shot), OCR'd on-device
in the background and pinned to ~/.hi/context/pinned.json, which the assistant's prompt picks up (hi/context/now.py).
Enter sends the text to the backend's /query and streams the answer into the popover. Simple commands ("timer 5
min", "bluetooth off") run locally through hi/fast_commands.py with no model. Private apps are never captured.
Right-click the icon for Quit. Native PyObjC, no extra dependencies.
"""

from __future__ import annotations

import fcntl
import json
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import objc
from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory, NSBezelBorder, NSColor, NSEvent, NSEventTypeRightMouseUp,
    NSFont, NSImage, NSMakeRect, NSMenu, NSMenuItem, NSMinYEdge, NSPopover, NSPopoverBehaviorTransient, NSScrollView,
    NSStatusBar, NSTextField, NSTextView, NSVariableStatusItemLength, NSView, NSViewController,
)
from Foundation import NSObject
from PyObjCTools import AppHelper

import hi.config as config
from hi.context import now
from hi.perception import privacy

BACKEND_QUERY = "http://127.0.0.1:8765/query"
LOCK_PATH = Path.home() / ".hi" / "menubar.lock"
WIDTH, HEIGHT = 440, 300
_lock_file = None


def already_running() -> bool:
    """True if another menu bar app holds the lock. Taking the lock here keeps it for this process."""
    global _lock_file
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    return False


def lock_is_free() -> bool:
    """For the launcher: is no menu bar app running? (Does not keep the lock.)"""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True


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


def stream_answer(text: str, on_text, on_status) -> None:
    """POST /query and feed the AG-UI event stream to the callbacks: on_text(delta), on_status(line)."""
    request = urllib.request.Request(
        BACKEND_QUERY, json.dumps({"text": text, "fresh": True}).encode(), {"Content-Type": "application/json"}
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
            elif kind in ("THINKING_START", "RUN_STARTED"):
                on_status("thinking…")
            elif kind == "TOOL_CALL_START":
                on_status(f"using {event.get('toolCallName', 'a tool')}…")
            elif kind == "RUN_ERROR":
                on_text(f"\n⚠️ {event.get('message', 'error')}")


class Delegate(NSObject):
    def applicationDidFinishLaunching_(self, _notification) -> None:
        self.ocr_thread = None
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        button = self.item.button()
        icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_("sparkles", "hi")
        if icon is not None:
            button.setImage_(icon)
        else:
            button.setTitle_("hi")
        button.setTarget_(self)
        button.setAction_("clicked:")
        button.sendActionOn_((1 << 1) | (1 << 3))  # left and right mouse up

        self.field = NSTextField.alloc().initWithFrame_(NSMakeRect(12, HEIGHT - 40, WIDTH - 24, 28))
        self.field.setPlaceholderString_("Ask about what's on your screen…")
        self.field.setTarget_(self)
        self.field.setAction_("submit:")
        self.status = NSTextField.labelWithString_("")
        self.status.setFrame_(NSMakeRect(12, HEIGHT - 62, WIDTH - 24, 16))
        self.status.setFont_(NSFont.systemFontOfSize_(11))
        self.status.setTextColor_(NSColor.secondaryLabelColor())
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(12, 12, WIDTH - 24, HEIGHT - 80))
        scroll.setBorderType_(NSBezelBorder)
        scroll.setHasVerticalScroller_(True)
        self.output = NSTextView.alloc().initWithFrame_(scroll.contentView().bounds())
        self.output.setEditable_(False)
        self.output.setFont_(NSFont.systemFontOfSize_(13))
        self.output.setAutoresizingMask_(2)  # width-sizable
        scroll.setDocumentView_(self.output)

        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, HEIGHT))
        for sub in (self.field, self.status, scroll):
            view.addSubview_(sub)
        controller = NSViewController.alloc().init()
        controller.setView_(view)
        self.popover = NSPopover.alloc().init()
        self.popover.setContentViewController_(controller)
        self.popover.setContentSize_((WIDTH, HEIGHT))
        self.popover.setBehavior_(NSPopoverBehaviorTransient)

    def clicked_(self, sender) -> None:
        event = NSApplication.sharedApplication().currentEvent()
        if event is not None and event.type() == NSEventTypeRightMouseUp:
            menu = NSMenu.alloc().init()
            menu.addItemWithTitle_action_keyEquivalent_("Quit hi", "terminate:", "q")
            self.item.setMenu_(menu)
            self.item.button().performClick_(None)
            self.item.setMenu_(None)
            return
        if self.popover.isShown():
            self.popover.close()
            return
        self.ocr_thread = capture_screen()  # BEFORE showing: our own window must not be in the shot
        self.field.setStringValue_("")
        self.output.setString_("")
        self.status.setStringValue_("screen captured" if self.ocr_thread else "no screen context (private app or paused)")
        self.popover.showRelativeToRect_ofView_preferredEdge_(sender.bounds(), sender, NSMinYEdge)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.field.window().makeFirstResponder_(self.field)

    def submit_(self, _sender) -> None:
        text = str(self.field.stringValue()).strip()
        if not text:
            return
        self.output.setString_("")
        self.status.setStringValue_("…")
        threading.Thread(target=self._answer, args=(text,), daemon=True).start()

    @objc.python_method
    def _answer(self, text: str) -> None:
        from hi.fast_commands import maybe_fast_reply

        try:
            if fast := maybe_fast_reply(text):  # timers, volume, bluetooth...: no model, no backend
                AppHelper.callAfter(self._set, fast[1], "")
                return
            if self.ocr_thread:
                self.ocr_thread.join(timeout=10)  # the pinned screen text must exist before the model reads it
            stream_answer(text, lambda d: AppHelper.callAfter(self._append, d), lambda s: AppHelper.callAfter(self.status.setStringValue_, s))
            AppHelper.callAfter(self.status.setStringValue_, "")
        except Exception as e:
            AppHelper.callAfter(self._set, f"Can't reach hi's backend ({e}). Run `hi` to start it.", "")

    @objc.python_method
    def _set(self, text: str, status: str) -> None:
        self.output.setString_(text)
        self.status.setStringValue_(status)

    @objc.python_method
    def _append(self, delta: str) -> None:
        self.output.setString_(str(self.output.string()) + delta)
        self.output.scrollToEndOfDocument_(None)


def run_menubar() -> None:
    if already_running():
        print("hi menu bar app is already running.")
        return
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # menu bar only, no Dock icon
    delegate = Delegate.alloc().init()
    app.setDelegate_(delegate)
    AppHelper.runEventLoop()
