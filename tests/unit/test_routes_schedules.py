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
