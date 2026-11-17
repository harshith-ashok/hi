from datetime import datetime
from types import SimpleNamespace

import pytest

import hi.config as config
from hi.automation import limits, scheduler
from hi.automation.deliver import Delivered
from hi.memory import schedules
from hi.memory.schedules import Schedule

MON_8 = datetime(2026, 11, 16, 8, 0)  # a Monday


class Runner:
    """A fake headless runner that records calls."""

    def __init__(self, answer="# Brief\n\nThree things today.", error="", proposals=()):
        self.calls, self.answer, self.error, self.proposals = [], answer, error, list(proposals)

    def __call__(self, text, **kw):
        self.calls.append({"text": text, **kw})
        return SimpleNamespace(answer=self.answer, error=self.error, proposals=self.proposals, notes=[])


class Sink:
    def __init__(self):
        self.items = []

    def __call__(self, d):
        self.items.append(d)
        return Delivered("rid-1" if d.body else "", "shown")


def now_run(s, run, sink, at, **kw):
    return scheduler.tick(at, run, submit=lambda key, fn: fn(), deliver_fn=sink, **kw)


def make(**kw):
    base = dict(id="brief", when="0 8 * * 1-5", prompt="Brief me.", created="2026-11-15T20:00:00")
    base.update(kw)
    s = Schedule(**base)
    schedules.save(s)
    return s


@pytest.fixture(autouse=True)
def _usage(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "state_dir", lambda: tmp_path)  # usage.jsonl stays out of ~/.hi
    monkeypatch.setattr(limits.registry, "is_local", lambda tier: True)


# --- the timetable ---------------------------------------------------------------------------------------------

def test_cron_and_once_are_validated():
    assert schedules.validate_when("0 8 * * 1-5") == ""
    assert schedules.validate_when("once 2026-11-20T15:00") == ""
    assert "five cron fields" in schedules.validate_when("every morning")
    assert "five cron fields" in schedules.validate_when("0 8 * *")
    assert "once 2026-11-20T15:00" in schedules.validate_when("once tomorrow")


def test_next_fires_are_in_local_time_and_skip_the_weekend():
    s = Schedule("b", "0 8 * * 1-5", "x")
    fires = schedules.next_fires(s, 3, datetime(2026, 11, 20, 9, 0))  # Friday 09:00
    assert [schedules.say_time(f) for f in fires] == ["Mon 23 Nov 08:00", "Tue 24 Nov 08:00", "Wed 25 Nov 08:00"]


def test_a_note_round_trips_and_edits_in_obsidian_are_read_on_the_next_tick(tmp_vault):
    make(context=("vault", "screen"), allow=("create_note",), allow_web=True, catch_up_s=1800)
    got = schedules.load("brief")
    assert got.context == ("vault", "screen") and got.allow == ("create_note",) and got.allow_web and got.catch_up_s == 1800
    assert got.when == "0 8 * * 1-5" and got.prompt == "Brief me."
    path = tmp_vault / "hi" / "schedules" / "brief.md"
    path.write_text(path.read_text().replace("Brief me.", "Brief me, and be quick."))  # edited by hand
    run, sink = Runner(), Sink()
    now_run(None, run, sink, MON_8)
    assert run.calls[0]["text"] == "Brief me, and be quick."


# --- ticking ----------------------------------------------------------------------------------------------------

def test_a_due_task_runs_under_the_unattended_policy_and_its_result_is_delivered(tmp_vault):
    make(tier="haiku", persona="term", allow_web=True)
    run, sink = Runner(), Sink()
    assert now_run(None, run, sink, MON_8) == ["2026-11-16T08:00:00"]
    call = run.calls[0]
    assert call["origin"] == "schedule" and call["tier"] == "haiku" and call["persona"] == "term"
    assert not call["policy"].interactive and call["policy"].allow_web and not call["policy"].allow_screen
    assert "Context (assembled automatically" in call["context"]
    (d,) = sink.items
    assert d.headline == "Brief" and d.kind == "digest" and d.body.startswith("# Brief")
    assert d.dedupe_key == "schedule:brief:2026-11-16T08:00:00"
    assert schedules.runs("brief")[0]["status"] == "done" and schedules.runs("brief")[0]["report"] == "rid-1"


