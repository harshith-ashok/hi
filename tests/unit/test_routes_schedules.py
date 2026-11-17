import pytest
from starlette.testclient import TestClient

from hi.automation import scheduler
from hi.memory import schedules
from hi.memory.schedules import Schedule
from hi.server.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_the_schedules_endpoint_lists_next_runs_and_bad_notes(tmp_vault, client):
    schedules.save(Schedule("brief", "0 8 * * 1-5", "Brief me", created="2026-11-15T10:00:00"))
    (tmp_vault / "hi" / "schedules" / "bad.md").write_text("---\nwhen: soon\n---\n\nx\n")
    body = client.get("/schedules").json()
    (row,) = body["schedules"]
    assert row["id"] == "brief" and len(row["next"]) == 3 and row["enabled"] is True and "bad.md" in body["errors"][0]


def test_toggle_and_delete(tmp_vault, client):
    schedules.save(Schedule("brief", "0 8 * * *", "x", created="2026-11-15T10:00:00"))
    assert client.post("/schedules/brief/toggle").json() == {"id": "brief", "enabled": False}
    assert client.post("/schedules/brief/toggle").json()["enabled"] is True
    assert client.delete("/schedules/brief").status_code == 204
    assert client.delete("/schedules/brief").status_code == 404 and client.post("/schedules/brief/toggle").status_code == 404


def test_run_now_404s_for_an_unknown_schedule_and_starts_a_known_one(tmp_vault, client, monkeypatch):
    schedules.save(Schedule("brief", "0 8 * * *", "x", kind="reminder", created="2026-11-15T10:00:00"))
    monkeypatch.setattr(scheduler, "get_worker", lambda: type("W", (), {"submit": lambda self, key, fn: True})())
    assert client.post("/schedules/nope/run").status_code == 404
    assert client.post("/schedules/brief/run").json() == {"message": "Started 'brief'."}


def test_a_bad_id_in_the_url_cannot_reach_outside_the_schedules_folder(tmp_vault, client):
    assert client.delete("/schedules/..%2Fsecret").status_code == 404


def test_filing_an_uploaded_attachment_copies_it_into_the_drop_folder(tmp_vault, client, monkeypatch):
    from hi import attachments
    from hi.automation import drop

    monkeypatch.setattr(drop.config, "DROP_PATH", "")
    folder = tmp_vault / "hi" / "context" / "0123456789ab"
    folder.mkdir(parents=True)
    (folder / "memo.txt").write_text("hello")
    (folder / "extracted.md").write_text("hello")
    assert attachments.original("0123456789ab").name == "memo.txt"
    assert client.post("/context/0123456789ab/file").json() == {"queued": "memo.txt"}
    assert (tmp_vault / "hi" / "drop" / "memo.txt").read_text() == "hello"
    assert (folder / "memo.txt").exists()  # the attachment itself is untouched
    assert client.post("/context/0123456789ab/file").json() == {"queued": "memo-2.txt"}
    assert client.post("/context/nope/file").status_code == 404
    assert client.post("/context/..%2F..%2Fetc/file").status_code in (404, 405)


def test_health_reports_jobs_proposals_and_the_zone(tmp_vault, client, monkeypatch):
    from hi import probes
    from hi.core import health, jobs
    from hi.memory import proposals

    monkeypatch.setattr(probes, "PROBES", {"ollama": lambda: None, "vault": lambda: None})
    jobs.last_run["scheduler"] = 1_000_000.0
    health.mark_down("searxng", "refused")
    proposals.create("heartbeat", "term", "send_email", {})
    body = client.get("/health").json()
    assert body["jobs"]["scheduler"]["last_run"] == 1_000_000 and body["pending_proposals"] == 1
    assert body["timezone"] and not body["deps"]["searxng"]["ok"] and "latency" in body
