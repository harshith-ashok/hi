import json
import threading
import time

import pytest
from starlette.testclient import TestClient

from hi import visuals
from hi.memory import records, sessions, transcript
from hi.memory.records import TurnRecord, record_turn
from hi.server.app import create_app

HDR = {"X-Hi-Client": "test"}
REAL_RETITLE = sessions.retitle_async  # the fixture below replaces it on the module for every other test


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(records.extraction, "extract_async", lambda *a: None)
    monkeypatch.setattr(sessions, "retitle_async", lambda *a, **k: None)


@pytest.fixture
def client():
    return TestClient(create_app(), headers=HDR)


def turn(session, ask, answer="ok", **kw):
    record_turn(TurnRecord("term", "sonnet", ask, answer, session=session, **kw))


# --- the store ---------------------------------------------------------------------------------------------------

def test_a_new_session_has_a_default_title_and_is_listed(tmp_vault):
    s = sessions.create()
    assert sessions.valid_id(s.id) and s.title == "New chat" and s.title_auto
    assert [x.id for x in sessions.list_sessions()] == [s.id]


def test_the_first_question_gives_a_provisional_title_and_later_ones_do_not_change_it(tmp_vault):
    s = sessions.create()
    sessions.touch(s.id, "what did I note about binary search trees last week please")
    got = sessions.get(s.id)
    assert got.title == "what did I note about binary search…" and got.turns == 1
    sessions.touch(s.id, "and the second one?")
    assert sessions.get(s.id).title == got.title and sessions.get(s.id).turns == 2


def test_a_renamed_session_keeps_the_users_title_even_if_a_model_suggests_another(tmp_vault):
    s = sessions.create()
    sessions.update(s.id, title="Taxes 2026")
    assert not sessions.set_generated_title(s.id, "Something a model made up")
    assert sessions.get(s.id).title == "Taxes 2026" and not sessions.get(s.id).title_auto


def test_a_generated_title_replaces_the_provisional_one(tmp_vault):
    s = sessions.create()
    sessions.touch(s.id, "how do I rebase")
    assert sessions.set_generated_title(s.id, "Git rebase basics") and sessions.get(s.id).title == "Git rebase basics"


def test_pinned_sessions_come_first_then_newest(tmp_vault):
    a, b, c = (sessions.create(t) for t in ("a", "b", "c"))
    for i, s in enumerate((a, b, c)):
        s2 = sessions.get(s.id)
        s2.updated = f"2026-11-17T10:0{i}:00"
        sessions._write(s2)
    sessions.update(a.id, pinned=True)
    assert [s.title for s in sessions.list_sessions()] == ["a", "c", "b"]


def test_archived_sessions_are_hidden_unless_asked_for(tmp_vault):
    s = sessions.create()
    sessions.update(s.id, archived=True)
    assert sessions.list_sessions() == [] and len(sessions.list_sessions(include_archived=True)) == 1


def test_a_title_that_looks_like_a_list_or_has_markdown_reads_back_safely(tmp_vault):
    s = sessions.create("[urgent] **fix** `it`")
    assert sessions.get(s.id).title == "urgent fix it"


def test_a_bad_id_never_touches_the_disk(tmp_vault):
    assert sessions.get("../../etc/passwd") is None and sessions.touch("nope", "x") is None
    assert not sessions.delete("../x") and sessions.update("../x", title="x") is None


def test_an_unknown_but_valid_id_is_created_on_first_use(tmp_vault):
    sid = sessions.new_id()
    assert sessions.touch(sid, "hello there").turns == 1 and sessions.get(sid).title == "hello there"


def test_a_failed_title_generation_keeps_the_provisional_title(tmp_vault):
    s = sessions.create()
    sessions.touch(s.id, "how do I rebase")
    done = threading.Event()

    def boom(ask, answer):
        done.set()
        raise RuntimeError("model down")

    REAL_RETITLE(s.id, "how do I rebase", "answer", make=boom)
    assert done.wait(2)
    time.sleep(0.1)
    assert sessions.get(s.id).title == "how do I rebase"


def test_a_generated_title_is_applied_in_the_background(tmp_vault):
    s = sessions.create()
    sessions.touch(s.id, "how do I rebase")
    REAL_RETITLE(s.id, "how do I rebase", "answer", make=lambda ask, answer: "Git rebase basics")
    deadline = time.time() + 2
    while sessions.get(s.id).title != "Git rebase basics" and time.time() < deadline:
        time.sleep(0.01)
    assert sessions.get(s.id).title == "Git rebase basics"


# --- turns and history belong to a session -------------------------------------------------------------------------

def test_history_only_includes_the_sessions_own_turns(tmp_vault):
    a, b = sessions.create().id, sessions.create().id
    turn(a, "in a", "answer a")
    turn(b, "in b", "answer b")
    turn("", "no session", "answer none")
    assert [m["content"] for m in transcript.history(session=a)] == ["in a", "answer a"]
    assert [m["content"] for m in transcript.history(session=b)] == ["in b", "answer b"]
    assert [m["content"] for m in transcript.history()] == ["no session", "answer none"]


