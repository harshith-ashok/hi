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


def test_an_answer_that_already_has_a_diagram_is_not_drawn_again(tmp_vault, monkeypatch):
    from fakes import Scripted
    from langchain_core.messages import AIMessage

    from hi.agents.base import make_agent
    from hi.server import turn as turn_module

    answer = "Here is the flow:\n\n```mermaid\nflowchart TD\n A-->B\n```\n"
    agent = make_agent(Scripted(messages=iter([AIMessage(answer)])), [])
    monkeypatch.setattr(turn_module, "_get_agent", lambda *a, **k: agent)
    monkeypatch.setattr(turn_module, "fast_route", lambda text: ("term", "sonnet"))
    monkeypatch.setattr(turn_module.reflection_agent, "maybe_reflect_yesterday", lambda: None)
    monkeypatch.setattr(turn_module, "make_visual", lambda q, a: pytest.fail("drew a second diagram"))
    monkeypatch.setattr(turn_module, "make_spoken_summary", lambda a: None)
    events = list(turn_module.stream_query_as_agui("explain", visualize=True))
    assert not any(e.type == "CUSTOM" and e.name in ("visual", "phase") for e in events)


# --- stopping a reply ----------------------------------------------------------------------------------------------

def _stream_stub(monkeypatch, deltas):
    from ag_ui.core import events as ag

    from hi.server import turn as turn_module

    def fake_agent_stream(agent, text, thread_id, history=None):
        yield ag.RunStartedEvent(thread_id="t", run_id="r")
        yield ag.TextMessageStartEvent(message_id="m")
        for d in deltas:
            yield ag.TextMessageContentEvent(message_id="m", delta=d)
        yield ag.RunFinishedEvent(thread_id="t", run_id="r", result="".join(deltas))

    monkeypatch.setattr(turn_module, "stream_agent_as_agui", fake_agent_stream)
    monkeypatch.setattr(turn_module, "_get_agent", lambda *a, **k: object())
    monkeypatch.setattr(turn_module, "fast_route", lambda text: ("term", "sonnet"))
    monkeypatch.setattr(turn_module.reflection_agent, "maybe_reflect_yesterday", lambda: None)
    monkeypatch.setattr(turn_module, "make_spoken_summary", lambda a: None)
    return turn_module


def test_a_stopped_reply_is_kept_in_its_session_with_what_was_said(tmp_vault, monkeypatch):
    turn_module = _stream_stub(monkeypatch, ["Hello ", "wor", "ld, this ", "is long"])
    sid = sessions.create().id
    stream = turn_module.stream_query_as_agui("say something long", session=sid)
    for event in stream:  # read until two pieces of the answer have arrived, then press Stop
        if event.type == "TEXT_MESSAGE_CONTENT" and event.delta == "wor":
            break
    stream.close()
    (saved,) = transcript.session_turns(sid)
    assert saved["ask"] == "say something long" and saved["answer"] == "Hello wor" and saved["error"] == "stopped"
    assert sessions.get(sid).turns == 1 and sessions.get(sid).title == "say something long"


def test_a_stopped_reply_is_not_journaled_as_a_failure_or_learned_from(tmp_vault, monkeypatch):
    turn_module = _stream_stub(monkeypatch, ["a", "b", "c"])
    sid = sessions.create().id
    stream = turn_module.stream_query_as_agui("go", session=sid)
    next(stream)
    stream.close()
    assert not (tmp_vault / "hi" / "journal").exists() or "error" not in next((tmp_vault / "hi" / "journal").glob("*.md")).read_text()


def test_a_finished_reply_is_recorded_once(tmp_vault, monkeypatch):
    turn_module = _stream_stub(monkeypatch, ["all ", "done"])
    sid = sessions.create().id
    list(turn_module.stream_query_as_agui("go", session=sid))
    (saved,) = transcript.session_turns(sid)
    assert saved["answer"] == "all done" and saved["error"] == ""


def test_an_untitled_empty_chat_disappears_after_a_while_but_a_new_one_stays(tmp_vault):
    from datetime import datetime, timedelta

    fresh = sessions.create()
    old = sessions.create()
    s = sessions.get(old.id)
    s.created = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    sessions._write(s)
    named = sessions.create("Kept on purpose")
    s = sessions.get(named.id)
    s.created = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    sessions._write(s)
    ids = {x.id for x in sessions.list_sessions()}
    assert fresh.id in ids and named.id in ids and old.id not in ids


