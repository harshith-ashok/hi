import threading

import pytest

import hi.config as config
from hi.core import health, jobs
from hi.llm import registry
from hi.memory import records, transcript
from hi.memory.records import TurnRecord, record_turn


def test_a_job_that_succeeds_is_up_and_one_that_fails_is_reported_with_its_error():
    health.reset()
    done = threading.Event()
    stop = threading.Event()
    jobs.every("ok-job", 0.01, lambda: done.set() or stop.set(), stop=stop).join(2)
    assert health.snapshot()["job:ok-job"]["ok"] and "ok-job" in jobs.last_run

    stop2 = threading.Event()

    def boom():
        stop2.set()
        raise KeyError("nope")

    jobs.every("bad-job", 0.01, boom, stop=stop2).join(2)
    snap = health.snapshot()["job:bad-job"]
    assert not snap["ok"] and "nope" in snap["error"]


def test_one_failing_job_does_not_stop_another():
    health.reset()
    other = threading.Event()
    stop_bad, stop_good = threading.Event(), threading.Event()
    jobs.every("bad2", 0.01, lambda: (_ for _ in ()).throw(KeyError("x")), stop=stop_bad)
    jobs.every("good2", 0.01, lambda: other.set(), stop=stop_good)
    assert other.wait(2)
    stop_bad.set(), stop_good.set()


def test_is_local_is_false_when_any_model_in_the_chain_is_hosted(monkeypatch):
    monkeypatch.setattr(config, "HAIKU_MODEL", "gemma4:e4b")
    monkeypatch.setattr(config, "SONNET_MODEL", "gemma4:e4b")
    monkeypatch.setattr(config, "OPUS_MODEL", "nemotron-3-ultra:cloud")
    assert registry.is_local("haiku") and registry.is_local("sonnet")
    assert not registry.is_local("opus")  # opus degrades to sonnet and haiku, but is itself hosted
    monkeypatch.setattr(config, "HAIKU_MODEL", "gpt-oss:20b-cloud")
    assert not registry.is_local("sonnet")  # sonnet may fall back to a hosted haiku


def test_secret_values_collects_credential_settings_live(monkeypatch):
    monkeypatch.setattr(config, "GITHUB_PERSONAL_ACCESS_TOKEN", "ghp_livevalue1234567890")
    monkeypatch.setattr(config, "SEARXNG_SECRET", "short")  # too short to mask safely
    values = config.secret_values()
    assert "ghp_livevalue1234567890" in values and "short" not in values


def test_background_turns_skip_the_conversation_log_and_learning_but_keep_the_transcript(tmp_vault, monkeypatch):
    learned = []
    monkeypatch.setattr(records.extraction, "extract_async", lambda *a: learned.append(a))
    record_turn(TurnRecord("term", "sonnet", "scheduled prompt", "answer", origin="schedule"))
    record_turn(TurnRecord("term", "sonnet", "what is x", "x is y"))
    assert learned == [("what is x", "x is y", [])]
    assert not any("scheduled prompt" in f.read_text() for f in (tmp_vault / "hi" / "conversations").glob("*"))
    assert [m["content"] for m in transcript.history()] == ["what is x", "x is y"]  # only the chat turn
    assert "[schedule]" in next((tmp_vault / "hi" / "journal").glob("*.md")).read_text()


def test_the_island_origin_is_accepted_by_the_query_route(monkeypatch):
    from starlette.testclient import TestClient

    from hi.server import turn
    from hi.server.app import create_app
    from ag_ui.core import events as ag

    seen = {}

    def fake(text, forced_persona=None, fresh=False, context="", origin="ui", forced_tier=None):
        seen["origin"] = origin
        yield ag.RunStartedEvent(thread_id="t", run_id="r")
        yield ag.RunFinishedEvent(thread_id="t", run_id="r", result="x")

    monkeypatch.setattr(turn, "stream_query_as_agui", fake)
    client = TestClient(create_app())
    client.post("/query", json={"text": "hi", "origin": "island"})
    assert seen["origin"] == "island"
    client.post("/query", json={"text": "hi", "origin": "schedule"})  # a client may not claim a background origin
    assert seen["origin"] == "ui"
