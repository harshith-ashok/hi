import hi.config as config
from hi.memory import skills


def _skill(vault, name, description="Does a thing", extra="", body="Step one."):
    folder = vault / "skills" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n{body}\n")


def test_expand_slash_returns_skill_and_rest(tmp_vault):
    _skill(config.VAULT_PATH, "pdf", body="Use pypdf.")
    name, rest, instructions = skills.expand_slash("/pdf merge a and b")
    assert (name, rest) == ("pdf", "merge a and b")
    assert "Use pypdf." in instructions


def test_expand_slash_without_arguments(tmp_vault):
    _skill(config.VAULT_PATH, "pdf")
    assert skills.expand_slash("/pdf")[:2] == ("pdf", "")


def test_unknown_name_and_paths_are_left_alone(tmp_vault):
    _skill(config.VAULT_PATH, "pdf")
    assert skills.expand_slash("/nope hi") is None
    assert skills.expand_slash("/Users/me/file.txt please read") is None
    assert skills.expand_slash("hello /pdf") is None


def test_builtin_names_win_over_skills(tmp_vault):
    _skill(config.VAULT_PATH, "new")
    _skill(config.VAULT_PATH, "pdf")
    assert skills.expand_slash("/new thing") is None
    assert [c["name"] for c in skills.slash_commands()] == ["pdf"]
    assert "No skill named" not in skills.use_skill.invoke({"name": "new"})  # the model can still load it


def test_invoke_false_hides_skill(tmp_vault):
    _skill(config.VAULT_PATH, "secret", extra="invoke: false\n")
    assert skills.slash_commands() == []
    assert skills.index() == ""
    assert skills.expand_slash("/secret x") is None
    assert "Step one." in skills.use_skill.invoke({"name": "secret"})


def test_nested_skills_are_found_and_loadable(tmp_vault):
    folder = config.VAULT_PATH / "skills" / "skills" / "pdf"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: pdf\ndescription: PDFs\n---\n\nNested body.\n")
    (folder / "examples").mkdir()
    (folder / "examples" / "SKILL.md").write_text("---\nname: example\ndescription: bundled\n---\n\nx\n")
    assert list(skills.list_skills()) == ["pdf"]
    assert skills.expand_slash("/pdf go")[2].startswith("Nested body.")
    assert "Nested body." in skills.use_skill.invoke({"name": "pdf"})