def test_recording_a_turn_updates_the_session(tmp_vault):
    s = sessions.create()
    turn(s.id, "how do I rebase", "like this")
    got = sessions.get(s.id)
    assert got.turns == 1 and got.title == "how do I rebase"


def test_session_turns_come_back_in_order_with_tools_and_the_visual(tmp_vault):
    s = sessions.create().id
    turn(s, "first", "one", tools=[{"name": "read_note", "args": "{}", "result": "x"}], visual="flowchart TD\n A-->B")
    turn(s, "second", "two")
    turns = transcript.session_turns(s)
    assert [t["ask"] for t in turns] == ["first", "second"]
    assert turns[0]["tools"][0]["name"] == "read_note" and turns[0]["visual"].startswith("flowchart")


def test_deleting_a_session_removes_its_turns_and_only_its_turns(tmp_vault):
    a, b = sessions.create().id, sessions.create().id
    turn(a, "in a")
    turn(b, "in b")
    assert sessions.delete(a) and sessions.get(a) is None
    assert transcript.session_turns(a) == [] and len(transcript.session_turns(b)) == 1


def test_search_finds_sessions_by_what_was_said_with_a_snippet(tmp_vault):
    a, b = sessions.create().id, sessions.create().id
    turn(a, "tell me about kaapi", "Kaapi is a coffee project")
    turn(b, "something else", "unrelated")
    hits = transcript.search_sessions("coffee")
    assert list(hits) == [a] and "coffee" in hits[a]
    assert transcript.search_sessions("   ") == {}


def test_a_torn_transcript_line_does_not_hide_the_session(tmp_vault):
    s = sessions.create().id
    turn(s, "hello")
    day = next((tmp_vault / "hi" / "transcripts").glob("*.jsonl"))
    day.write_text(day.read_text() + '{"ask": "cut off\n')
    assert len(transcript.session_turns(s)) == 1


# --- routes -------------------------------------------------------------------------------------------------------

def test_create_list_open_rename_pin_archive_delete(tmp_vault, client):
    s = client.post("/sessions", json={}).json()
    sid = s["id"]
    turn(sid, "hello world", "hi back", visual="flowchart TD\n A-->B")
    opened = client.get(f"/sessions/{sid}").json()
    assert opened["turns"][0]["ask"] == "hello world" and opened["turns"][0]["visual"].startswith("flowchart")
    assert client.patch(f"/sessions/{sid}", json={"title": "Greetings", "pinned": True}).json()["title"] == "Greetings"
    assert [r["pinned"] for r in client.get("/sessions").json()] == [True]
    assert client.patch(f"/sessions/{sid}", json={"archived": True}).json()["archived"] is True
    assert client.get("/sessions").json() == [] and len(client.get("/sessions?archived=1").json()) == 1
    assert client.delete(f"/sessions/{sid}").status_code == 204
    assert client.get(f"/sessions/{sid}").status_code == 404 and client.delete(f"/sessions/{sid}").status_code == 404


def test_search_over_the_api(tmp_vault, client):
    sid = client.post("/sessions", json={"title": "Coffee"}).json()["id"]
    other = client.post("/sessions", json={"title": "Taxes"}).json()["id"]
    turn(other, "what is my deduction", "the espresso machine counts")
    rows = {r["id"]: r for r in client.get("/sessions?q=espresso").json()}
    assert set(rows) == {other} and "espresso" in rows[other]["snippet"]
    assert [r["id"] for r in client.get("/sessions?q=coffee").json()] == [sid]


def test_changes_need_the_client_header_and_bad_input_is_refused(tmp_vault):
    plain = TestClient(create_app())
    assert plain.post("/sessions", json={}).status_code == 403
    sid = plain.post("/sessions", json={}, headers=HDR).json()["id"]
    assert plain.patch(f"/sessions/{sid}", json={"title": "x"}).status_code == 403
    assert plain.delete(f"/sessions/{sid}").status_code == 403
    assert plain.patch(f"/sessions/{sid}", json={"pinned": "yes"}, headers=HDR).status_code == 400
    assert plain.get("/sessions/..%2Fx").status_code == 404


def test_query_passes_a_valid_session_and_the_visualize_flag_only(tmp_vault, client, monkeypatch):
    from ag_ui.core import events as ag

    from hi.server import turn as turn_module

    seen = []

    def fake(text, **kw):
        seen.append(kw)
        yield ag.RunStartedEvent(thread_id="t", run_id="r")
        yield ag.RunFinishedEvent(thread_id="t", run_id="r", result="x")

    monkeypatch.setattr(turn_module, "stream_query_as_agui", fake)
    sid = sessions.new_id()
    client.post("/query", json={"text": "hi", "session": sid, "visualize": True})
    client.post("/query", json={"text": "hi", "session": "../../x", "visualize": "yes"})
    assert seen[0]["session"] == sid and seen[0]["visualize"] is True
    assert seen[1]["session"] == "" and seen[1]["visualize"] is False