# --- the tier chosen in the chat ---------------------------------------------------------------------------------

def test_the_tier_reaches_the_turn_and_a_bad_one_is_ignored(tmp_vault, monkeypatch):
    from ag_ui.core import events as ag
    from starlette.testclient import TestClient

    from hi.server import turn as turn_module
    from hi.server.app import create_app

    seen = []

    def fake(text, **kw):
        seen.append(kw.get("forced_tier"))
        yield ag.RunStartedEvent(thread_id="t", run_id="r")
        yield ag.RunFinishedEvent(thread_id="t", run_id="r", result="x")

    monkeypatch.setattr(turn_module, "stream_query_as_agui", fake)
    client = TestClient(create_app())
    for tier in ("haiku", "opus", "gpt-5", None, 3):
        client.post("/query", json={"text": "hi", **({"tier": tier} if tier is not None else {})})
    assert seen == ["haiku", "opus", None, None, None]


def test_a_forced_tier_is_used_but_the_router_choice_is_what_the_next_message_inherits(tmp_vault, monkeypatch):
    from fakes import Scripted
    from langchain_core.messages import AIMessage

    from hi.agents.base import make_agent
    from hi.server import turn as turn_module

    chosen, remembered = [], []
    agent = make_agent(Scripted(messages=iter([AIMessage("ok")])), [])
    monkeypatch.setattr(turn_module, "_get_agent", lambda persona, tier, *a, **k: chosen.append(tier) or agent)
    monkeypatch.setattr(turn_module, "fast_route", lambda text: ("term", "sonnet"))
    monkeypatch.setattr(turn_module, "remember_route", lambda persona, tier: remembered.append(tier))
    monkeypatch.setattr(turn_module.reflection_agent, "maybe_reflect_yesterday", lambda: None)
    monkeypatch.setattr(turn_module, "make_spoken_summary", lambda a: None)
    list(turn_module.stream_query_as_agui("hello", forced_tier="opus"))
    assert chosen == ["opus"] and remembered == ["sonnet"]


# --- a turn that ended by asking ------------------------------------------------------------------------------------

def test_a_turn_that_showed_a_form_stays_in_the_history_so_the_reply_makes_sense(tmp_vault):
    sid = sessions.create().id
    ui = {"ui": {"type": "form", "title": "Deploy", "children": []}}
    turn(sid, "deploy it", "", tools=[{"name": "show_ui", "args": json.dumps(ui), "result": "The UI is now shown. End your turn now"}])
    turn(sid, "My response to \"Deploy\": deploy\n- Environment: staging", "Deploying.")
    messages = transcript.history(session=sid)
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert "interactive UI (Deploy)" in messages[1]["content"] and "waited for their response" in messages[1]["content"]


def test_a_turn_that_asked_questions_is_kept_with_the_questions(tmp_vault):
    sid = sessions.create().id
    turn(sid, "delete the branches", "", tools=[{"name": "ask_user", "args": json.dumps({"questions": ["Which ones?", "Force?"]}), "result": "ok"}])
    (_, assistant) = transcript.history(session=sid)
    assert "asked the user: Which ones? | Force?" in assistant["content"]


def test_a_failed_turn_with_no_answer_is_still_left_out(tmp_vault):
    sid = sessions.create().id
    turn(sid, "x", "", tools=[{"name": "read_note", "args": "{}", "result": "x"}], error="model down")
    assert transcript.history(session=sid) == []


