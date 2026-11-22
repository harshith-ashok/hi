import os

import pytest
from starlette.testclient import TestClient

from hi.memory import vault_notes
from hi.server.app import create_app


def note(vault, rel, text="body", mtime=None):
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def vault(tmp_vault):
    note(tmp_vault, "Ideas/Kaapi.md", "# Kaapi", 1000)
    note(tmp_vault, "Ideas/other.md", "x", 3000)
    note(tmp_vault, "inbox.txt", "plain", 2000)
    note(tmp_vault, "hi/knowledge/preferences.md", "prefs", 500)
    note(tmp_vault, "hi/sessions/abc.md", "internal")
    note(tmp_vault, "hi/backups/1/x.md", "internal")
    note(tmp_vault, ".obsidian/workspace.md", "machinery")
    note(tmp_vault, "skills/pdf/SKILL.md", "skill")
    note(tmp_vault, "Ideas/diagram.png", "not text")
    return tmp_vault


def test_search_lists_only_your_notes_newest_first(vault):
    assert [n["path"] for n in vault_notes.search()] == ["Ideas/other.md", "inbox.txt", "Ideas/Kaapi.md", "hi/knowledge/preferences.md"]


def test_search_matches_every_word_in_the_path_and_prefers_titles_that_start_with_it(vault):
    assert [n["path"] for n in vault_notes.search("kaapi")] == ["Ideas/Kaapi.md"]
    assert [n["path"] for n in vault_notes.search("ideas other")] == ["Ideas/other.md"]
    assert vault_notes.search("nothing here") == []
    assert vault_notes.search("kaapi")[0]["title"] == "Kaapi"


def test_read_refuses_machinery_internals_other_types_and_escapes(vault):
    assert vault_notes.read("Ideas/Kaapi.md") == "# Kaapi"
    for bad in ("hi/sessions/abc.md", "hi/backups/1/x.md", ".obsidian/workspace.md", "skills/pdf/SKILL.md",
                "Ideas/diagram.png", "../outside.md", "/etc/passwd", "Ideas", "missing.md"):
        assert vault_notes.read(bad) is None, bad


def test_routes(vault):
    client = TestClient(create_app())
    assert [n["path"] for n in client.get("/vault/notes?q=kaapi").json()] == ["Ideas/Kaapi.md"]
    assert client.get("/vault/note?path=Ideas/Kaapi.md").json() == {"path": "Ideas/Kaapi.md", "text": "# Kaapi"}
    assert client.get("/vault/note?path=hi/sessions/abc.md").status_code == 404
    assert client.get("/vault/note").status_code == 404
