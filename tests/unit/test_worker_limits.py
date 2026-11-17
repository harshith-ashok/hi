import threading
import time

import hi.config as config
from hi.automation import limits
from hi.automation.worker import Worker


def test_work_runs_one_at_a_time_in_order():
    w, order, release = Worker(), [], threading.Event()
    running = []

    def job(name):
        def run():
            running.append(name)
            assert len(running) == 1  # never two at once
            if name == "a":
                release.wait(2)
            order.append(name)
            running.remove(name)
        return run

    assert w.submit("a", job("a")) and w.submit("b", job("b"))
    release.set()
    deadline = time.time() + 2
    while len(order) < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert order == ["a", "b"]


def test_a_key_already_queued_is_not_queued_again_but_can_run_again_after():
    w, gate, count = Worker(), threading.Event(), []
    assert w.submit("k", lambda: gate.wait(2) or count.append(1))
    assert not w.submit("k", lambda: count.append(2)) and w.pending() == 1
    gate.set()
    deadline = time.time() + 2
    while w.pending() and time.time() < deadline:
        time.sleep(0.01)
    assert w.submit("k", lambda: count.append(3))


def test_a_failing_job_does_not_stop_the_worker():
    w, done = Worker(), threading.Event()
    w.submit("bad", lambda: 1 / 0)
    w.submit("good", done.set)
    assert done.wait(2)


def test_runs_per_hour_counts_only_background_runs(monkeypatch):
    monkeypatch.setattr(config, "MAX_BACKGROUND_RUNS_PER_HOUR", 2)
    now = 1_000_000.0
    limits.record("ui", "sonnet", False, 0, 1.0, now=now - 10)  # a chat turn is not a background run
    limits.record("heartbeat", "sonnet", False, 1, 2.0, now=now - 100)
    assert limits.check_run(now) == ""
    limits.record("schedule", "sonnet", False, 1, 2.0, now=now - 50)
    assert "2 background runs per hour" in limits.check_run(now)
    assert limits.check_run(now + 3600) == ""  # an hour later the window has moved on


def test_over_the_daily_hosted_limit_a_run_moves_to_a_local_tier_or_is_skipped(monkeypatch):
    monkeypatch.setattr(config, "MAX_HOSTED_CALLS_PER_DAY", 2)
    now = time.time()
    monkeypatch.setattr(limits.registry, "is_local", lambda tier: tier == "haiku")
    assert limits.choose_tier("sonnet", now) == "sonnet"  # under the limit
    for _ in range(2):
        limits.record("schedule", "sonnet", True, 0, 1.0, now=now)
    assert limits.choose_tier("sonnet", now) == "haiku"
    assert limits.choose_tier("haiku", now) == "haiku"  # local work is never limited
    monkeypatch.setattr(limits.registry, "is_local", lambda tier: False)
    assert limits.choose_tier("sonnet", now) is None


def test_latency_is_summarised_per_origin():
    now = 2_000_000.0
    limits.record("island", "haiku", False, 0, 1.0, 0.4, now=now - 10)
    limits.record("island", "haiku", False, 0, 3.0, 0.8, now=now - 20)
    limits.record("schedule", "sonnet", False, 2, 20.0, None, now=now - 30)
    got = limits.latency_by_origin(now)
    assert got["island"] == {"runs": 2, "avg_seconds": 2.0, "avg_first_token_s": 0.6}
    assert got["schedule"]["avg_first_token_s"] is None


def test_the_usage_file_is_trimmed_and_a_torn_line_is_ignored():
    path = limits._path()
    path.write_text("not json\n" * 3)
    limits.record("schedule", "sonnet", False, 0, 1.0)
    assert limits.background_runs_last_hour() == 1
