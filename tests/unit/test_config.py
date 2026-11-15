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


def test_only_local_and_tailscale_modes_exist():
    assert config.MODES == ("local", "tailscale")


def test_a_saved_openrouter_mode_falls_back_to_local(tmp_path):
    import os
    import subprocess
    import sys

    env = {**os.environ, "AI_MODE": "openrouter", "HOME": str(tmp_path)}
    out = subprocess.run(
        [sys.executable, "-c", "import hi.config as c; print(c.AI_MODE, c.SONNET_MODEL)"],
        env=env, capture_output=True, text=True, check=True,
    )
    assert out.stdout.split()[-2:] == ["local", config.model_for("SONNET_MODEL", "local")]
    assert "no longer supported" in out.stdout


def test_the_unused_per_persona_model_settings_are_gone():
    for role in ("TERM_MODEL", "BUTLER_MODEL", "DOCS_MODEL", "WEB_MODEL"):
        assert role not in config.MODEL_ROLES
    assert config.MODEL_ROLES == ("HAIKU_MODEL", "SONNET_MODEL", "OPUS_MODEL", "VISION_MODEL")
