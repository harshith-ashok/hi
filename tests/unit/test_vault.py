import pytest

from hi.memory import vault


def test_create_then_read_note(tmp_vault):
    vault.create_note.invoke({"path": "projects/kaapi.md", "content": "hello"})
    assert (tmp_vault / "hi" / "knowledge" / "projects" / "kaapi.md").is_file()
    assert "hello" in vault.read_note.invoke({"path": "projects/kaapi.md"})


def test_append_creates_missing_note_and_keeps_existing_text(tmp_vault):
    vault.append_note.invoke({"path": "ideas.md", "content": "one"})
    vault.append_note.invoke({"path": "ideas.md", "content": "two"})
    text = vault.read_note.invoke({"path": "ideas.md"})
    assert "one" in text and "two" in text and text.index("one") < text.index("two")


def test_list_notes_is_sorted_and_relative(tmp_vault):
    vault.create_note.invoke({"path": "b.md", "content": "x"})
    vault.create_note.invoke({"path": "a/c.md", "content": "x"})
    listing = vault.list_notes.invoke({})
    assert listing.index("a/c.md") < listing.index("b.md")


def test_read_missing_note_reports_it(tmp_vault):
    assert "does not exist" in vault.read_note.invoke({"path": "nope.md"})


@pytest.mark.parametrize("bad", ["../escape.md", "a/../../escape.md", "/etc/passwd"])
def test_paths_outside_knowledge_are_rejected(tmp_vault, bad):
    with pytest.raises(ValueError):
        vault.create_note.invoke({"path": bad, "content": "x"})
    assert not (tmp_vault / "escape.md").exists()
