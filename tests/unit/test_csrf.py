"""A web page open in your browser must not be able to approve, deny, run or delete anything on the loopback backend."""

import pytest
from starlette.testclient import TestClient

from hi.memory import proposals, schedules
from hi.memory.schedules import Schedule
from hi.server.app import create_app

EVIL = "https://evil.example"
TINYUI = "http://localhost:5176"

MUTATING = [
    ("POST", "/pending/abc/approve"), ("POST", "/pending/abc/deny"),
    ("POST", "/proposals/P-abcdef/approve"), ("POST", "/proposals/P-abcdef/deny"),
    ("POST", "/schedules/brief/toggle"), ("POST", "/schedules/brief/run"), ("DELETE", "/schedules/brief"),
    ("POST", "/context/0123456789ab/file"),
]


@pytest.fixture
def client():
    return TestClient(create_app())  # no default header: a plain cross-site request carries none


@pytest.mark.parametrize("method,path", MUTATING)
def test_a_request_without_the_client_header_is_refused_before_anything_happens(client, method, path):
    assert client.request(method, path).status_code == 403


def test_the_refusal_means_nothing_ran(tmp_vault, client):
    pid = proposals.create("heartbeat", "term", "send_email", {"to": "a"})
    schedules.save(Schedule("brief", "0 8 * * *", "x", created="2026-11-15T10:00:00"))
    assert client.post(f"/proposals/{pid}/approve").status_code == 403
    assert client.post(f"/proposals/{pid}/deny").status_code == 403
    assert client.delete("/schedules/brief").status_code == 403
    assert proposals.get(pid)["status"] == "created" and schedules.load("brief")


def test_with_the_header_the_same_requests_work(tmp_vault, client):
    pid = proposals.create("heartbeat", "term", "send_email", {"to": "a"})
    assert client.post(f"/proposals/{pid}/deny", headers={"X-Hi-Client": "tinyui"}).status_code == 204


def test_a_browser_must_preflight_the_header_and_only_tinyuis_origin_passes(client):
    ask = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-hi-client"}
    ok = client.options("/proposals/P-1/approve", headers={"Origin": TINYUI, **ask})
    assert ok.status_code == 200 and "x-hi-client" in ok.headers["access-control-allow-headers"].lower()
    refused = client.options("/proposals/P-1/approve", headers={"Origin": EVIL, **ask})
    assert refused.status_code == 400 and "access-control-allow-origin" not in refused.headers


def test_delete_is_allowed_from_tinyui_for_schedules(client):
    r = client.options("/schedules/brief", headers={"Origin": TINYUI, "Access-Control-Request-Method": "DELETE",
                                                    "Access-Control-Request-Headers": "x-hi-client"})
    assert r.status_code == 200 and "DELETE" in r.headers["access-control-allow-methods"]


def test_proposal_ids_are_hard_to_guess(tmp_vault):
    ids = {proposals.create("heartbeat", "term", "t", {"i": i}) for i in range(50)}
    assert len(ids) == 50 and all(len(i) == len("P-") + 6 for i in ids)


def test_the_island_sends_the_header(monkeypatch):
    import urllib.request

    from hi.context import inbox

    seen = {}

    class Done:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=0: seen.update(headers=dict(request.header_items())) or Done())
    inbox._http_post("http://127.0.0.1:8768/proposals/P-1/approve")
    assert seen["headers"].get("X-hi-client") == "island"
