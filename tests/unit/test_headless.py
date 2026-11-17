import json
import time

import pytest
from fakes import Scripted
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from hi.agents.base import make_agent
from hi.core.runpolicy import UNATTENDED
from hi.memory import proposals, transcript
from hi.server import headless, turn


@pytest.fixture
def wired(tmp_vault, monkeypatch):
    """The real turn pipeline and a real agent, with a scripted model and no routing model, learning or reflection."""
    ran = []

    @tool
    def write_project_file(path: str) -> str:
        """Write a file."""
        ran.append(path)
        return "written"

    def script(messages):
        agent = make_agent(Scripted(messages=iter(messages)), [write_project_file])
        monkeypatch.setattr(turn, "_get_agent", lambda persona, tier, isolated=False: agent)

    monkeypatch.setattr(turn, "fast_route", lambda text: ("term", "sonnet"))
    monkeypatch.setattr(turn.reflection_agent, "maybe_reflect_yesterday", lambda: None)
    monkeypatch.setattr("hi.memory.records.extraction.extract_async", lambda *a: pytest.fail("learned from a background run"))
    return script, ran


def test_a_background_run_returns_the_answer_and_records_its_origin(wired, tmp_vault):
    script, _ = wired
    script([AIMessage("# Morning brief\n\nThree things today.")])
    result = headless.run_turn("brief me", origin="schedule", policy=UNATTENDED)
    assert result.error == "" and result.answer.startswith("# Morning brief") and result.proposals == []
    (day,) = (tmp_vault / "hi" / "transcripts").glob("*.jsonl")
    entry = json.loads(day.read_text())
    assert entry["origin"] == "schedule" and entry["ask"] == "brief me"


def test_a_risky_tool_call_becomes_a_proposal_and_the_file_is_untouched(wired):
    script, ran = wired
    script([AIMessage("", tool_calls=[{"name": "write_project_file", "args": {"path": "a.py"}, "id": "c1"}]),
            AIMessage("I queued the change.")])
    result = headless.run_turn("fix it", origin="heartbeat", policy=UNATTENDED)
    assert ran == [] and result.answer == "I queued the change."
    (p,) = proposals.pending()
    assert result.proposals == [p["id"]] and p["persona"] == "term" and p["origin"] == "heartbeat"
    assert [t["name"] for t in result.tools] == ["write_project_file"] and "queued" in result.tools[0]["result"]


def test_a_background_run_never_joins_the_chat_history_or_the_conversation_log(wired, tmp_vault):
    script, _ = wired
    script([AIMessage("background answer")])
    headless.run_turn("scheduled prompt", origin="schedule", policy=UNATTENDED)
    assert transcript.history() == []
    assert not (tmp_vault / "hi" / "conversations").exists()


def test_a_background_run_does_not_steer_the_next_chat_route(wired, monkeypatch):
    script, _ = wired
    remembered = []
    monkeypatch.setattr(turn, "remember_route", lambda *a: remembered.append(a))
    script([AIMessage("ok")])
    headless.run_turn("x", origin="schedule", policy=UNATTENDED)
    assert remembered == []


def test_it_uses_its_own_agent_so_your_chat_is_not_reset(wired, monkeypatch):
    script, _ = wired
    seen = []
    monkeypatch.setattr(turn, "_get_agent", lambda persona, tier, isolated=False: seen.append(isolated) or make_agent(Scripted(messages=iter([AIMessage("ok")])), []))
    headless.run_turn("x", origin="heartbeat", policy=UNATTENDED)
    assert seen == [True]


def test_a_run_that_takes_too_long_is_stopped_and_reported(monkeypatch, tmp_vault):
    from ag_ui.core import events as ag

    def slow(text, **kw):
        yield ag.RunStartedEvent(thread_id="t", run_id="r")
        time.sleep(0.05)
        yield ag.TextMessageStartEvent(message_id="m")
        yield ag.RunFinishedEvent(thread_id="t", run_id="r", result="late answer")

    monkeypatch.setattr(turn, "stream_query_as_agui", slow)
    policy = UNATTENDED.__class__(**{**UNATTENDED.__dict__, "timeout_s": 0.01})
    result = headless.run_turn("x", origin="schedule", policy=policy)
    assert result.error.startswith("timed out") and result.answer == ""


def test_a_failed_turn_is_an_error_not_an_exception(wired, monkeypatch):
    monkeypatch.setattr(turn, "_get_agent", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("model host down")))
    result = headless.run_turn("x", origin="schedule", policy=UNATTENDED)
    assert result.answer == "" and result.error


def test_a_background_run_is_never_routed_by_a_model_or_planned(tmp_vault, monkeypatch):
    seen = {}
    monkeypatch.setattr(turn, "fast_route", lambda text: pytest.fail("routed a background run"))
    monkeypatch.setattr(turn, "classify_or_default", lambda text: pytest.fail("classified a background run"))
    monkeypatch.setattr(turn.reflection_agent, "maybe_reflect_yesterday", lambda: None)
    monkeypatch.setattr(turn, "_get_agent", lambda persona, tier, isolated=False: seen.update(persona=persona, tier=tier) or make_agent(Scripted(messages=iter([AIMessage("ok")])), []))
    result = headless.run_turn("prepare it", origin="heartbeat", policy=UNATTENDED)
    assert result.answer == "ok" and seen == {"persona": "term", "tier": "sonnet"}
