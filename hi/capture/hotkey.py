"""Global quick-capture hotkey: works regardless of which pane/persona is
focused, not just inside a `hi` session, so it's a standalone long-lived
process rather than something started inside a tmux `hi` pane. Run it with:

    hi --capture-daemon

Needs macOS Accessibility (or Input Monitoring) permission granted to
whatever process runs this (Terminal/iTerm) — pynput's global listener
silently receives no key events at all without it, rather than raising an
error, so if the hotkey never fires, that's the first thing to check:
System Settings > Privacy & Security > Accessibility.

On trigger, prompts for text via a native macOS dialog (osascript) rather
than a custom GUI window — the same "use the OS's own UI, no new GUI
toolkit" pattern hi/agents/butler/butler.py already uses for System
Events calls — and writes it straight to hi/tasks/inbox/ untriaged
(hi/capture/inbox.py). hi/capture/triage.py classifies it into a real
Task/Event the next time any `hi` persona starts.
"""

from __future__ import annotations

import subprocess

from pynput import keyboard

from hi.capture.inbox import write_inbox_item

DEFAULT_HOTKEY = "<cmd>+<shift>+<space>"


def _prompt_for_text() -> str | None:
    script = 'display dialog "Quick capture:" default answer "" with title "hi"'
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return None  # user cancelled the dialog
    # `display dialog ... default answer "x"` prints "text returned:x" to
    # stdout — nothing else uses that exact prefix, so a plain strip is enough.
    output = result.stdout.strip()
    prefix = "text returned:"
    return output[len(prefix) :] if output.startswith(prefix) else None


def run_capture_daemon(hotkey: str = DEFAULT_HOTKEY) -> None:
    def on_activate() -> None:
        text = _prompt_for_text()
        if text and text.strip():
            path = write_inbox_item(text.strip())
            print(f"Captured to {path}")

    print(f"Quick-capture daemon listening for {hotkey}. Ctrl-C to stop.")
    with keyboard.GlobalHotKeys({hotkey: on_activate}) as listener:
        listener.join()
