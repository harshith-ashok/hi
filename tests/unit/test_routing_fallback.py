import threading
import time

import pytest

from hi import router
from hi.orchestrator import complexity


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(router, "_last_route", None)


def test_a_good_classification_is_returned_as_is(monkeypatch):
    monkeypatch.setattr(complexity, "classify_with_plan", lambda p: ("butler", "haiku", False))
    assert complexity.classify_or_default("x") == ("butler", "haiku", False)


def test_a_failing_classifier_falls_back_to_term_sonnet(monkeypatch):
    def boom(prompt):
        raise RuntimeError("model down")

    monkeypatch.setattr(complexity, "classify_with_plan", boom)
    assert complexity.classify_or_default("x") == ("term", "sonnet", False)


def test_a_failing_classifier_reuses_a_fresh_last_route(monkeypatch):
    monkeypatch.setattr(complexity, "classify_with_plan", lambda p: 1 / 0)
    router.remember_route("butler", "haiku")
    assert complexity.classify_or_default("x") == ("butler", "haiku", False)


def test_a_slow_classifier_does_not_block_the_turn(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(complexity, "classify_with_plan", lambda p: release.wait() or ("web", "opus", True))
    monkeypatch.setattr(complexity, "CLASSIFY_TIMEOUT_S", 0.2)
    started = time.monotonic()
    result = complexity.classify_or_default("x")
    release.set()
    assert result == ("term", "sonnet", False)
    assert time.monotonic() - started < 2


def test_recent_route_expires(monkeypatch):
    router.remember_route("butler", "haiku")
    assert router.recent_route() == ("butler", "haiku")
    monkeypatch.setattr(router, "STICKY_SECONDS", -1)
    assert router.recent_route() is None