def test_the_turn_ends_as_soon_as_a_form_is_shown_without_another_model_call(tmp_vault, monkeypatch):
    from ag_ui.core import events as ag

    from hi.server import turn as turn_module
    from hi.ui_spec import WAIT_MARKER

    closed = []

    def agent_stream(agent, text, thread_id, history=None):
        try:
            yield ag.RunStartedEvent(thread_id="t", run_id="r")
            yield ag.ToolCallStartEvent(tool_call_id="c1", tool_call_name="show_ui")
            yield ag.ToolCallArgsEvent(tool_call_id="c1", delta='{"ui": {"type": "form", "title": "Deploy"}}')
            yield ag.ToolCallResultEvent(message_id="m", tool_call_id="c1", content=f"The UI is shown. {WAIT_MARKER} without adding anything")
            yield ag.TextMessageStartEvent(message_id="x")
            yield ag.TextMessageContentEvent(message_id="x", delta="THE MODEL'S UNWANTED EXTRA WORDS")  # must never be reached
            yield ag.RunFinishedEvent(thread_id="t", run_id="r", result="THE MODEL'S UNWANTED EXTRA WORDS")
        finally:
            closed.append(True)

    monkeypatch.setattr(turn_module, "stream_agent_as_agui", agent_stream)
    monkeypatch.setattr(turn_module, "_get_agent", lambda *a, **k: object())
    monkeypatch.setattr(turn_module, "fast_route", lambda text: ("term", "sonnet"))
    monkeypatch.setattr(turn_module.reflection_agent, "maybe_reflect_yesterday", lambda: None)
    monkeypatch.setattr(turn_module, "make_spoken_summary", lambda a: None)
    sid = sessions.create().id
    events = list(turn_module.stream_query_as_agui("deploy it", session=sid))
    kinds = [e.type for e in events if e.type in ("TOOL_CALL_RESULT", "TEXT_MESSAGE_CONTENT", "RUN_FINISHED")]
    assert kinds == ["TOOL_CALL_RESULT", "RUN_FINISHED"] and events[-1].type in ("RUN_FINISHED", "CUSTOM") and closed == [True]
    assert [e.result for e in events if e.type == "RUN_FINISHED"] == [""]
    (saved,) = transcript.session_turns(sid)
    assert saved["answer"] == "" and saved["error"] == "" and saved["tools"][0]["name"] == "show_ui"
    # and the next message still sees what was asked
    assert "interactive UI (Deploy)" in transcript.history(session=sid)[1]["content"]


def test_a_stopped_turn_with_tools_is_still_remembered(tmp_vault):
    sid = sessions.create().id
    turn(sid, "go", "", tools=[{"name": "show_ui", "args": json.dumps({"ui": {"type": "form", "title": "T"}}), "result": "x"}], error="stopped")
    assert len(transcript.history(session=sid)) == 2


# --- turn ids and parents ----------------------------------------------------------------------------------------

def test_turns_get_ids_chained_by_parent_and_the_session_head_follows(tmp_vault):
    s = sessions.create().id
    turn(s, "first")
    turn(s, "second")
    a, b = transcript.session_turns(s)
    assert a["id"] and b["id"] and a["id"] != b["id"]
    assert a["parent"] == "" and b["parent"] == a["id"]
    assert sessions.get(s).head == b["id"] and sessions.head_of(s) == b["id"]


def test_a_sibling_turn_is_left_out_of_the_branch_that_is_showing(tmp_vault):
    s = sessions.create().id
    turn(s, "q1")
    (first,) = transcript.session_turns(s)
    turn(s, "q2 v1", id="v1", parent=first["id"])
    turn(s, "q2 v2", id="v2", parent=first["id"])  # a second attempt at the same question
    assert [t["ask"] for t in transcript.session_turns(s)] == ["q1", "q2 v2"]
    assert [t["ask"] for t in transcript.session_turns(s, head="v1")] == ["q1", "q2 v1"]
    assert [m["content"] for m in transcript.history(session=s, head="v1") if m["role"] == "user"] == ["q1", "q2 v1"]


def test_turns_written_before_ids_read_as_a_chain_and_new_turns_follow_them(tmp_vault):
    s = sessions.create().id
    day = transcript._day_file(transcript.date.today())
    day.parent.mkdir(parents=True, exist_ok=True)
    old = [{"time": f"2026-01-01T10:0{i}:00", "ask": f"old {i}", "answer": "ok", "tools": [], "session": s} for i in range(2)]
    day.write_text("".join(json.dumps(e) + "\n" for e in old))
    first, second = transcript.session_turns(s)
    assert first["parent"] == "" and second["parent"] == first["id"]
    assert sessions.head_of(s) == second["id"]  # no head saved yet: the newest turn is it
    turn(s, "new")
    assert [t["ask"] for t in transcript.session_turns(s)] == ["old 0", "old 1", "new"]
    assert transcript.session_turns(s)[-1]["parent"] == second["id"]


# --- edit and "ask again": versions ------------------------------------------------------------------------------

def two_attempts(client):
    s = sessions.create().id
    turn(s, "q1", id="a")
    turn(s, "q2 first try", id="b1", parent="a")
    turn(s, "q3", id="c", parent="b1")
    turn(s, "q2 second try", id="b2", parent="a")  # an edit of q2: a sibling of b1, now showing
    return s


