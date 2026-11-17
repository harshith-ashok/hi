import json
import os
import time
from datetime import datetime

import pytest

import hi.config as config
from hi.automation import drop
from hi.automation.deliver import Delivered
from hi.capture.store import list_items

NOW = datetime(2026, 11, 17, 13, 15)
SUMMARY = json.dumps({"title": "Call with Acme", "summary": "Bob wants the proposal by Friday.",
                      "tasks": ["Send Bob the proposal", "Book a follow-up call"], "folder": "Clients"})


class Sink:
    def __init__(self):
        self.items = []

    def __call__(self, d):
        self.items.append(d)
        return Delivered("", "shown")


@pytest.fixture(autouse=True)
def clean(tmp_vault, monkeypatch):
    drop._seen.clear()
    drop._failures.clear()
    drop._started_at = None
    monkeypatch.setattr(config, "DROP_PATH", "")
    folder = drop.drop_dir()
    folder.mkdir(parents=True)
    return folder


def put(folder, name, content="Bob wants the proposal by Friday."):
    path = folder / name
    path.write_text(content)
    return path


def poll(sink=None, model=None, **kw):
    queued = []
    sink = sink or Sink()
    names = drop.poll(NOW, sink, submit=lambda key, fn: queued.append(fn), model_fn=model or (lambda p: SUMMARY), **kw)
    for fn in queued:
        fn()
    return names, sink


def test_a_file_is_only_read_after_it_stops_changing_between_two_polls(clean):
    queued = []

    def look():
        return drop.poll(NOW, Sink(), submit=lambda key, fn: queued.append(key), model_fn=lambda p: SUMMARY)

    path = put(clean, "memo.txt", "a")
    assert look() == []  # first sight: it may still be being written
    path.write_text("a longer version, still being written")  # it changed between polls
    assert look() == []
    assert look() == ["memo.txt"]  # unchanged since the last poll: ready
    assert queued == [f"drop:{path}"]


def test_an_empty_file_is_never_ready(clean):
    put(clean, "empty.txt", "")
    drop.poll(NOW, Sink(), submit=lambda k, f: None)
    assert drop.poll(NOW, Sink(), submit=lambda k, f: None) == []


def test_placeholders_dotfiles_partial_downloads_and_folders_are_skipped(clean):
    for name in (".hidden.txt", ".memo.m4a.icloud", "a.crdownload", "b.part", "c.download", "index.jsonl"):
        put(clean, name)
    (clean / "notes").mkdir()
    put(clean, "real.txt")
    assert [p.name for p in drop.candidates()] == ["real.txt"]


def test_a_text_file_becomes_a_note_with_tasks_and_the_original_is_filed_away(clean, tmp_vault):
    put(clean, "memo.txt")
    poll()
    names, sink = poll()
    (note,) = (clean / "notes").glob("*.md")
    body = note.read_text()
    assert note.name == "2026-11-17-call-with-acme.md"
    assert "Bob wants the proposal by Friday." in body and "- [ ] Send Bob the proposal" in body and "Suggested folder: Clients" in body
    assert "[[hi/drop/processed/2026-11/memo.txt]]" in body
    assert (clean / "processed" / "2026-11" / "memo.txt").exists() and not (clean / "memo.txt").exists()
    assert sorted(t.text for t in list_items(kind="task")) == ["Book a follow-up call", "Send Bob the proposal"]
    (d,) = sink.items
    assert d.headline == "Filed document: Call with Acme, 2 tasks added" and d.origin == "drop" and d.kind == "info"
    assert json.loads(drop.index_path().read_text())["name"] == "memo.txt"


def test_the_same_file_dropped_twice_is_not_filed_twice(clean):
    put(clean, "memo.txt")
    poll(), poll()
    put(clean, "memo-again.txt")  # identical content
    poll()
    names, sink = poll()
    assert len(list((clean / "notes").glob("*.md"))) == 1 and len(list_items(kind="task")) == 2
    assert not (clean / "memo-again.txt").exists() and sink.items == []


def test_a_task_that_already_exists_is_not_added_again(clean):
    from hi.capture.schema import Task
    from hi.capture.store import save

    save(Task(text="send bob the proposal"))
    put(clean, "memo.txt")
    poll(), poll()
    assert len(list_items(kind="task")) == 2


def test_audio_is_transcribed_and_labelled_a_voice_memo(clean, monkeypatch):
    monkeypatch.setattr(drop.attachments, "_transcribe", lambda path: "remind me to call the dentist")
    (clean / "memo.m4a").write_bytes(b"\x00fake audio")
    poll(), poll()
    (note,) = (clean / "notes").glob("*.md")
    assert "kind: voice memo" in note.read_text() and "remind me to call the dentist" in note.read_text()


