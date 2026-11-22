import pytest

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


def test_the_reserved_names_are_exactly_the_commands_tinyui_handles(tmp_vault):
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "tinyui" / "src" / "lib" / "commands.ts").read_text()
    in_ui = set(re.findall(r"\{ name: '([a-z]+)', description:", source))
    assert in_ui == set(skills.BUILTIN_COMMANDS)


def test_a_skill_called_persona_can_be_run_now(tmp_vault):
    _skill(config.VAULT_PATH, "persona")  # /persona is not a command any more
    assert skills.expand_slash("/persona write a bio")[0] == "persona"


# --- writing skills ----------------------------------------------------------------------------------------------

def test_a_created_skill_is_listed_and_can_be_run_with_a_slash(tmp_vault):
    from hi.agents.term.skill_tools import create_skill

    out = create_skill.invoke({"name": "weekly-report", "description": "Write the weekly report.\nUse on Fridays.", "instructions": "1. Gather the week's notes."})
    assert "/weekly-report" in out
    assert skills.list_skills() == {"weekly-report": "Write the weekly report. Use on Fridays."}
    assert skills.expand_slash("/weekly-report now")[2].startswith("1. Gather")


@pytest.mark.parametrize("name", ["A", "x", "Has Space", "../up", "a" * 41, "-lead", "new", "model"])
def test_bad_and_reserved_names_are_refused(tmp_vault, name):
    from hi.agents.term.skill_tools import create_skill

    assert "Created" not in create_skill.invoke({"name": name, "description": "d", "instructions": "i"})
    assert skills.list_skills() == {}


def test_creating_never_overwrites_and_needs_a_description_and_instructions(tmp_vault):
    from hi.agents.term.skill_tools import create_skill

    _skill(config.VAULT_PATH, "pdf", body="original")
    assert "already exists" in create_skill.invoke({"name": "pdf", "description": "d", "instructions": "new"})
    assert "original" in skills.skill_text("pdf")
    assert "description" in create_skill.invoke({"name": "fresh", "description": "  ", "instructions": "i"})
    assert "instructions" in create_skill.invoke({"name": "fresh", "description": "d", "instructions": " "})


def test_updating_asks_first_backs_up_and_keeps_other_frontmatter(tmp_vault, monkeypatch):
    from hi.agents.term import skill_tools

    _skill(config.VAULT_PATH, "pdf", extra="invoke: false\n", body="old steps")
    update = lambda **kw: skill_tools.update_skill.invoke({"name": "pdf", "instructions": "new steps", **kw})
    monkeypatch.setattr(skill_tools, "confirm_destructive", lambda description: False)
    assert "Cancelled" in update() and "old steps" in skills.skill_text("pdf")
    monkeypatch.setattr(skill_tools, "confirm_destructive", lambda description: True)
    assert "Updated" in update(description="Handle PDFs")
    assert "new steps" in skills.skill_text("pdf")
    text = (config.VAULT_PATH / "skills" / "pdf" / "SKILL.md").read_text()
    assert "invoke: false" in text and "description: Handle PDFs" in text
    (backup,) = (config.VAULT_PATH / "hi" / "backups").glob("*/skills/pdf/SKILL.md")
    assert "old steps" in backup.read_text()
    assert "No skill named" in skill_tools.update_skill.invoke({"name": "ghost", "instructions": "x"})
