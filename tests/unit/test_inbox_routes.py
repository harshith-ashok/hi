import pytest
from langchain_core.tools import tool
from starlette.testclient import TestClient

from hi.core import runpolicy
from hi.memory import proposals, reports
from hi.server import proposals_exec
from hi.server.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def email(monkeypatch):
    """A tool the executor can find, recording how it was called."""
    calls = []

    @tool
    def send_email(to: str) -> str:
        """Send."""
        calls.append((to, runpolicy.is_pre_approved()))
        return f"sent to {to}"

    monkeypatch.setattr(proposals_exec, "_tools", lambda persona: [send_email] if persona == "term" else [])
    return calls


def new(tool="send_email", **args):
    return proposals.create("heartbeat", "term", tool, args or {"to": "bob@acme.com"})


def test_approving_runs_the_tool_once_with_the_stored_arguments_and_records_the_result(tmp_vault, client, email):
    pid = new()
    r = client.post(f"/proposals/{pid}/approve")
    assert r.status_code == 200 and r.json() == {"status": "executed", "result": "sent to bob@acme.com"}
    assert email == [("bob@acme.com", True)]  # pre-approved: the tool must not ask a second time
    assert proposals.get(pid)["status"] == "executed"


def test_a_second_approval_is_a_conflict_and_does_not_run_the_tool_again(tmp_vault, client, email):
    pid = new()
    assert client.post(f"/proposals/{pid}/approve").status_code == 200
    assert client.post(f"/proposals/{pid}/approve").status_code == 409
    assert len(email) == 1


def test_denying_never_runs_the_tool_and_blocks_a_later_approval(tmp_vault, client, email):
    pid = new()
    assert client.post(f"/proposals/{pid}/deny").status_code == 204
    assert client.post(f"/proposals/{pid}/approve").status_code == 409
    assert email == [] and proposals.get(pid)["status"] == "denied"


def test_an_unknown_proposal_is_a_conflict_not_a_crash(tmp_vault, client):
    assert client.post("/proposals/P-nope/approve").status_code == 409
    assert client.post("/proposals/P-nope/deny").status_code == 409


def test_a_tool_that_raises_is_recorded_failed_and_not_retried(tmp_vault, client, monkeypatch):
    calls = []

    @tool
    def flaky(x: str = "") -> str:
        """Fails."""
        calls.append(1)
        raise RuntimeError("smtp down")

    monkeypatch.setattr(proposals_exec, "_tools", lambda persona: [flaky])
    pid = new("flaky", x="1")
    r = client.post(f"/proposals/{pid}/approve")
    assert r.json()["status"] == "failed" and "smtp down" in r.json()["result"]
    assert calls == [1] and proposals.get(pid)["status"] == "failed"


def test_a_tool_that_no_longer_exists_fails_cleanly(tmp_vault, client, monkeypatch):
    monkeypatch.setattr(proposals_exec, "_tools", lambda persona: [])
    pid = new("gone")
    assert client.post(f"/proposals/{pid}/approve").json()["status"] == "failed"


def test_the_tool_is_found_in_another_personas_list_when_the_recorded_one_lacks_it(tmp_vault, monkeypatch, email):
    pid = proposals.create("drop", "butler", "send_email", {"to": "a"})
    monkeypatch.setattr(proposals_exec, "_tools", lambda persona: [] if persona == "butler" else [t for t in email_tools])
    email_tools = []
    from langchain_core.tools import tool as mk

    @mk
    def send_email(to: str) -> str:
        """Send."""
        return "ok"

    email_tools.append(send_email)
    assert proposals_exec.find_tool("send_email", "butler").name == "send_email"


def test_listing_proposals_shows_what_approving_would_run(tmp_vault, client):
    new(to="bob@acme.com")
    rows = client.get("/proposals?status=pending").json()
    assert len(rows) == 1 and rows[0]["summary"].startswith("send_email(to='bob@acme.com'")


def test_reports_are_listed_and_read_and_a_bad_id_is_404(tmp_vault, client):
    rid, _ = reports.write_report("schedule", "Morning brief", "## Tasks\n- a")
    assert [r["headline"] for r in client.get("/reports").json()] == ["Morning brief"]
    assert "- a" in client.get(f"/reports/{rid}").json()["body"]
    assert client.get("/reports/..%2F..%2Fetc").status_code == 404


def test_livez_stays_200_even_when_health_would_not(client):
    assert client.get("/livez").json() == {"ok": True}
