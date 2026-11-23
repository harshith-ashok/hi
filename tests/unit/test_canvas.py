import io
import json

import pytest

from hi.canvas import board, organise


@pytest.fixture
def no_model(monkeypatch):
    """The organiser's model reply is set per test."""
    reply = {"text": "{}"}
    monkeypatch.setattr(organise, "invoke_with_retry", lambda model, messages: reply["text"])
    monkeypatch.setattr(organise, "get_tier_model_fast", lambda tier: None)
    return reply


def test_new_items_land_in_the_inbox(tmp_vault):
    board.add_text("buy milk")
    snap = board.snapshot()
    assert [g["label"] for g in snap["groups"]] == ["Inbox"]
    assert snap["groups"][0]["items"][0]["text"] == "buy milk"


def test_the_canvas_is_an_obsidian_canvas_file(tmp_vault):
    board.add_text("hello")
    data = json.loads((tmp_vault / "hi" / "canvas" / "dropbox.canvas").read_text())
    assert {n["type"] for n in data["nodes"]} == {"group", "text"}


def test_file_drop_is_saved_and_pending(tmp_vault):
    item_id = board.add_file("a b.png", io.BytesIO(b"png"), 3)
    item = board.snapshot()["groups"][0]["items"][0]
    assert item["kind"] == "image" and item["pending"] and item["url"] == f"/canvas/files/{item_id}/a b.png"
    assert board.file_path(item_id, "a b.png").read_bytes() == b"png"
    assert board.file_path(item_id, "../dropbox.canvas") is None


def test_audio_is_a_voice_note(tmp_vault):
    board.add_file("memo.webm", io.BytesIO(b"x"), 1, "audio")
    assert board.snapshot()["groups"][0]["items"][0]["kind"] == "voice"


def test_organise_files_items_into_groups(tmp_vault, no_model):
    a, b = board.add_text("flights to Lisbon"), board.add_text("hotel in Lisbon")
    no_model["text"] = f'Sure: {{"{a}": "Lisbon trip", "{b}": "lisbon trip", "bogus": "X"}}'
    assert organise.organise() == 2
    labels = [g["label"] for g in board.snapshot()["groups"]]
    assert labels == ["Inbox", "Lisbon trip"]  # the Inbox always stays as the drop target; "lisbon trip" joined the same group


def test_organise_failure_leaves_items_in_the_inbox(tmp_vault, monkeypatch):
    board.add_text("x")

    def boom(*a, **k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(organise, "invoke_with_retry", boom)
    monkeypatch.setattr(organise, "get_tier_model_fast", lambda tier: None)
    assert organise.organise() == 0
    assert board.snapshot()["groups"][0]["label"] == "Inbox"


def test_manual_moves_survive_a_regroup(tmp_vault, no_model):
    a = board.add_text("one")
    board.move_item(a, label="Mine")
    no_model["text"] = f'{{"{a}": "Other"}}'
    organise.organise(regroup=True)
    assert [g["label"] for g in board.snapshot()["groups"] if g["items"]] == ["Mine"]


def test_describe_fills_summary(tmp_vault, monkeypatch):
    item_id = board.add_file("memo.m4a", io.BytesIO(b"x"), 1, "audio")
    monkeypatch.setattr(organise.attachments, "read_file", lambda path, kind="": f"transcript of {path.name} ({kind})")
    organise.describe(item_id)
    item = board.snapshot()["groups"][0]["items"][0]
    assert not item["pending"] and item["summary"] == "transcript of memo.m4a (audio)"


def test_delete_removes_file_and_empty_group(tmp_vault):
    item_id = board.add_file("a.txt", io.BytesIO(b"x"), 1)
    assert board.delete_item(item_id)
    assert not (tmp_vault / "hi" / "canvas" / "files" / item_id).exists()
    assert not board.delete_item(item_id)


def test_rename_group(tmp_vault):
    board.add_text("x")
    gid = board.snapshot()["groups"][0]["id"]
    assert board.rename_group(gid, "  Later  ")
    assert board.snapshot()["groups"][0]["label"] == "Later"


def test_routes_drop_list_move_and_serve(tmp_vault, monkeypatch):
    from starlette.testclient import TestClient

    from hi.server.app import create_app
    from hi.server.routes import canvas as routes

    monkeypatch.setattr(routes, "run_background", lambda name, fn: None)
    client, h = TestClient(create_app()), {"X-Hi-Client": "tinyui"}
    assert client.post("/canvas/text", json={"text": "hi"}).status_code == 403  # needs the client header
    assert client.post("/canvas/text", json={"text": "idea"}, headers=h).status_code == 200
    img = client.post("/canvas/file?name=p.png", content=b"PNG", headers=h).json()["id"]
    snap = client.get("/canvas").json()
    assert sum(len(g["items"]) for g in snap["groups"]) == 2 and snap["pending"] == 1
    assert client.get(f"/canvas/files/{img}/p.png").content == b"PNG"
    assert client.get(f"/canvas/files/{img}/..%2Fx").status_code == 404
    moved = client.patch(f"/canvas/items/{img}", json={"group": "Pictures"}, headers=h).json()
    assert [g["label"] for g in moved["groups"] if g["items"] and g["items"][0]["id"] == img] == ["Pictures"]
    assert client.delete(f"/canvas/items/{img}", headers=h).status_code == 200
    assert client.delete(f"/canvas/items/{img}", headers=h).status_code == 404