def test_versions_list_the_attempts_at_each_turn(tmp_vault, client):
    s = two_attempts(client)
    body = client.get(f"/sessions/{s}").json()
    assert [t["ask"] for t in body["turns"]] == ["q1", "q2 second try"]
    assert body["turns"][0]["versions"] == {"index": 0, "count": 1, "ids": ["a"]}
    assert body["turns"][1]["versions"] == {"index": 1, "count": 2, "ids": ["b1", "b2"]}


def test_switching_versions_shows_the_newest_branch_through_the_chosen_turn(tmp_vault, client):
    s = two_attempts(client)
    assert client.patch(f"/sessions/{s}", json={"head": "b1"}).status_code == 200
    body = client.get(f"/sessions/{s}").json()
    assert [t["ask"] for t in body["turns"]] == ["q1", "q2 first try", "q3"]  # b1's branch goes on to q3
    assert body["head"] == "c"
    assert sessions.head_of(s) == "c"  # the next turn follows what is showing


def test_switching_to_a_turn_that_is_not_in_the_chat_is_refused(tmp_vault, client):
    s = two_attempts(client)
    assert client.patch(f"/sessions/{s}", json={"head": "nope"}).status_code == 400
    assert client.patch(f"/sessions/{s}", json={"head": 5}).status_code == 400


def test_deleting_a_chat_removes_every_branch(tmp_vault, client):
    s = two_attempts(client)
    assert client.delete(f"/sessions/{s}").status_code == 204
    assert transcript.session_turns(s) == [] and transcript._session_entries(s) == []


def test_query_passes_a_known_parent_on_and_refuses_an_unknown_one(tmp_vault, client, monkeypatch):
    from hi.server import turn
    from ag_ui import core as ag

    s = two_attempts(client)
    seen = {}

    def fake(text, **kw):
        seen.update(kw)
        yield ag.RunStartedEvent(thread_id="t", run_id="r")
        yield ag.RunFinishedEvent(thread_id="t", run_id="r", result="x")

    monkeypatch.setattr(turn, "stream_query_as_agui", fake)
    assert client.post("/query", json={"text": "q2 again", "session": s, "parent": "a"}).status_code == 200
    assert seen["parent"] == "a"
    seen.clear()
    client.post("/query", json={"text": "plain", "session": s})
    assert "parent" not in seen  # not sent: the turn follows the chat's latest turn
    assert client.post("/query", json={"text": "x", "session": s, "parent": "nope"}).status_code == 400


# --- incognito chats ---------------------------------------------------------------------------------------------

def test_an_incognito_chat_is_hidden_and_leaves_no_log_journal_or_memory(tmp_vault, client, monkeypatch):
    learned = []
    monkeypatch.setattr(records.extraction, "extract_async", lambda *a: learned.append(a))
    s = client.post("/sessions", json={"incognito": True}).json()
    assert s["incognito"] is True
    turn(s["id"], "a secret question", "a secret answer")
    assert learned == []
    assert transcript.session_turns(s["id"])[0]["ask"] == "a secret question"  # kept only so the chat can carry on
    assert not list((tmp_vault / "hi" / "conversations").glob("*.md")) and not list((tmp_vault / "hi" / "journal").glob("*"))
    assert s["id"] not in [x["id"] for x in client.get("/sessions").json()]
    assert client.get(f"/sessions/{s['id']}").status_code == 200  # still open while you are in it
    turn(sessions.create().id, "an ordinary question")
    assert len(learned) == 1  # an ordinary chat is still learned from


def test_deleting_an_incognito_chat_removes_everything_of_it(tmp_vault, client):
    s = client.post("/sessions", json={"incognito": True}).json()["id"]
    turn(s, "q", '```html artifact title="x"\n<p>x</p>\n```')
    assert client.delete(f"/sessions/{s}").status_code == 204
    assert transcript._session_entries(s) == [] and not sessions._path(s).exists()


def test_the_sweep_deletes_only_old_incognito_chats(tmp_vault):
    old, fresh, normal = (sessions.create(incognito=True), sessions.create(incognito=True), sessions.create())
    for chat in (old, fresh, normal):
        turn(chat.id, "q")
    stale = sessions.get(old.id)
    stale.updated = "2020-01-01T00:00:00"
    sessions._write(stale)
    older_normal = sessions.get(normal.id)
    older_normal.updated = "2020-01-01T00:00:00"
    sessions._write(older_normal)
    assert sessions.sweep_incognito() == 1
    assert sessions.get(old.id) is None and sessions.get(fresh.id) is not None and sessions.get(normal.id) is not None
