import json
from datetime import datetime
from types import SimpleNamespace

import pytest

import hi.config as config
from hi.automation import heartbeat, limits, signals
from hi.automation.deliver import Delivered
from hi.memory import proposals, reports

NOW = datetime(2026, 11, 17, 10, 40)
ERR = signals.Signal("error:keyerror", "An error has been on screen for 20+ minutes (iTerm): KeyError: 'tier' in router.py", 3, True)
MEET = signals.Signal("meeting:acme", "'Acme call' starts at 11:20 (40 min).", 2)


class Runner:
    def __init__(self, answers=None, error="", proposals=()):
        self.calls, self.answers, self.error, self.proposals = [], list(answers or ["# Fix for KeyError\n\nIt is a missing key."]), error, list(proposals)

    def __call__(self, text, **kw):
        self.calls.append({"text": text, **kw})
        answer = self.answers[min(len(self.calls), len(self.answers)) - 1] if not self.error else ""
        return SimpleNamespace(answer=answer, error=self.error, proposals=self.proposals, notes=[])


class Sink:
    def __init__(self):
        self.items = []

    def __call__(self, d):
        self.items.append(d)
        return Delivered(f"r{len(self.items)}" if d.body else "", "shown")


def reply(*decisions):
    return json.dumps([{"action": a, "task": t, "why": "w", "evidence": e} for a, t, e in decisions])


@pytest.fixture
def env(tmp_vault, monkeypatch):
    monkeypatch.setattr(config, "HEARTBEAT", True)
    monkeypatch.setattr(config, "HEARTBEAT_HOURS", "08-22")
    monkeypatch.setattr(config, "MAX_BACKGROUND_RUNS_PER_HOUR", 6)
    monkeypatch.setattr(heartbeat.registry, "is_local", lambda tier: True)
    monkeypatch.setattr(limits.registry, "is_local", lambda tier: True)
    found = [ERR, MEET]
    seen = {}
    monkeypatch.setattr(heartbeat.signals, "collect", lambda now, described="", include_screen=False: seen.update(screen=include_screen) or [s for s in found if include_screen or not s.screen])
    monkeypatch.setattr(heartbeat.proposals, "expire_old", lambda: 0)
    from hi.context import now as live

    monkeypatch.setattr(live, "recent_activity", lambda minutes=30: "- iTerm, 22 min")  # never read the real history
    monkeypatch.setattr(heartbeat.context_pack.registry, "is_local", lambda tier: True)
    return SimpleNamespace(found=found, seen=seen)


def run(env, triage, runner=None, sink=None, now=NOW, **kw):
    runner, sink = runner or Runner(), sink or Sink()
    result = heartbeat.beat(now, runner, sink, described=kw.pop("described", "Frontmost: iTerm (for 20 min; idle 1 s)"),
                            triage_fn=triage, ignored=kw.pop("ignored", []))
    return result, runner, sink


# --- gates ------------------------------------------------------------------------------------------------------

def test_active_hours_including_a_window_that_wraps_midnight():
    at = lambda h: datetime(2026, 11, 17, h, 0)
    assert heartbeat.in_active_hours(at(8), "08-22") and heartbeat.in_active_hours(at(21), "08-22")
    assert not heartbeat.in_active_hours(at(22), "08-22") and not heartbeat.in_active_hours(at(7), "08-22")
    assert heartbeat.in_active_hours(at(23), "22-06") and heartbeat.in_active_hours(at(5), "22-06") and not heartbeat.in_active_hours(at(12), "22-06")
    assert heartbeat.in_active_hours(at(3), "garbage")  # a bad setting must not silently stop the heartbeat


def test_off_outside_hours_and_over_the_run_limit_cost_nothing(env, monkeypatch):
    never = lambda prompt: pytest.fail("called the model")
    monkeypatch.setattr(config, "HEARTBEAT", False)
    assert run(env, never)[0].skipped == "off"
    monkeypatch.setattr(config, "HEARTBEAT", True)
    assert run(env, never, now=datetime(2026, 11, 17, 3, 0))[0].skipped == "outside active hours"
    monkeypatch.setattr(config, "MAX_BACKGROUND_RUNS_PER_HOUR", 1)
    limits.record("schedule", "sonnet", False, 0, 1.0, now=NOW.timestamp() - 60)
    assert "limit" in run(env, never)[0].skipped


def test_no_signals_means_no_model_call(env):
    env.found.clear()
    result, runner, sink = run(env, lambda p: pytest.fail("called the model"))
    assert result.skipped == "no signals" and runner.calls == [] and sink.items == []


