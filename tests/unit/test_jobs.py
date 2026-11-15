import threading
import time

from hi.core import jobs


def test_run_background_runs_the_function():
    done = threading.Event()
    jobs.run_background("t", done.set).join(2)
    assert done.is_set()


def test_a_failing_job_does_not_raise_or_kill_the_thread():
    def boom():
        raise RuntimeError("x")

    thread = jobs.run_background("t", boom)
    thread.join(2)
    assert not thread.is_alive()


def test_every_repeats_until_stopped():
    stop = threading.Event()
    count = []
    jobs.every("t", 0.01, lambda: count.append(1), stop=stop)
    deadline = time.time() + 2
    while len(count) < 3 and time.time() < deadline:
        time.sleep(0.01)
    stop.set()
    assert len(count) >= 3


def test_every_keeps_going_after_a_failure_and_backs_off(monkeypatch):
    waits = []

    class FakeStop(threading.Event):
        def wait(self, timeout=None):
            waits.append(timeout)
            if len(waits) >= 4:
                return True
            return False

    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("down")

    jobs.every("t", 1.0, flaky, max_backoff_s=3.0, stop=FakeStop()).join(2)
    assert waits == [2.0, 3.0, 1.0, 1.0]  # doubled, capped at 3.0, reset after the success
