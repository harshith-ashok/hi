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