def test_the_same_situation_twice_costs_no_second_model_call(env):
    triage_calls = []
    first, _, _ = run(env, lambda p: triage_calls.append(p) or reply())
    later = datetime(2026, 11, 17, 11, 10)
    second, runner, sink = run(env, lambda p: pytest.fail("called the model"), now=later)
    assert len(triage_calls) == 1 and second.skipped == "unchanged" and second.fingerprint == first.fingerprint
    env.found.append(signals.Signal("deadline:x", "'Report' is due 2026-11-18 (1d).", 2))
    third, _, _ = run(env, lambda p: reply(), now=datetime(2026, 11, 17, 11, 40))
    assert third.skipped == ""  # a new signal is a new situation


def test_a_beat_that_failed_is_tried_again_not_remembered_as_handled(env):
    def down(prompt):
        raise RuntimeError("ollama down")

    failed, _, sink = run(env, down)
    assert failed.skipped.startswith("failed") and sink.items == []
    retried, _, _ = run(env, lambda p: reply(), now=datetime(2026, 11, 17, 11, 10))
    assert retried.skipped == ""  # same signals, but the failure did not mark them handled


# --- triage -----------------------------------------------------------------------------------------------------

def test_decisions_must_quote_a_real_signal(env):
    good = ("prepare", "Summarise the KeyError and propose a fix", "KeyError: 'tier' in router.py")
    invented = ("prepare", "Fix the database", "the production database is on fire")
    too_short = ("prepare", "Do a thing", "KeyError")
    result, _, _ = run(env, lambda p: reply(good, invented, too_short))
    assert [d.task for d in result.decisions] == ["Summarise the KeyError and propose a fix"]


def test_bad_replies_give_no_decisions_and_none_is_not_an_action(env):
    for bad in ("I think you should relax", "[not json", "{}", '[{"action": "none"}]', '[{"action": "prepare"}]', '"x"', "[1, 2]"):
        assert run(env, lambda p, b=bad: b)[0].decisions == [], bad


def test_at_most_three_decisions(env):
    many = reply(*[("prepare", f"task {i}", "Acme call' starts at 11:20") for i in range(6)])
    assert len(run(env, lambda p: many)[0].decisions) == 3


def test_the_prompt_carries_the_signals_what_was_prepared_and_what_was_ignored(env):
    reports.write_report("heartbeat", "Prepared the PR 41 summary", "x", now=NOW)
    seen = []
    run(env, lambda p: seen.append(p) or reply(), ignored=["Want me to look at the build?"])
    prompt = seen[0]
    assert "KeyError: 'tier' in router.py" in prompt and "Acme call" in prompt
    assert "Prepared the PR 41 summary" in prompt and "Want me to look at the build?" in prompt


def test_screen_signals_are_left_out_when_the_model_is_not_local(env, monkeypatch):
    monkeypatch.setattr(heartbeat.registry, "is_local", lambda tier: False)
    seen = []
    result, _, _ = run(env, lambda p: seen.append(p) or reply())
    assert env.seen["screen"] is False and "KeyError" not in seen[0] and "Acme call" in seen[0]
    assert "screen left out" in result.notes


def test_a_paused_screen_leaves_the_screen_out_but_not_the_vault(env):
    seen = []
    run(env, lambda p: seen.append(p) or reply(), described="Screen context is paused or hidden right now (private app)")
    assert env.seen["screen"] is False and "Acme call" in seen[0]


# --- preparing and delivering -------------------------------------------------------------------------------------

def test_one_prepared_item_is_one_delivery_that_is_shown(env):
    runner = Runner()
    result, _, sink = run(env, lambda p: reply(("prepare", "Summarise the KeyError", "KeyError: 'tier' in router.py")), runner)
    (call,) = runner.calls
    assert call["origin"] == "heartbeat" and call["tier"] == "sonnet" and not call["policy"].interactive
    assert call["policy"].allow_web and call["policy"].allow_screen and call["profile"] == "heartbeat.prepare"
    assert "Context (assembled automatically" in call["context"]
    (d,) = sink.items
    assert d.headline == "Fix for KeyError" and d.popup == "yes" and d.origin == "heartbeat" and result.delivered == ["r1"]


def test_without_a_local_model_the_run_may_not_see_the_screen(env, monkeypatch):
    monkeypatch.setattr(heartbeat.registry, "is_local", lambda tier: False)
    monkeypatch.setattr(limits.registry, "is_local", lambda tier: False)
    monkeypatch.setattr(heartbeat.context_pack.registry, "is_local", lambda tier: False)
    _, runner, _ = run(env, lambda p: reply(("prepare", "Prep the Acme call", "'Acme call' starts at 11:20")))
    assert runner.calls[0]["policy"].allow_screen is False


