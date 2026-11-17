import asyncio
import json
import threading
import time

import pytest
from ag_ui.core import events as ag
from starlette.testclient import TestClient

import hi.config as config
from hi.server import turn
from hi.server.app import create_app
from hi.server.http import iterate_in_one_thread

ORIGIN = "http://localhost:5173"


@pytest.fixture
def client():
    return TestClient(create_app())  # no `with`: the lifespan (background jobs, warm-up) is not started


def test_get_config_lists_fields_models_and_modes(client):
    body = client.get("/config").json()
    assert body["MODES"] == ["local", "tailscale"] and body["AI_MODE"] in body["MODES"]
    assert "SONNET_MODEL" in body and "OPENROUTER_API_KEY_SET" not in body


def test_get_config_rejects_an_unknown_mode(client):
    assert client.get("/config?mode=openrouter").status_code == 400


def test_post_config_validates_then_applies_and_journals(client, tmp_vault, monkeypatch):
    applied = []
    monkeypatch.setattr(config, "set_value", lambda k, v: applied.append((k, v)))
    assert client.post("/config", json={"NOPE": "x"}).status_code == 400
    assert client.post("/config", json={"AI_MODE": "openrouter"}).status_code == 400
    assert client.post("/config", content=b"{not json").status_code == 400

    r = client.post("/config", json={"SONNET_MODEL": "m", "AI_MODE": "tailscale", "HAIKU_MODEL": "  "})
    assert r.json()["updated"] == ["AI_MODE", "SONNET_MODEL"]  # AI_MODE first; blank values ignored
    assert applied == [("AI_MODE", "tailscale"), ("SONNET_MODEL", "m")]


def test_cors_allows_tinyui_and_nobody_else(client):
    assert client.get("/config", headers={"Origin": ORIGIN}).headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-origin" not in client.get("/config", headers={"Origin": "https://evil.example"}).headers


