"""Background jobs with one owner: named, logged, and isolated from each other.

`run_background` runs a function once on a daemon thread. `every` repeats it, and after a failure
waits longer each time (up to a cap) so a broken job doesn't hammer a down service. Nothing here
runs at import: processes start their jobs explicitly (see hi/startup.py).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from hi.core import health

log = logging.getLogger(__name__)

last_run: dict[str, float] = {}  # job name -> when it last finished (shown by GET /health)


def run_background(name: str, fn: Callable[[], object]) -> threading.Thread:
    def work() -> None:
        try:
            fn()
        except Exception:  # boundary: a background job must never take the process down
            log.exception("background job %s failed", name)

    thread = threading.Thread(target=work, name=name, daemon=True)
    thread.start()
    return thread


def every(
    name: str,
    interval_s: float,
    fn: Callable[[], object],
    *,
    max_backoff_s: float = 3600.0,
    stop: threading.Event | None = None,
) -> threading.Thread:
    """Run `fn` now, then again every `interval_s`. Each consecutive failure doubles the wait,
    capped at `max_backoff_s`; a success resets it. Set `stop` to end the loop."""
    stop = stop or threading.Event()

    def loop() -> None:
        failures = 0
        while not stop.is_set():
            try:
                fn()
                failures = 0
                health.mark_ok(f"job:{name}")
            except Exception as e:
                failures += 1
                log.exception("job %s failed (%d in a row)", name, failures)
                health.mark_down(f"job:{name}", e, cooldown_s=0.0)
            finally:
                last_run[name] = time.time()
            wait = min(interval_s * (2**failures), max_backoff_s) if failures else interval_s
            if stop.wait(wait):
                return

    thread = threading.Thread(target=loop, name=name, daemon=True)
    thread.start()
    return thread
