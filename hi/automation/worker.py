"""One worker for all background runs, so two of them never load the model host at the same time.

`submit(key, fn)` queues `fn`; a key that is already queued or running is not queued again (a slow run must not pile up
copies of itself). Work runs one at a time, in order, on a daemon thread that starts with the first submit.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable

log = logging.getLogger(__name__)


class Worker:
    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[str, Callable[[], object]]] = queue.Queue()
        self._keys: set[str] = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def submit(self, key: str, fn: Callable[[], object]) -> bool:
        """Queue `fn`. False if `key` is already waiting or running."""
        with self._lock:
            if key in self._keys:
                return False
            self._keys.add(key)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="background-worker", daemon=True)
                self._thread.start()
        self._queue.put((key, fn))
        return True

    def pending(self) -> int:
        with self._lock:
            return len(self._keys)

    def _loop(self) -> None:
        while True:
            key, fn = self._queue.get()
            try:
                fn()
            except Exception:  # boundary: one failing run must not stop the worker
                log.exception("background work %s failed", key)
            finally:
                with self._lock:
                    self._keys.discard(key)


_worker: Worker | None = None
_worker_lock = threading.Lock()


def get_worker() -> Worker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = Worker()
        return _worker
