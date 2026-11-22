import io

import pytest
from starlette.testclient import TestClient

from hi.memory import projects, records, sessions
from hi.memory.records import TurnRecord, record_turn
from hi.server.app import create_app

HDR = {"X-Hi-Client": "test"}


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(records.extraction, "extract_async", lambda *a: None)
    monkeypatch.setattr(sessions, "retitle_async", lambda *a, **k: None)


@pytest.fixture
def client(tmp_vault):
    return TestClient(create_app(), headers=HDR)


def test_a_project_is_a_folder_with_instructions_in_project_md(tmp_vault):
    p = projects.create("Thesis Work", "Chapters and notes", "Answer in British English.\nBe brief.")
    assert p.slug == "thesis-work"
    text = (projects.projects_dir() / "thesis-work" / "PROJECT.md").read_text()
    assert "name: Thesis Work" in text and "Be brief." in text
    again = projects.get("thesis-work")
    assert (again.name, again.description, again.instructions) == ("Thesis Work", "Chapters and notes", "Answer in British English.\nBe brief.")


def test_same_names_get_their_own_slugs_and_a_name_is_needed(tmp_vault):
    assert [projects.create("Notes").slug, projects.create("Notes").slug] == ["notes", "notes-2"]
    with pytest.raises(ValueError):
        projects.create("   ")


def test_rename_keeps_the_slug_so_chats_stay_attached(tmp_vault):
    p = projects.create("Old name")
    s = sessions.create(project=p.slug)
    projects.update(p.slug, name="New name", instructions="x")
    assert projects.get(p.slug).name == "New name" and sessions.get(s.id).project == p.slug


def test_deleting_a_project_keeps_its_chats_but_unassigns_them(tmp_vault):
    p = projects.create("Gone")
    a, b = sessions.create(project=p.slug), sessions.create()
    assert projects.delete(p.slug) and projects.get(p.slug) is None
    assert sessions.get(a.id) is not None and sessions.get(a.id).project == "" and sessions.get(b.id) is not None
    assert not (projects.projects_dir() / "gone").exists()


def test_files_are_listed_replaced_and_removed_and_names_are_checked(tmp_vault):
    p = projects.create("Files")
    projects.save_file(p.slug, "a.txt", io.BytesIO(b"hello"))
    projects.save_file(p.slug, "a.txt", io.BytesIO(b"hello again"))
    assert projects.files(p.slug) == [{"name": "a.txt", "size": 11}]
    for bad in ("../x", "PROJECT.md", ".hidden", "a/b", ""):
        assert not projects.valid_file_name(bad)
        with pytest.raises(ValueError):
            projects.save_file(p.slug, bad, io.BytesIO(b"x"))
    assert projects.delete_file(p.slug, "a.txt") and projects.files(p.slug) == []


def test_routes_create_list_change_and_delete(client):
    made = client.post("/projects", json={"name": "Trip", "instructions": "Plan it."})
    assert made.status_code == 201 and made.json()["slug"] == "trip"
    assert client.get("/projects").json() == [{"slug": "trip", "name": "Trip", "description": "", "files": 0}]
    assert client.patch("/projects/trip", json={"instructions": "Plan it well."}).json()["instructions"] == "Plan it well."
    assert client.post("/projects", json={"name": ""}).status_code == 400
    assert client.post("/projects", json={"name": "x"}, headers={"X-Hi-Client": ""}).status_code == 403
    assert client.get("/projects/nope").status_code == 404
    assert client.delete("/projects/trip").status_code == 204 and client.get("/projects").json() == []


def test_upload_and_delete_a_project_file_over_http(client):
    client.post("/projects", json={"name": "Trip"})
    r = client.post("/projects/trip/files?name=plan.md", content=b"# plan")
    assert r.status_code == 201 and r.json() == {"name": "plan.md", "size": 6}
    assert client.get("/projects/trip").json()["files"] == [{"name": "plan.md", "size": 6}]
    assert client.post("/projects/trip/files?name=../evil", content=b"x").status_code == 400
    assert client.delete("/projects/trip/files/plan.md").status_code == 204
    assert client.delete("/projects/trip/files/plan.md").status_code == 404


def test_a_chat_can_be_started_in_a_project_and_moved_out(client):
    client.post("/projects", json={"name": "Trip"})
    chat = client.post("/sessions", json={"project": "trip"}).json()
    assert chat["project"] == "trip"
    assert [c["id"] for c in client.get("/projects/trip").json()["chats"]] == [chat["id"]]
    assert client.post("/sessions", json={"project": "nope"}).status_code == 400
    assert client.patch(f"/sessions/{chat['id']}", json={"project": ""}).json()["project"] == ""
    assert client.patch(f"/sessions/{chat['id']}", json={"project": "nope"}).status_code == 400
    assert client.get("/projects/trip").json()["chats"] == []


def test_a_project_holds_several_chats(client):
    client.post("/projects", json={"name": "Trip"})
    ids = {client.post("/sessions", json={"project": "trip"}).json()["id"] for _ in range(3)}
    assert {c["id"] for c in client.get("/projects/trip").json()["chats"]} == ids