def test_cors_preflight(client):
    r = client.options("/query", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200 and "POST" in r.headers["access-control-allow-methods"]


def test_memory_routes_validate_input(client):
    assert client.post("/memory/add", json={}).status_code == 400
    assert client.post("/memory/forget", content=b"nope").status_code == 400


def test_conversations(client, tmp_vault):
    assert client.get("/conversations").json() == []
    conversations = tmp_vault / "hi" / "conversations"
    conversations.mkdir(parents=True, exist_ok=True)
    (conversations / "2026-11-15.md").write_text("hello")
    assert client.get("/conversations").json() == ["2026-11-15"]
    assert client.get("/conversations/2026-11-15").json()["content"] == "hello"
    assert client.get("/conversations/1999-01-01").status_code == 404


def test_plots_are_served_with_a_locked_down_csp_and_traversal_is_refused(client, tmp_vault):
    plots = tmp_vault / "hi" / "plots"
    plots.mkdir(parents=True)
    (plots / "a-1.svg").write_text("<svg/>")
    r = client.get("/plots/a-1.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert client.get("/plots/..%2Fsecret.png").status_code == 404
    assert client.get("/plots/missing.png").status_code == 404


def test_files_are_downloads_not_pages(client, tmp_vault):
    folder = tmp_vault / "hi" / "files" / "run1"
    folder.mkdir(parents=True)
    (folder / "page.html").write_text("<script>alert(1)</script>")
    r = client.get("/files/run1/page.html")
    assert r.status_code == 200 and r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment") and r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/files/run1/missing.txt").status_code == 404
    assert client.get("/files/justaname").status_code == 404


def test_pending_approvals(client):
    assert client.get("/pending").json() == []
    assert client.post("/pending/nope/approve").status_code == 404


def test_agent_routes_are_not_shadowed_by_the_run_id_route(client, monkeypatch):
    from hi.server.routes import agents, mcp

    monkeypatch.setattr(agents, "list_presets", lambda: [{"id": "p"}])
    monkeypatch.setattr(mcp, "get_mcp_tools_by_server", lambda: {"fetch": [1, 2]})
    assert client.get("/agents/presets").json() == [{"id": "p"}]
    assert client.get("/agents/mcp-servers").json() == {"fetch": 2}
    assert client.get("/agents/doesnotexist").status_code == 404
    assert client.post("/agents", json={}).status_code == 400
    assert client.post("/agents/x/answer", json={"answers": "no"}).status_code == 400


def test_health_is_503_when_the_essentials_are_down(client, monkeypatch):
    from hi.server.routes import config as config_routes

    monkeypatch.setattr(config_routes.probes, "run", lambda: {"ok": False, "deps": {}})
    assert client.get("/health").status_code == 503
    monkeypatch.setattr(config_routes.probes, "run", lambda: {"ok": True, "deps": {}})
    assert client.get("/health").status_code == 200


def test_upload_streams_the_body_to_attachments_save(client, monkeypatch):
    from hi.server.routes import files

    seen = {}

    def save(name, stream, size, kind):
        seen.update(name=name, data=stream.read(), size=size, kind=kind)
        return {"id": "abc", "name": name, "size": size, "chars": 0}

    monkeypatch.setattr(files.attachments, "save", save)
    r = client.post("/context?name=notes.txt&kind=audio", content=b"hello")
    assert r.json()["id"] == "abc" and seen == {"name": "notes.txt", "data": b"hello", "size": 5, "kind": "audio"}


def fake_events(text, forced_persona=None, fresh=False, context="", origin="ui", forced_tier=None):
    yield ag.RunStartedEvent(thread_id="t", run_id="r")
    yield ag.CustomEvent(name="persona_selected", value={"name": "term", "tier": "sonnet", "plan": False, "echo": text})
    yield ag.RunFinishedEvent(thread_id="t", run_id="r", result="done")


def test_query_streams_ag_ui_events_and_records_latency(client, monkeypatch):
    from hi.server.routes import query

    recorded = []
    monkeypatch.setattr(turn, "stream_query_as_agui", fake_events)
    monkeypatch.setattr(query, "record_query_latency", recorded.append)
    r = client.post("/query", json={"text": "hello", "persona": "butler"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    payloads = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert [p["type"] for p in payloads] == ["RUN_STARTED", "CUSTOM", "RUN_FINISHED"]
    assert payloads[1]["value"]["echo"] == "hello"
    assert len(recorded) == 1


def test_query_requires_text(client):
    assert client.post("/query", json={"text": "  "}).status_code == 400
    assert client.post("/query", json={}).status_code == 400


def test_a_query_that_fails_midway_still_ends_the_stream(client, monkeypatch):
    def broken(*a, **kw):
        yield ag.RunStartedEvent(thread_id="t", run_id="r")
        raise RuntimeError("boom")

    monkeypatch.setattr(turn, "stream_query_as_agui", broken)
    with pytest.raises(RuntimeError, match="boom"):
        client.post("/query", json={"text": "x"})


def test_stopping_early_closes_the_generator_on_its_own_thread():
    state = {"closed": False, "threads": set()}

    def gen():
        try:
            for i in range(1000):
                state["threads"].add(threading.current_thread().name)
                yield i
                time.sleep(0.001)
        finally:
            state["closed"] = True

    async def consume():
        stream = iterate_in_one_thread(gen)
        got = []
        async for item in stream:
            got.append(item)
            if len(got) == 3:
                break
        await stream.aclose()
        return got

    got = asyncio.run(consume())
    for _ in range(200):
        if state["closed"]:
            break
        time.sleep(0.01)
    assert got == [0, 1, 2] and state["closed"] and state["threads"] == {"stream"}


def test_tts_retries_the_configured_engine_once(client, monkeypatch):
    from hi.server.routes import voice

    calls = []

    def flaky(text, voice_name, persona):
        calls.append(text)
        if len(calls) == 1:
            raise RuntimeError("phonon is loading")
        return b"RIFFwav"

    monkeypatch.setattr(voice, "_synthesize", flaky)
    r = client.post("/tts", json={"text": "hello"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content == b"RIFFwav"
    assert len(calls) == 2


def test_tts_stays_silent_when_the_engine_is_down_and_tries_no_other_engine(client, monkeypatch):
    from hi.core import health
    from hi.server.routes import voice

    calls = []

    def down(text, voice_name, persona):
        calls.append(1)
        raise RuntimeError("connection refused")

    monkeypatch.setattr(voice, "_synthesize", down)
    health.reset()
    r = client.post("/tts", json={"text": "hello"})
    assert r.status_code == 503 and "voice offline" in r.text and "connection refused" in r.text
    assert len(calls) == 2  # one retry, nothing else
    assert not health.is_up("tts")
    health.reset()


def test_there_is_no_kokoro_fallback_left():
    import importlib.util

    assert importlib.util.find_spec("hi.tts_kokoro") is None