def test_a_file_that_cannot_be_read_stays_is_reported_once_and_backs_off(clean):
    (clean / "scan.pdf").write_bytes(b"%PDF- not really")
    sink = Sink()
    poll(sink), poll(sink)
    assert (clean / "scan.pdf").exists() and [d.kind for d in sink.items] == ["failure"]
    assert "scan.pdf" in sink.items[0].headline
    poll(sink)
    poll(sink)  # inside the backoff window: not retried, not reported again
    assert len(sink.items) == 1
    assert drop._failures["scan.pdf"].count == 1


def test_a_retry_after_the_backoff_that_fails_again_stays_silent(clean):
    (clean / "scan.pdf").write_bytes(b"%PDF- not really")
    sink = Sink()
    poll(sink), poll(sink)
    drop._failures["scan.pdf"].retry_at = 0
    poll(sink)
    assert drop._failures["scan.pdf"].count == 2 and len(sink.items) == 1


def test_a_stuck_file_becomes_a_signal_after_ten_minutes(clean):
    (clean / "scan.pdf").write_bytes(b"%PDF- x")
    poll(), poll()
    assert drop.stuck_files(NOW) == []
    later = datetime.fromtimestamp(time.time() + 700)
    assert drop.stuck_files(later) == ["scan.pdf"]
    from hi.automation import signals

    assert "scan.pdf" in signals.drop_stuck(later)[0].text


def test_without_a_model_the_file_is_still_filed_with_a_plain_note(clean):
    put(clean, "meeting_notes.txt", "Agenda: budget review")

    def down(prompt):
        raise RuntimeError("ollama down")

    poll(model=down), poll(model=down)
    (note,) = (clean / "notes").glob("*.md")
    assert "meeting notes" in note.read_text() and "Agenda: budget review" in note.read_text()
    assert list_items(kind="task") == []


def test_a_garbled_model_reply_falls_back_to_the_plain_note(clean):
    put(clean, "x.txt", "hello there")
    poll(model=lambda p: "sure! here you go"), poll(model=lambda p: "sure! here you go")
    assert len(list((clean / "notes").glob("*.md"))) == 1


def test_secrets_in_a_document_are_masked_in_the_note(clean):
    put(clean, "env.txt", "GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789\nhello")
    poll(), poll()
    (note,) = (clean / "notes").glob("*.md")
    assert "ghp_abcdefghijklmnopqrstuvwxyz" not in note.read_text() and "hello" in note.read_text()


def test_the_note_is_written_before_the_original_moves(clean, monkeypatch):
    put(clean, "memo.txt")
    poll()
    monkeypatch.setattr(drop.shutil, "move", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    queued = []
    drop.poll(NOW, Sink(), submit=lambda k, fn: queued.append(fn), model_fn=lambda p: SUMMARY)
    queued[0]()
    assert (clean / "memo.txt").exists()  # nothing lost; it will be retried
    assert drop._failures["memo.txt"].count == 1


def test_screenshots_need_the_switch_on_and_a_local_vision_model(monkeypatch):
    monkeypatch.setattr(config, "SCREENSHOT_WATCH", False)
    assert drop.screenshots_allowed() == (False, "SCREENSHOT_WATCH is off")
    monkeypatch.setattr(config, "SCREENSHOT_WATCH", True)
    monkeypatch.setattr(config, "VISION_MODEL", "gemma4:31b-cloud")
    ok, why = drop.screenshots_allowed()
    assert not ok and "hosted" in why
    monkeypatch.setattr(config, "VISION_MODEL", "gemma4:e4b")
    assert drop.screenshots_allowed() == (True, "")


def test_new_screenshots_are_described_but_left_on_the_desktop(clean, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCREENSHOT_WATCH", True)
    monkeypatch.setattr(config, "VISION_MODEL", "gemma4:e4b")
    desktop = tmp_path / "home" / "Desktop"
    desktop.mkdir(parents=True)
    monkeypatch.setenv("HI_HOST_HOME", str(tmp_path / "home"))
    old = put(desktop, "Screenshot 2026-11-01 at 09.00.00.png")
    os.utime(old, (1, 1))  # from before the watcher started: never touched
    monkeypatch.setattr(drop.attachments, "_describe_image", lambda data, mime: "A terminal showing a KeyError")
    drop.poll_screenshots(NOW, Sink(), submit=lambda k, f: f(), model_fn=lambda p: SUMMARY)  # starts the watcher
    new = desktop / "Screenshot 2026-11-17 at 13.00.00.png"
    new.write_bytes(b"\x89PNG fake")
    put(desktop, "notes.txt")  # not a screenshot name
    drop.poll_screenshots(NOW, Sink(), submit=lambda k, f: f(), model_fn=lambda p: SUMMARY)
    sink = Sink()
    names = drop.poll_screenshots(NOW, sink, submit=lambda k, f: f(), model_fn=lambda p: SUMMARY)
    assert names == [new.name] and new.exists() and old.exists()
    assert "KeyError" in next((clean / "notes").glob("*.md")).read_text()
    assert drop.poll_screenshots(NOW, sink, submit=lambda k, f: f(), model_fn=lambda p: SUMMARY) == []  # not again
