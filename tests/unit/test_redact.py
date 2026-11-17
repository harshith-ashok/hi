import pytest

from hi.core.redact import contains_secret, redact


@pytest.mark.parametrize("secret", [
    "sk-abcdefghijklmnopqrstuvwxyz123456",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "github_pat_11ABCDEFG0abcdefghijklmnop_abcdef",
    "xoxb-123456789012-abcdefghijkl",
    "AKIAIOSFODNN7EXAMPLE",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop",
    "Bearer abcdefghijklmnopqrstuvwxyz012345",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIB\nabc\n-----END RSA PRIVATE KEY-----",
])
def test_known_token_shapes_are_found_and_masked(secret):
    text = f"here: {secret} done"
    assert contains_secret(text)
    assert secret not in redact(text) and "[redacted]" in redact(text)


def test_assignments_to_credential_names_are_masked():
    text = "GITHUB_TOKEN=abcdef123456 and password: 'hunter2hunter2'"
    out = redact(text)
    assert "abcdef123456" not in out and "hunter2hunter2" not in out
    assert out.startswith("GITHUB_TOKEN=")


def test_known_values_are_masked_even_without_a_recognisable_shape():
    assert contains_secret("my pin is zebra-battery-staple", known=["zebra-battery-staple"])
    assert redact("x zebra-battery-staple y", known=["zebra-battery-staple"]) == "x [redacted] y"


def test_a_short_known_value_is_ignored_so_ordinary_words_survive():
    assert not contains_secret("the key is under the mat", known=["key", "mat"])


def test_normal_text_and_git_shas_are_not_secrets():
    sha = "3732f66a1b2c3d4e5f60718293a4b5c6d7e8f901"
    text = f"commit {sha} fixed the token refresh bug in the password form"
    assert not contains_secret(text)
    assert redact(text) == text


def test_the_longest_known_value_is_masked_whole():
    assert redact("abcdefgh12345678", known=["abcdefgh", "abcdefgh12345678"]) == "[redacted]"
