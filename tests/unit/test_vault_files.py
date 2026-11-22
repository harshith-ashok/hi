import pytest

from hi.agents.term import vault_files as vf


def call(tool, **kw):
    return tool.invoke(kw)


def test_write_creates_note_anywhere_in_the_vault(tmp_vault):
    assert "Created" in call(vf.write_vault_note, path="Projects/Kaapi", content="# Kaapi\n")
    assert (tmp_vault / "Projects" / "Kaapi.md").read_text() == "# Kaapi\n"


def test_replacing_asks_and_keeps_a_backup(tmp_vault, monkeypatch):
    (tmp_vault / "a.md").write_text("old")
    monkeypatch.setattr(vf, "confirm_destructive", lambda d: True)
    assert "Replaced" in call(vf.write_vault_note, path="a.md", content="new")
    backups = list((tmp_vault / "hi" / "backups").rglob("a.md"))
    assert [b.read_text() for b in backups] == ["old"]


def test_declined_replace_changes_nothing(tmp_vault, monkeypatch):
    (tmp_vault / "a.md").write_text("old")
    monkeypatch.setattr(vf, "confirm_destructive", lambda d: False)
    assert "Cancelled" in call(vf.write_vault_note, path="a.md", content="new")
    assert (tmp_vault / "a.md").read_text() == "old"


def test_edit_needs_exactly_one_match(tmp_vault):
    (tmp_vault / "n.md").write_text("one two two")
    assert "2 times" in call(vf.edit_vault_note, path="n.md", old_text="two", new_text="x")
    assert "not found" in call(vf.edit_vault_note, path="n.md", old_text="zzz", new_text="x")
    assert "Edited" in call(vf.edit_vault_note, path="n.md", old_text="one", new_text="1")
    assert (tmp_vault / "n.md").read_text() == "1 two two"
    assert list((tmp_vault / "hi" / "backups").rglob("n.md"))


def test_append_adds_on_a_new_line(tmp_vault):
    (tmp_vault / "n.md").write_text("a")
    call(vf.append_vault_note, path="n.md", content="b")
    assert (tmp_vault / "n.md").read_text() == "a\nb\n"


def test_move_refuses_to_overwrite(tmp_vault):
    (tmp_vault / "a.md").write_text("a")
    (tmp_vault / "b.md").write_text("b")
    assert "already exists" in call(vf.move_vault_note, path="a.md", new_path="b.md")
    assert "Moved" in call(vf.move_vault_note, path="a.md", new_path="sub/c.md")
    assert (tmp_vault / "sub" / "c.md").read_text() == "a"


@pytest.mark.parametrize("bad", ["../x.md", "/etc/passwd.md", ".obsidian/app.md", ".git/config.txt", "hi/backups/x/a.md", "pic.png"])
def test_unsafe_paths_are_refused(tmp_vault, bad):
    with pytest.raises(ValueError):
        vf.resolve(bad)
    assert "Created" not in call(vf.write_vault_note, path=bad, content="x")


def test_list_folder_hides_machinery(tmp_vault):
    (tmp_vault / ".obsidian").mkdir()
    (tmp_vault / "Notes").mkdir()
    (tmp_vault / "a.md").write_text("a")
    listing = call(vf.list_vault_folder)
    assert "[dir] Notes/" in listing and "[file] a.md" in listing and "obsidian" not in listing
