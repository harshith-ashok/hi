"""What a turn hands the agent: the message with its added context, and the history. The agent itself is a stand-in."""

import io

import pytest
from ag_ui import core as ag

from hi.memory import artifacts, projects, records, sessions, transcript
from hi.memory.records import TurnRecord, record_turn
from hi.server import turn as turn_module


class Agent:
    def __init__(self):
        self.resets = 0

    def reset(self):
        self.resets += 1


@pytest.fixture
def run(monkeypatch, tmp_vault):
    """run(text, **kw) -> (what the agent was sent, its history, the agent), for one turn."""
    monkeypatch.setattr(records.extraction, "extract_async", lambda *a: None)
    monkeypatch.setattr(sessions, "retitle_async", lambda *a, **k: None)
    agent = Agent()
    seen = {}

    def fake(_agent, text, thread_id, history=None):
        seen.update(text=text, history=history)
        yield ag.RunStartedEvent(thread_id="t", run_id="r")
        yield ag.RunFinishedEvent(thread_id="t", run_id="r", result="ok")

    monkeypatch.setattr(turn_module, "_get_agent", lambda *a, **k: agent)
    monkeypatch.setattr(turn_module, "stream_agent_as_agui", fake)
    monkeypatch.setattr(turn_module, "fast_route", lambda text: ("term", "sonnet"))
    monkeypatch.setattr(turn_module.reflection_agent, "maybe_reflect_yesterday", lambda: None)
    monkeypatch.setattr(turn_module, "make_spoken_summary", lambda a: None)
    monkeypatch.setattr(turn_module.summary, "summarise_async", lambda *a: None)

    def go(text, **kw):
        events = list(turn_module.stream_query_as_agui(text, **kw))
        return seen["text"], seen["history"], agent, events

    return go


def test_the_chosen_style_is_added_to_the_message_but_not_to_what_is_saved(run, tmp_vault):
    s = sessions.create().id
    sent, _history, _agent, _events = run("explain tides", session=s, style="concise")
    assert sent.startswith("explain tides") and "(Writing style: Be brief" in sent
    assert transcript.session_turns(s)[0]["ask"] == "explain tides"
    assert "Writing style" not in run("explain tides", session=s)[0]  # no style chosen: nothing added
    assert "Writing style" not in run("explain tides", session=s, style="nope")[0]


def test_a_chat_in_a_project_is_told_the_instructions_and_files(run, tmp_vault):
    p = projects.create("Trip", instructions="Plan in euros.")
    projects.save_file(p.slug, "budget.csv", io.BytesIO(b"a,b"))
    s = sessions.create(project=p.slug).id
    sent = run("what next?", session=s)[0]
    assert "Plan in euros." in sent and "budget.csv" in sent and "read_workspace_file" in sent
    assert "Plan in euros." not in run("what next?", session=sessions.create().id)[0]


def test_the_newest_version_of_an_artifact_is_sent_and_older_pages_are_not(run, tmp_vault):
    s = sessions.create().id
    page = lambda body: f'```html artifact title="Budget"\n{body}\n```'
    record_turn(TurnRecord("term", "sonnet", "make a page", page("<h1>one</h1>"), session=s))
    record_turn(TurnRecord("term", "sonnet", "change it", page("<h1>two</h1>"), session=s))
    sent, history, _agent, events = run("make the title bigger", session=s)
    assert "<h1>two</h1>" in sent and "<h1>one</h1>" not in sent and "version 2" in sent
    assert not any("<h1>" in m["content"] for m in history) and any("[artifact" in m["content"] for m in history)


def test_a_new_artifact_is_announced_after_the_turn(run, tmp_vault, monkeypatch):
    s = sessions.create().id
    monkeypatch.setattr(turn_module, "stream_agent_as_agui", lambda *a, **k: iter([
        ag.RunStartedEvent(thread_id="t", run_id="r"),
        ag.RunFinishedEvent(thread_id="t", run_id="r", result='Done.\n```svg artifact title="Logo"\n<svg/>\n```'),
    ]))
    events = list(turn_module.stream_query_as_agui("draw a logo", session=s))
    custom = {e.name: e.value for e in events if e.type == "CUSTOM"}
    assert custom["artifact"] == {"slug": "logo", "title": "Logo", "kind": "svg", "version": 1}
    assert custom["turn"]["id"] == transcript.session_turns(s)[0]["id"]