# --- visuals ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("reply,ok", [
    ('flowchart TD\n  A["Read"] --> B["Parse"]', True),
    ('```mermaid\nsequenceDiagram\n  A->>B: hi\n```', True),
    ("mindmap\n  root((hi))", True),
    ("stateDiagram-v2\n  [*] --> A", True),
    ("NONE", False), ("", False), ("Sure! Here is a diagram", False), ("flowchartish nonsense", False),
    ("flowchart TD\n" + "A-->B\n" * 1000, False),
])
def test_only_a_real_diagram_type_is_accepted(reply, ok):
    assert (visuals.clean_mermaid(reply) is not None) is ok


def test_a_short_answer_is_not_drawn_and_a_failing_model_is_not_an_error():
    assert visuals.make_visual("q", "yes", model_fn=lambda p: pytest.fail("called the model")) is None

    def down(prompt):
        raise RuntimeError("model down")

    assert visuals.make_visual("q", "x" * 100, model_fn=down) is None


def test_a_retry_carries_the_parse_error_to_the_model():
    seen = []
    out = visuals.make_visual("q", "x" * 100, error="Parse error on line 2", model_fn=lambda p: seen.append(p) or "flowchart TD\n A-->B")
    assert out and "Parse error on line 2" in seen[0]


def test_the_visual_route(tmp_vault, client, monkeypatch):
    monkeypatch.setattr(visuals, "_default_model", lambda p: "flowchart TD\n A-->B")
    assert client.post("/visual", json={"question": "q", "answer": "a" * 80}).json() == {"mermaid": "flowchart TD\n A-->B"}
    assert client.post("/visual", json={"question": "q"}).status_code == 400
    assert TestClient(create_app()).post("/visual", json={"answer": "a" * 80}).status_code == 403


# --- the turn pipeline ---------------------------------------------------------------------------------------------

def test_a_forced_visual_arrives_after_the_answer_and_is_saved_with_the_turn(tmp_vault, monkeypatch):
    from fakes import Scripted
    from langchain_core.messages import AIMessage

    from hi.agents.base import make_agent
    from hi.server import turn as turn_module

    answer = "The process has three steps: read, parse, write. " * 2
    agent = make_agent(Scripted(messages=iter([AIMessage(answer)])), [])
    monkeypatch.setattr(turn_module, "_get_agent", lambda *a, **k: agent)
    monkeypatch.setattr(turn_module, "fast_route", lambda text: ("term", "sonnet"))
    monkeypatch.setattr(turn_module.reflection_agent, "maybe_reflect_yesterday", lambda: None)
    monkeypatch.setattr(turn_module, "make_visual", lambda q, a: "flowchart TD\n A-->B")
    monkeypatch.setattr(turn_module, "make_spoken_summary", lambda a: None)
    sid = sessions.create().id
    events = list(turn_module.stream_query_as_agui("explain it", session=sid, visualize=True))
    names = [(e.name, e.value) for e in events if e.type == "CUSTOM"]
    kinds = [n for n, _ in names]
    assert kinds.index("phase") < kinds.index("visual") < kinds.index("timing")
    assert dict(names)["visual"] == {"mermaid": "flowchart TD\n A-->B"}
    (saved,) = transcript.session_turns(sid)
    assert saved["visual"].startswith("flowchart") and saved["answer"] == answer


def test_without_the_flag_no_visual_is_made(tmp_vault, monkeypatch):
    from fakes import Scripted
    from langchain_core.messages import AIMessage

    from hi.agents.base import make_agent
    from hi.server import turn as turn_module

    agent = make_agent(Scripted(messages=iter([AIMessage("x" * 100)])), [])
    monkeypatch.setattr(turn_module, "_get_agent", lambda *a, **k: agent)
    monkeypatch.setattr(turn_module, "fast_route", lambda text: ("term", "sonnet"))
    monkeypatch.setattr(turn_module.reflection_agent, "maybe_reflect_yesterday", lambda: None)
    monkeypatch.setattr(turn_module, "make_visual", lambda q, a: pytest.fail("drew without being asked"))
    monkeypatch.setattr(turn_module, "make_spoken_summary", lambda a: None)
    assert not any(e.type == "CUSTOM" and e.name == "visual" for e in turn_module.stream_query_as_agui("hi"))


def test_each_session_gets_its_own_agent_and_the_cache_is_bounded(monkeypatch):
    from hi.server import turn as turn_module

    built = []
    monkeypatch.setattr(turn_module, "get_tier_model", lambda tier: type("M", (), {"model": "m"})())
    monkeypatch.setattr(turn_module.llm, "signature", lambda *a: "sig")
    monkeypatch.setattr(turn_module, "get_agent_builder", lambda name: lambda model: built.append(1) or object())
    turn_module._agent_cache.clear()
    a1, a2 = turn_module._get_agent("term", "sonnet", session="s1"), turn_module._get_agent("term", "sonnet", session="s2")
    assert a1 is not a2 and turn_module._get_agent("term", "sonnet", session="s1") is a1
    for i in range(30):
        turn_module._get_agent("term", "sonnet", session=f"x{i}")
    assert len(turn_module._agent_cache) == turn_module.MAX_CACHED_AGENTS
    turn_module._agent_cache.clear()