def test_nothing_runs_before_the_first_slot_after_creation(tmp_vault):
    make(created="2026-11-16T10:00:00")  # created after today's 8:00
    run, sink = Runner(), Sink()
    assert now_run(None, run, sink, datetime(2026, 11, 16, 10, 5)) == []
    assert now_run(None, run, sink, datetime(2026, 11, 17, 8, 0)) == ["2026-11-17T08:00:00"]


def test_a_slot_never_runs_twice(tmp_vault):
    make()
    run, sink = Runner(), Sink()
    now_run(None, run, sink, MON_8)
    assert now_run(None, run, sink, MON_8) == [] and now_run(None, run, sink, datetime(2026, 11, 16, 8, 1)) == []
    assert len(run.calls) == 1


def test_a_disabled_schedule_does_not_run(tmp_vault):
    make(enabled=False)
    run, sink = Runner(), Sink()
    assert now_run(None, run, sink, MON_8) == [] and run.calls == []


def test_waking_up_runs_only_the_newest_slot_and_records_the_older_ones_as_missed(tmp_vault):
    make(when="0 * * * *", created="2026-11-16T05:30:00", catch_up_s=7200)  # hourly
    run, sink = Runner(), Sink()
    started = now_run(None, run, sink, datetime(2026, 11, 16, 9, 10))
    assert started == ["2026-11-16T09:00:00"] and len(run.calls) == 1
    status = {r["slot"]: r["status"] for r in schedules.runs("brief", 20)}
    assert status["2026-11-16T06:00:00"] == status["2026-11-16T07:00:00"] == status["2026-11-16T08:00:00"] == "missed"
    assert status["2026-11-16T09:00:00"] == "done"


def test_a_slot_too_far_in_the_past_is_missed_not_run(tmp_vault):
    make(catch_up_s=3600)
    run, sink = Runner(), Sink()
    assert now_run(None, run, sink, datetime(2026, 11, 16, 11, 0)) == [] and run.calls == []
    assert schedules.runs("brief")[0]["status"] == "missed"
    assert now_run(None, run, sink, datetime(2026, 11, 16, 11, 1)) == []  # and is not retried every tick


def test_a_reminder_is_delivered_as_written_with_no_model_call(tmp_vault):
    make(id="stand", when="55 9 * * 1-5", kind="reminder", prompt="Stand-up in 5 minutes")
    run, sink = Runner(), Sink()
    now_run(None, run, sink, datetime(2026, 11, 16, 9, 55))
    assert run.calls == []
    (d,) = sink.items
    assert d.kind == "reminder" and d.headline == "Stand-up in 5 minutes"


def test_a_reminder_respects_its_deliver_mode(tmp_vault):
    make(id="quiet", when="55 9 * * 1-5", kind="reminder", prompt="x", deliver="silent")
    sink = Sink()
    now_run(None, Runner(), sink, datetime(2026, 11, 16, 9, 55))
    assert sink.items[0].popup == "no"


def test_a_failed_run_is_recorded_and_delivered_as_a_failure(tmp_vault):
    make()
    run, sink = Runner(answer="", error="model host unreachable"), Sink()
    now_run(None, run, sink, MON_8)
    (d,) = sink.items
    assert d.kind == "failure" and "model host unreachable" in d.headline
    r = schedules.runs("brief")[0]
    assert r["status"] == "failed" and "unreachable" in r["error"]


def test_a_runner_that_raises_is_a_failure_not_a_crash(tmp_vault):
    make()
    sink = Sink()

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    scheduler.tick(MON_8, boom, submit=lambda k, fn: fn(), deliver_fn=sink)
    assert schedules.runs("brief")[0]["status"] == "failed" and sink.items[0].kind == "failure"


