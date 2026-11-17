from datetime import date, datetime

from hi.automation import signals
from hi.capture.schema import Event
from hi.capture.store import save
from hi.memory import proposals

NOW = datetime(2026, 11, 17, 10, 40)
TRACE = """Frontmost: iTerm — pytest (for {n} min; user idle 3 s)
Looks like: debugging a failing test
Text visible on screen:
tests/test_router.py::test_route FAILED
Traceback (most recent call last):
  File "router.py", line 12
KeyError: 'tier'
"""


def test_an_error_on_screen_for_a_long_time_is_a_signal_with_a_stable_key():
    (sig,) = signals.screen_error(TRACE.format(n=22))
    assert sig.screen and sig.weight == 3 and "22+ minutes" in sig.text and "iTerm" in sig.text
    assert signals.screen_error(TRACE.format(n=40))[0].key == sig.key  # same error, same key: no new beat


def test_a_recent_or_error_free_window_is_not_a_signal():
    assert signals.screen_error(TRACE.format(n=5)) == []
    assert signals.screen_error("Frontmost: Safari (for 30 min; user idle 3 s)\nText visible on screen:\nHello world") == []
    assert signals.screen_error("Frontmost: iTerm (for 90 s; user idle 3 s)\nText visible on screen:\nKeyError: 'a'") == []
    assert signals.screen_error("") == []


def test_a_meeting_within_the_hour_is_a_signal_but_a_later_one_is_not(tmp_vault):
    save(Event(text="Acme call", when="2026-11-17T11:20"))
    save(Event(text="Dinner", when="2026-11-17T19:00"))
    save(Event(text="All-day thing", when="2026-11-17"))
    (sig,) = signals.meetings(NOW)
    assert "Acme call" in sig.text and "40 min" in sig.text and sig.key.startswith("meeting:")


def test_proposals_waiting_over_a_day_are_a_signal(tmp_vault):
    pid = proposals.create("heartbeat", "term", "send_email", {})
    created = proposals.get(pid)["created_at"]
    assert signals.proposals_waiting(datetime.fromtimestamp(created + 3600)) == []
    (sig,) = signals.proposals_waiting(datetime.fromtimestamp(created + 25 * 3600))
    assert pid in sig.key and "send_email" in sig.text


def test_deadlines_inside_the_window_only(tmp_vault):
    from hi.capture.schema import Task

    save(Task(text="Send proposal", due="2026-11-18"))
    save(Task(text="Far away", due="2026-12-30"))
    found = signals.deadlines(2, today=date(2026, 11, 17))
    assert len(found) == 1 and "Send proposal" in found[0].text and found[0].weight == 2


def test_collect_skips_a_failing_check_and_orders_by_weight(monkeypatch):
    def broken():
        raise RuntimeError("git not found")

    monkeypatch.setattr(signals, "idle_repos", broken)
    monkeypatch.setattr(signals, "deadlines", lambda *a, **k: [signals.Signal("d", "due", 2)])
    monkeypatch.setattr(signals, "applications", lambda: [signals.Signal("a", "follow up", 1)])
    monkeypatch.setattr(signals, "meetings", lambda now: [])
    monkeypatch.setattr(signals, "proposals_waiting", lambda now: [])
    monkeypatch.setattr(signals, "drop_stuck", lambda now: [])
    assert [s.key for s in signals.collect(NOW)] == ["d", "a"]


def test_screen_signals_only_when_screen_is_included(monkeypatch):
    for name in ("idle_repos", "applications"):
        monkeypatch.setattr(signals, name, lambda: [])
    monkeypatch.setattr(signals, "deadlines", lambda *a, **k: [])
    monkeypatch.setattr(signals, "meetings", lambda now: [])
    monkeypatch.setattr(signals, "proposals_waiting", lambda now: [])
    monkeypatch.setattr(signals, "drop_stuck", lambda now: [])
    monkeypatch.setattr(signals, "diff_watch", lambda: [])
    described = TRACE.format(n=30)
    assert signals.collect(NOW, described, include_screen=False) == []
    assert [s.screen for s in signals.collect(NOW, described, include_screen=True)] == [True]


def test_the_suggestion_engine_still_produces_the_same_suggestions(monkeypatch, tmp_vault):
    from hi.capture.schema import Task
    from hi.suggest import engine

    save(Task(text="Send proposal", due=date.today().isoformat()))
    monkeypatch.setattr(signals, "idle_repos", lambda: [])
    (s,) = engine._deadline_suggestions()
    assert s.message.startswith("'Send proposal' is due") and s.key.startswith("deadline:")
