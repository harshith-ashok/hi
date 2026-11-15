import pytest

from hi import router


@pytest.fixture(autouse=True)
def _reset_sticky_route(monkeypatch):
    monkeypatch.setattr(router, "_last_route", None)


@pytest.mark.parametrize(
    "prompt, expected",
    [
        ("turn the volume down", ("butler", "haiku")),
        ("set a timer for ten minutes", ("butler", "haiku")),
        ("what's on my screen", ("term", "sonnet")),
        ("what did I write in my notes about kaapi", ("docs", "sonnet")),
        ("find a picture of a red panda", ("web", "haiku")),
        ("open a pull request for this branch", ("term", "sonnet")),
    ],
)
def test_obvious_prompts_skip_the_model(prompt, expected):
    assert router.fast_route(prompt) == expected


def test_unclear_prompt_goes_to_the_model():
    assert router.fast_route("help me think about my week") is None


def test_multi_part_requests_always_go_to_the_model():
    assert router.fast_route("turn the volume down and then play some music") is None


def test_short_follow_up_sticks_to_the_last_route():
    router.remember_route("butler", "haiku")
    assert router.fast_route("do it") == ("butler", "haiku")


def test_long_follow_up_does_not_stick():
    router.remember_route("butler", "haiku")
    assert router.fast_route("please explain how this works in more detail now") is None


def test_collapse_keeps_only_butler_and_term():
    assert router.collapse("butler") == "butler"
    assert {router.collapse(p) for p in ("docs", "web", "term")} == {"term"}
