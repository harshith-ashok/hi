import pytest
from starlette.testclient import TestClient

from hi.memory import preferences
from hi.server.app import create_app

HDR = {"X-Hi-Client": "test"}


@pytest.fixture
def client(tmp_vault):
    return TestClient(create_app(), headers=HDR)


def test_preferences_round_trip_keeps_the_frontmatter_out_of_the_text(tmp_vault):
    preferences.write("- Be brief.\n- Use metric units.")
    assert preferences.path().read_text().startswith("---\ntags: [hi]\n---")
    assert preferences.read() == "- Be brief.\n- Use metric units."


def test_an_existing_file_with_frontmatter_reads_without_it(tmp_vault):
    preferences.path().parent.mkdir(parents=True)
    preferences.path().write_text("---\ntags: [hi]\n---\n\n- **Always sign emails.**\n")
    assert preferences.read() == "- **Always sign emails.**"


def test_blank_text_removes_the_file_and_too_much_text_is_refused(tmp_vault):
    preferences.write("x")
    preferences.write("   \n")
    assert not preferences.path().exists() and preferences.read() == ""
    with pytest.raises(ValueError):
        preferences.write("x" * (preferences.MAX_CHARS + 1))


def test_routes_read_and_replace_the_preferences(client):
    assert client.get("/preferences").json() == {"text": "", "max_chars": preferences.MAX_CHARS}
    assert client.put("/preferences", json={"text": "- Be kind."}).json()["text"] == "- Be kind."
    assert client.get("/preferences").json()["text"] == "- Be kind."
    assert client.put("/preferences", json={"text": 5}).status_code == 400
    assert client.put("/preferences", json={"text": "x" * 9000}).status_code == 400
    assert client.put("/preferences", json={"text": "y"}, headers={"X-Hi-Client": ""}).status_code == 403


def test_what_the_term_agent_reads_is_the_file_the_editor_writes(tmp_vault):
    from hi.agents.term import term
    from hi.memory.vault import knowledge_dir

    assert knowledge_dir() / term.PREFERENCES_PATH == preferences.path()
