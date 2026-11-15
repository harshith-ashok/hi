from hi import config
from hi.env_file import write_env_var


def test_parse_env_handles_quotes_comments_and_blanks(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\n\nA=1\nB="two words"\nC=\'x\'\nnot a pair\n')
    assert config._parse_env(env) == {"A": "1", "B": "two words", "C": "x"}


def test_parse_env_of_missing_file_is_empty(tmp_path):
    assert config._parse_env(tmp_path / "missing") == {}


def test_write_env_var_replaces_then_appends(tmp_path):
    env = tmp_path / ".env"
    write_env_var("A", "1", path=env)
    write_env_var("B", "two words", path=env)
    write_env_var("A", "3", path=env)
    assert config._parse_env(env) == {"A": "3", "B": "two words"}


def test_model_for_uses_the_mode_defaults():
    assert config.model_for("HAIKU_MODEL", "tailscale") == "gemma4:e4b"
    assert config.model_for("HAIKU_MODEL", "local").endswith("-cloud")
