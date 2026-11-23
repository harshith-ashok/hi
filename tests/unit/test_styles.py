import pytest

import hi.config as config
from hi.automation import profiles
from hi.memory import styles


def style_file(vault, name, text):
    path = vault / "hi" / "styles" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_the_built_in_styles_and_their_sentences():
    listed = {s["id"]: s for s in profiles.list_styles()}
    assert list(listed) == ["normal", "concise", "explanatory", "formal"] and listed["concise"]["source"] == "built-in"
    assert profiles.style_text("normal") == "" and profiles.style_text("nope") == "" and profiles.style_text("") == ""
    assert "Be brief" in profiles.style_text("concise") and profiles.style_text("concise").startswith("\n\n(Writing style:")


def test_your_own_styles_come_from_the_vault(tmp_vault):
    style_file(tmp_vault, "Pirate.md", "---\nname: Pirate Talk\n---\nAnswer like a pirate.\nKeep the facts straight.\n")
    style_file(tmp_vault, "empty.md", "---\nname: Empty\n---\n")
    style_file(tmp_vault, "concise.md", "Mine should not replace the built-in.")
    listed = {s["id"]: s for s in profiles.list_styles()}
    assert listed["pirate"]["label"] == "Pirate Talk" and listed["pirate"]["source"] == "vault"
    assert "empty" not in listed and listed["concise"]["source"] == "built-in"
    assert "Answer like a pirate. Keep the facts straight." in profiles.style_text("pirate")
    assert "Be brief" in profiles.style_text("concise")


def test_a_long_style_is_cut(tmp_vault):
    style_file(tmp_vault, "long.md", "x " * 2000)
    assert len(styles.vault_styles()["long"]["instruction"]) <= styles.MAX_INSTRUCTION_CHARS


def test_the_styles_route(tmp_vault):
    from starlette.testclient import TestClient

    from hi.server.app import create_app

    style_file(tmp_vault, "pirate.md", "Arr.")
    ids = [s["id"] for s in TestClient(create_app()).get("/styles").json()]
    assert ids == ["normal", "concise", "explanatory", "formal", "pirate"]
