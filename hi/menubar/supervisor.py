"""The menu bar app owns the Mac-side helpers: it starts them, restarts one that dies, and stops them when it
quits, so closing the menu bar app stops everything it brought up.

Helpers: the context daemon (screen/app awareness and nudges) and the host bridge (how the Docker backend
reaches the Mac). They are children of the app (not detached) and also exit on their own if the app dies without
cleaning up, even on a force-kill: see `die_with_parent`, which they run when HI_SUPERVISED is set.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

SUPERVISED_ENV = "HI_SUPERVISED"
RESTART_LIMIT = 5  # a helper that keeps crashing is left down instead of restarting forever
HELPERS = {
    "host bridge": ([sys.executable, "-m", "hi.host_bridge"], "bridge.log", "hi.host_bridge"),
    "context daemon": ([sys.executable, "-m", "hi.cli", "--context-daemon"], "context.log", "hi.cli --context-daemon"),
}


def die_with_parent() -> None:
    """In a helper: exit when the process that started us is gone. A no-op unless the menu bar app launched us
    (HI_SUPERVISED), so running a daemon by hand from a terminal still works."""
    if not os.environ.get(SUPERVISED_ENV):
        return
    parent = os.getppid()

    def watch() -> None:
        while True:
            time.sleep(2)
            if os.getppid() != parent:  # re-parented to launchd: the app is gone
                os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


class Supervisor:
    def __init__(self) -> None:
        self.children: dict[str, subprocess.Popen] = {}
        self.restarts: dict[str, int] = {}
        self.stopping = False

    def start(self) -> None:
        for _name, (_cmd, _log, pattern) in HELPERS.items():  # copies left by an older launcher would double-run
            subprocess.run(["pkill", "-f", pattern], capture_output=True)
        time.sleep(0.5)
        for name in HELPERS:
            self._spawn(name)

    def _spawn(self, name: str) -> None:
        cmd, log_name, _pattern = HELPERS[name]
        log_path = Path.home() / ".hi" / log_name
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "ab") as log:
            self.children[name] = subprocess.Popen(
                cmd, stdout=log, stderr=log, stdin=subprocess.DEVNULL, env={**os.environ, SUPERVISED_ENV: "1"}
            )

    def check(self) -> None:
        """Restart a helper that has exited (called from the app's timer)."""
        if self.stopping:
            return
        for name, child in list(self.children.items()):
            if child.poll() is not None and self.restarts.get(name, 0) < RESTART_LIMIT:
                self.restarts[name] = self.restarts.get(name, 0) + 1
                print(f"{name} exited ({child.returncode}); restarting", flush=True)
                self._spawn(name)

    def stop(self) -> None:
        """Stop every helper. Safe to call twice."""
        self.stopping = True
        for child in self.children.values():
            if child.poll() is None:
                child.terminate()
        deadline = time.time() + 3
        for child in self.children.values():
            try:
                child.wait(timeout=max(0.0, deadline - time.time()))
            except subprocess.TimeoutExpired:
                child.kill()
