import pytest

from hi import cli


def test_no_flag_means_open_the_web_ui():
    assert cli.parse_mode([]) is None


@pytest.mark.parametrize(
    "flag, marker",
    [
        ("--menubar", cli.MENUBAR_MARKER),
        ("--context-daemon", cli.CONTEXT_DAEMON_MARKER),
        ("--voice-daemon", cli.VOICE_DAEMON_MARKER),
        ("--wake-daemon", cli.WAKE_DAEMON_MARKER),
        ("--capture-daemon", cli.CAPTURE_DAEMON_MARKER),
        ("--suggest-daemon", cli.SUGGEST_DAEMON_MARKER),
    ],
)
def test_daemon_flags(flag, marker):
    assert cli.parse_mode([flag]) == marker


@pytest.mark.parametrize("removed", ["--tui", "--tmux", "--term", "--butler", "--docs", "--web", "--code"])
def test_removed_terminal_flags_are_rejected(removed):
    with pytest.raises(SystemExit):
        cli.parse_mode([removed])
