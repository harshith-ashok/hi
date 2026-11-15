import pytest

from hi.core import health
from hi.core.fallback import AllFailed, first_available


@pytest.fixture(autouse=True)
def _clean_health():
    health.reset()
    yield
    health.reset()


def boom(msg="down"):
    def fn():
        raise OSError(msg)
    return fn


def test_returns_the_first_working_option():
    assert first_available([("a", lambda: 1), ("b", lambda: 2)]) == 1


def test_falls_through_to_the_next_and_marks_the_failed_one_down():
    assert first_available([("a", boom()), ("b", lambda: 2)]) == 2
    assert not health.is_up("a") and health.is_up("b")


def test_a_down_dependency_is_skipped_without_being_called():
    health.mark_down("a", "x")
    calls = []
    assert first_available([("a", lambda: calls.append(1) or 1), ("b", lambda: 2)]) == 2
    assert calls == []


def test_dependency_is_retried_after_its_cooldown():
    health.mark_down("a", "x", cooldown_s=-1)
    assert first_available([("a", lambda: 1)]) == 1
    assert health.is_up("a")


def test_all_failed_reports_every_reason():
    with pytest.raises(AllFailed) as err:
        first_available([("local", boom("refused")), ("tailscale", boom("no url"))])
    assert err.value.failures == {"local": "refused", "tailscale": "no url"}
    assert "refused" in str(err.value) and "no url" in str(err.value)


def test_snapshot_lists_state():
    health.mark_ok("a")
    health.mark_down("b", "bad")
    snap = health.snapshot()
    assert snap["a"]["ok"] is True and snap["b"] == {"ok": False, "error": "bad", "since": snap["b"]["since"]}
