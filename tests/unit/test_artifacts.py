import pytest
from starlette.testclient import TestClient

from hi.memory import artifacts, records, sessions
from hi.memory.records import TurnRecord, record_turn
from hi.server.app import create_app

PAGE = '```html artifact title="Budget"\n<h1>Budget</h1>\n```'


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(records.extraction, "extract_async", lambda *a: None)
    monkeypatch.setattr(sessions, "retitle_async", lambda *a, **k: None)


def test_only_blocks_marked_artifact_are_extracted():
    answer = "Here:\n```html\n<p>plain example</p>\n```\n" + PAGE + '\n```svg artifact\n<svg/>\n```\n```python artifact title=\'Tool\'\nprint(1)\n```'
    found = artifacts.extract(answer)
    assert [(a.title, a.kind, a.ext) for a in found] == [("Budget", "html", "html"), ("Untitled", "svg", "svg"), ("Tool", "code", "py")]
    assert found[0].content == "<h1>Budget</h1>"


def test_an_unclosed_block_and_an_empty_one_are_not_artifacts():
    assert artifacts.extract('```html artifact title="x"\n<p>still streaming') == []
    assert artifacts.extract("```html artifact\n\n```") == []


def test_a_longer_fence_can_hold_a_shorter_one():
    answer = '````markdown artifact title="Doc"\n# Doc\n```python\nx = 1\n```\n````'
    (a,) = artifacts.extract(answer)
    assert a.kind == "markdown" and "```python" in a.content


def test_the_same_title_in_a_chat_makes_a_new_version_and_a_repeat_does_not(tmp_vault):
    s = sessions.create().id
    first = artifacts.save(s, "t1", artifacts.extract(PAGE)[0])
    again = artifacts.save(s, "t2", artifacts.extract(PAGE)[0])
    changed = artifacts.save(s, "t3", artifacts.extract(PAGE.replace("h1>", "h2>"))[0])
    assert (first["version"], again["version"], changed["version"]) == (1, 1, 2)
    assert artifacts.read(s, "budget", 1)["content"] == "<h1>Budget</h1>"
    assert artifacts.latest(s)[0]["content"] == "<h2>Budget</h2>" and artifacts.latest(s)[0]["versions"] == [1, 2]
    assert [a["slug"] for a in artifacts.listing(s)] == ["budget"]


def test_a_recorded_turn_saves_its_artifacts_and_reports_them(tmp_vault):
    s = sessions.create().id
    rec = TurnRecord("term", "sonnet", "make a budget", "Done.\n" + PAGE, session=s)
    record_turn(rec)
    assert rec.artifacts == [{"slug": "budget", "title": "Budget", "kind": "html", "version": 1}]
    assert artifacts.listing(s)[0]["title"] == "Budget"


def test_failed_background_and_session_less_turns_save_nothing(tmp_vault):
    s = sessions.create().id
    record_turn(TurnRecord("term", "sonnet", "x", PAGE, session=s, error="boom"))
    record_turn(TurnRecord("term", "sonnet", "x", PAGE, session=s, origin="schedule"))
    record_turn(TurnRecord("term", "sonnet", "x", PAGE))
    assert artifacts.listing(s) == []


def test_deleting_a_chat_deletes_its_artifacts(tmp_vault):
    s = sessions.create().id
    record_turn(TurnRecord("term", "sonnet", "x", PAGE, session=s))
    assert artifacts.artifacts_dir(s).exists()
    sessions.delete(s)
    assert not artifacts.artifacts_dir(s).exists()


def test_routes_return_json_and_refuse_bad_paths(tmp_vault):
    client = TestClient(create_app())
    s = sessions.create().id
    record_turn(TurnRecord("term", "sonnet", "x", PAGE, session=s))
    assert client.get(f"/artifacts/{s}").json()[0]["slug"] == "budget"
    r = client.get(f"/artifacts/{s}/budget/1")
    assert r.headers["content-type"].startswith("application/json") and r.json()["content"] == "<h1>Budget</h1>"
    assert client.get(f"/artifacts/{s}/budget/2").status_code == 404
    assert client.get(f"/artifacts/{s}/budget/x").status_code == 404
    assert client.get(f"/artifacts/{s}/..%2Fsessions/1").status_code == 404
    assert client.get("/artifacts/..%2F..%2Fetc/x/1").status_code == 404


# --- artifacts in the model's context ----------------------------------------------------------------------------

def make(s, ask, body, **kw):
    rec = TurnRecord("term", "sonnet", ask, f'Here.\n```html artifact title="Budget"\n{body}\n```\nAnything else?', session=s, **kw)
    record_turn(rec)
    return rec


def test_the_context_has_only_the_newest_version_in_full(tmp_vault):
    s = sessions.create().id
    make(s, "make a page", "<h1>one</h1>")
    make(s, "change it", "<h1>two</h1>")
    block = artifacts.context_block(s, 5000)
    assert "<h1>two</h1>" in block and "<h1>one</h1>" not in block and "version 2" in block
    assert artifacts.context_block(sessions.create().id, 5000) == ""


def test_an_artifact_that_does_not_fit_is_named_not_included(tmp_vault):
    s = sessions.create().id
    make(s, "big", "<p>" + "x" * 3000 + "</p>")
    block = artifacts.context_block(s, 100)
    assert '"Budget"' in block and "xxxx" not in block and "too large" in block


def test_only_versions_on_the_showing_branch_count(tmp_vault):
    s = sessions.create().id
    first = make(s, "page", "<h1>one</h1>")
    make(s, "edit A", "<h1>from A</h1>", id="a", parent=first.id)
    make(s, "edit B", "<h1>from B</h1>", id="b", parent=first.id)
    on_a = artifacts.context_block(s, 5000, {first.id, "a"})
    assert "from A" in on_a and "from B" not in on_a
    assert artifacts.context_block(s, 5000, set()) == ""


def test_a_longer_fence_is_used_when_the_artifact_contains_backticks(tmp_vault):
    s = sessions.create().id
    record_turn(TurnRecord("term", "sonnet", "doc", '````markdown artifact title="Doc"\n```py\nx\n```\n````', session=s))
    assert "````markdown" in artifacts.context_block(s, 5000)


def test_older_answers_show_a_placeholder_instead_of_the_page(tmp_vault):
    from hi.memory import transcript

    s = sessions.create().id
    make(s, "make a page", "<h1>one</h1>")
    make(s, "thanks", "<h1>one</h1>")  # an identical repeat makes no new version
    messages, _ = transcript.history_within(100_000, s)
    texts = [m["content"] for m in messages if m["role"] == "assistant"]
    assert '[artifact "Budget" v1]' in texts[0] and "<h1>" not in texts[0] and "Anything else?" in texts[0]
    assert '[artifact "Budget"]' in texts[1] and "<h1>" not in texts[1]


def test_a_chat_reloaded_from_the_server_lists_what_each_turn_made(tmp_vault):
    client = TestClient(create_app())
    s = sessions.create().id
    make(s, "make a page", "<h1>one</h1>")
    make(s, "no page this time", "<h1>one</h1>")  # an identical repeat: no new version
    first, second = client.get(f"/sessions/{s}").json()["turns"]
    assert first["artifacts"] == [{"slug": "budget", "title": "Budget", "kind": "html", "version": 1}]
    assert second["artifacts"] == []