def test_several_items_make_several_quiet_reports_and_one_digest(env):
    runner = Runner(answers=["# First thing\n\nA.", "# Second thing\n\nB."])
    decisions = reply(("prepare", "Do first", "KeyError: 'tier' in router.py"), ("prepare", "Do second", "'Acme call' starts at 11:20"))
    result, _, sink = run(env, lambda p: decisions, runner)
    *items, digest = sink.items
    assert [i.popup for i in items] == ["no", "no"] and digest.kind == "digest" and digest.popup == "yes"
    assert digest.headline == "2 things ready: First thing" and "First thing (report r1)" in digest.body
    assert digest.dedupe_key == f"heartbeat:{result.fingerprint}"
    assert len(result.delivered) == 3


def test_proposals_from_a_prepared_item_travel_with_its_delivery(env):
    pid = proposals.create("heartbeat", "term", "send_email", {"to": "bob@acme.com"})
    _, _, sink = run(env, lambda p: reply(("prepare", "Draft the follow-up", "'Acme call' starts at 11:20")), Runner(proposals=[pid]))
    assert sink.items[0].proposals == (pid,)


def test_a_nudge_is_one_line_and_only_when_nothing_was_prepared(env):
    _, runner, sink = run(env, lambda p: reply(("nudge", "Acme call in 40 minutes", "'Acme call' starts at 11:20")))
    assert runner.calls == [] and [(d.headline, d.body) for d in sink.items] == [("Acme call in 40 minutes", "")]
    both = reply(("nudge", "Acme call soon", "'Acme call' starts at 11:20"), ("prepare", "Prep it", "'Acme call' starts at 11:20"))
    env.found.append(signals.Signal("extra", "x"))
    _, runner, sink = run(env, lambda p: both, now=datetime(2026, 11, 17, 12, 0))
    assert len(runner.calls) == 1 and len(sink.items) == 1 and sink.items[0].body


def test_a_run_that_fails_to_prepare_delivers_nothing_and_says_why(env):
    result, _, sink = run(env, lambda p: reply(("prepare", "Do it", "'Acme call' starts at 11:20")), Runner(error="timed out after 180s"))
    assert sink.items == [] and any("timed out" in n for n in result.notes)


def test_hitting_the_run_limit_midway_stops_preparing(env, monkeypatch):
    monkeypatch.setattr(config, "MAX_BACKGROUND_RUNS_PER_HOUR", 1)
    decisions = reply(("prepare", "A", "KeyError: 'tier' in router.py"), ("prepare", "B", "'Acme call' starts at 11:20"))
    runner = Runner()
    orig = runner.__call__
    runner_calls = []

    def counted(text, **kw):
        out = orig(text, **kw)
        limits.record("heartbeat", "sonnet", False, 0, 1.0, now=NOW.timestamp())
        return out

    result, _, sink = run(env, lambda p: decisions, counted)
    assert len(runner.calls) == 1 and any("limit" in n for n in result.notes)


def test_the_report_exists_even_when_the_popup_is_over_budget(tmp_vault):
    from hi.automation.deliver import deliver

    out = deliver(heartbeat.Delivery("3 things ready", body="## Prepared", kind="digest", origin="heartbeat"),
                  post=lambda *a: "budget")
    assert out.status == "budget" and reports.read_report(out.report_id)


def test_each_beat_is_logged_with_what_it_decided(env, tmp_vault):
    run(env, lambda p: reply(("prepare", "Summarise it", "KeyError: 'tier' in router.py")))
    (log,) = (tmp_vault / "hi" / "heartbeat").glob("*.jsonl")
    entry = json.loads(log.read_text().splitlines()[-1])
    assert entry["handled"] and entry["decisions"][0]["task"] == "Summarise it" and "error:keyerror" in entry["signals"]


# --- the job ---------------------------------------------------------------------------------------------------

def test_the_first_beat_comes_soon_and_later_ones_every_interval(monkeypatch):
    monkeypatch.setattr(heartbeat, "_last_beat", None)
    monkeypatch.setattr(config, "HEARTBEAT_EVERY", 1800)
    queued = []
    submit = lambda key, fn: queued.append(key) or True
    t0 = datetime(2026, 11, 17, 9, 0)
    assert not heartbeat.maybe_beat(None, submit, t0)
    assert not heartbeat.maybe_beat(None, submit, datetime(2026, 11, 17, 9, 4))
    assert heartbeat.maybe_beat(None, submit, datetime(2026, 11, 17, 9, 5))
    assert not heartbeat.maybe_beat(None, submit, datetime(2026, 11, 17, 9, 20))
    assert heartbeat.maybe_beat(None, submit, datetime(2026, 11, 17, 9, 36))
    assert queued == ["heartbeat", "heartbeat"]


def test_the_interval_is_read_live(monkeypatch):
    monkeypatch.setattr(heartbeat, "_last_beat", datetime(2026, 11, 17, 9, 0).timestamp())
    monkeypatch.setattr(config, "HEARTBEAT_EVERY", 600)
    assert heartbeat.maybe_beat(None, lambda k, f: True, datetime(2026, 11, 17, 9, 11))