def test_an_edit_sends_only_its_own_branch_and_clears_the_agents_memory(run, tmp_vault):
    s = sessions.create().id
    record_turn(TurnRecord("term", "sonnet", "q1", "a1", session=s, id="t1"))
    record_turn(TurnRecord("term", "sonnet", "q2 first try", "a2", session=s, id="t2", parent="t1"))
    _sent, history, agent, _e = run("q2 edited", session=s, parent="t1")
    assert [m["content"] for m in history if m["role"] == "user"] == ["q1"] and agent.resets == 1
    assert [t["parent"] for t in transcript.session_turns(s)] == ["", "t1"]  # the new turn is a sibling of t2, showing now
    _sent, history, agent, _e = run("q1 edited", session=s, parent="")  # editing the very first message: no history
    assert history == [] and agent.resets == 2  # one reset for each of the two edits (the agent is shared across the calls)


def test_a_normal_follow_up_keeps_the_agents_memory(run, tmp_vault):
    s = sessions.create().id
    record_turn(TurnRecord("term", "sonnet", "q1", "a1", session=s))
    _sent, history, agent, _e = run("q2", session=s)
    assert [m["content"] for m in history if m["role"] == "user"] == ["q1"] and agent.resets == 0


def test_think_off_builds_the_agent_on_the_model_without_reasoning(run, tmp_vault, monkeypatch):
    asked = []
    monkeypatch.setattr(turn_module, "_get_agent", lambda persona, tier, isolated=False, session="", think=True: asked.append(think) or Agent())
    s = sessions.create().id
    list(turn_module.stream_query_as_agui("hi", session=s))
    list(turn_module.stream_query_as_agui("hi", session=s, think=False))
    assert asked == [True, False]  # not passed at all unless it is off, so a fixed-signature fake still works


def test_the_agent_cache_keeps_thinking_and_not_thinking_agents_apart(monkeypatch):
    built = []
    models = {True: object(), False: object()}
    monkeypatch.setattr(turn_module, "get_tier_model", lambda tier: models[True])
    monkeypatch.setattr(turn_module, "get_tier_model_fast", lambda tier: models[False])
    monkeypatch.setattr(turn_module.llm, "model_name", lambda m: "m")
    monkeypatch.setattr(turn_module, "get_agent_builder", lambda name: lambda model: built.append(model) or object())
    turn_module._agent_cache.clear()
    a = turn_module._get_agent("term", "sonnet", session="s")
    b = turn_module._get_agent("term", "sonnet", session="s", think=False)
    assert a is not b and built == [models[True], models[False]]
    assert turn_module._get_agent("term", "sonnet", session="s", think=False) is b
    turn_module._agent_cache.clear()


def test_the_query_route_passes_think_only_when_it_is_false(tmp_vault, monkeypatch):
    from starlette.testclient import TestClient

    from hi.server.app import create_app

    seen = []

    def fake(text, **kw):
        seen.append(kw)
        yield ag.RunStartedEvent(thread_id="t", run_id="r")
        yield ag.RunFinishedEvent(thread_id="t", run_id="r", result="x")

    monkeypatch.setattr(turn_module, "stream_query_as_agui", fake)
    client = TestClient(create_app())
    for body in ({"text": "a"}, {"text": "b", "think": False}, {"text": "c", "think": True}, {"text": "d", "think": "no"}):
        client.post("/query", json=body)
    assert ["think" in kw and kw["think"] for kw in seen] == [False, False, True, False] and [("think" in kw) for kw in seen] == [False, True, True, False]


def test_which_models_stream_thinking_is_reported_without_probing(monkeypatch):
    from starlette.testclient import TestClient

    import hi.config as config
    from hi.llm import reasoning
    from hi.server.app import create_app

    monkeypatch.setattr(config, "HAIKU_MODEL", "small")
    monkeypatch.setattr(config, "SONNET_MODEL", "mid")
    monkeypatch.setattr(config, "OPUS_MODEL", "big")
    monkeypatch.setattr(reasoning, "_reasoning_supported", {"small": False, "mid": True})
    monkeypatch.setattr(reasoning, "_probe_reasoning_support", lambda *a: pytest.fail("must not probe"))
    assert TestClient(create_app()).get("/reasoning").json() == {"haiku": False, "sonnet": True, "opus": None}