def test_a_one_time_schedule_turns_itself_off_after_it_runs(tmp_vault):
    make(id="once-a", when="once 2026-11-16T15:00", created="2026-11-16T09:00:00")
    run, sink = Runner(), Sink()
    now_run(None, run, sink, datetime(2026, 11, 16, 15, 0))
    assert len(run.calls) == 1 and schedules.load("once-a").enabled is False


def test_a_one_time_schedule_that_was_missed_is_also_turned_off(tmp_vault):
    make(id="once-a", when="once 2026-11-16T15:00", created="2026-11-16T09:00:00", catch_up_s=60)
    run, sink = Runner(), Sink()
    now_run(None, run, sink, datetime(2026, 11, 16, 18, 0))
    assert run.calls == [] and schedules.load("once-a").enabled is False


def test_one_bad_note_does_not_stop_the_others_and_is_reported(tmp_vault):
    make()
    (tmp_vault / "hi" / "schedules" / "typo.md").write_text("---\nwhen: every morning\n---\n\nDo it.\n")
    errors = []
    assert [s.id for s in schedules.load_all(errors)] == ["brief"]
    assert "typo.md" in errors[0] and "five cron fields" in errors[0]
    run, sink = Runner(), Sink()
    assert len(now_run(None, run, sink, MON_8)) == 1


def test_a_proposal_from_a_run_is_attached_to_the_delivery(tmp_vault):
    make()
    run, sink = Runner(proposals=["P-1a2b"]), Sink()
    now_run(None, run, sink, MON_8)
    assert sink.items[0].proposals == ("P-1a2b",) and sink.items[0].popup == "yes"


def test_deliver_modes_decide_the_popup(tmp_vault):
    for mode, expected, proposals in [("notify", "yes", []), ("report", "no", []), ("report", "approvals", ["P-1"]), ("silent", "no", ["P-1"])]:
        s = Schedule("m", "0 8 * * *", "x", deliver=mode)
        assert scheduler._popup(s, tuple(proposals)) == expected


def test_screen_is_only_allowed_for_a_local_model(tmp_vault, monkeypatch):
    s = Schedule("m", "0 8 * * *", "x", context=("vault", "screen"), tier="sonnet")
    assert scheduler.policy_for(s).allow_screen
    monkeypatch.setattr(scheduler.registry, "is_local", lambda tier: False)
    assert not scheduler.policy_for(s).allow_screen


def test_the_hourly_run_limit_skips_and_says_so_once(tmp_vault, monkeypatch):
    make(when="0 * * * *", created="2026-11-16T05:00:00")
    monkeypatch.setattr(config, "MAX_BACKGROUND_RUNS_PER_HOUR", 1)
    limits.record("heartbeat", "sonnet", False, 0, 1.0, now=MON_8.timestamp())
    run, sink = Runner(), Sink()
    now_run(None, run, sink, datetime(2026, 11, 16, 8, 30))
    assert run.calls == [] and schedules.runs("brief")[0]["status"] == "skipped"
    assert sink.items[0].kind == "failure" and "limit" in sink.items[0].headline


def test_without_a_runner_a_task_fails_visibly_but_a_reminder_still_works(tmp_vault, monkeypatch):
    monkeypatch.setattr(scheduler, "_run_turn", None)
    make()
    make(id="r", kind="reminder", prompt="hi", when="0 8 * * 1-5")
    sink = Sink()
    scheduler.tick(MON_8, None, submit=lambda k, fn: fn(), deliver_fn=sink)
    runs = {r["id"]: r["status"] for r in schedules.runs()}
    assert runs == {"brief": "failed", "r": "done"}


def test_run_now_starts_a_schedule_outside_its_timetable(tmp_vault, monkeypatch):
    make()
    run, sink = Runner(), Sink()
    monkeypatch.setattr(scheduler, "_run_turn", run)
    monkeypatch.setattr(scheduler, "deliver", sink)
    assert scheduler.run_now("brief", submit=lambda key, fn: fn() or True, deliver_fn=sink) == "Started 'brief'."
    assert len(run.calls) == 1 and scheduler.run_now("nope") == "No schedule called 'nope'."
    assert schedules.last_slot("brief") is None  # a manual run does not disturb the timetable
