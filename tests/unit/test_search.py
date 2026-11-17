import httpx
import pytest

import hi.config as config
from hi import toolkit
from hi.agents.web import search
from hi.core import health

DATA = {"results": [
    {"title": "Free threading", "url": "https://docs.python.org/3/x", "content": "No GIL.\n  Faster.", "engines": ["duckduckgo", "google"]},
    {"title": "Guide", "url": "https://py-free-threading.github.io", "content": "", "engines": ["brave"]},
]}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    search._cache.clear()
    health.reset()
    monkeypatch.setattr("hi.memory.journal.record_event", lambda *a: None)


def test_results_are_numbered_with_url_snippet_and_engines(monkeypatch):
    monkeypatch.setattr(search, "_fetch", lambda params: DATA)
    out = search.search("python free threading", limit=5)
    assert out.splitlines()[0] == "[1] Free threading — https://docs.python.org/3/x"
    assert "No GIL. Faster. (duckduckgo, google)" in out and "[2] Guide — https://py-free-threading.github.io" in out


def test_the_limit_is_respected_and_empty_results_say_so(monkeypatch):
    monkeypatch.setattr(search, "_fetch", lambda params: DATA)
    assert "[2]" not in search.search("q", limit=1)
    monkeypatch.setattr(search, "_fetch", lambda params: {"results": []})
    assert search.search("nothing here") == "No results."


def test_parameters_reach_searxng_and_bad_ones_fall_back(monkeypatch):
    seen = []
    monkeypatch.setattr(search, "_fetch", lambda params: seen.append(params) or DATA)
    search.search("q", time_range="week", category="news")
    search.search("q2", time_range="decade", category="bogus")
    assert seen[0] == {"q": "q", "format": "json", "categories": "news", "time_range": "week"}
    assert seen[1] == {"q": "q2", "format": "json", "categories": "general"}


def test_a_query_with_a_secret_is_refused_without_any_request(monkeypatch):
    monkeypatch.setattr(search, "_fetch", lambda params: pytest.fail("made a request"))
    assert "secret" in search.search("why does ghp_abcdefghijklmnopqrstuvwxyz0123456789 fail")
    monkeypatch.setattr(config, "HOST_BRIDGE_TOKEN", "a-very-private-bridge-token")
    assert "secret" in search.search("what is a-very-private-bridge-token")


def test_a_repeated_query_is_served_from_the_cache_for_ten_minutes(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "_fetch", lambda params: calls.append(1) or DATA)
    search.search("Same Query", now=1000.0)
    search.search("same query", now=1500.0)
    assert len(calls) == 1
    search.search("same query", now=1000.0 + search.CACHE_TTL_S + 1)
    assert len(calls) == 2


def test_an_outage_marks_searxng_down_and_hides_the_tool(monkeypatch):
    def down(params):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(search, "_fetch", down)
    assert "unavailable" in search.search("anything")
    assert not health.is_up("searxng")
    assert toolkit.required_dependency("web_search") == "searxng" and not toolkit.dependency_is_up("web_search")


def test_recovery_marks_it_up_again(monkeypatch):
    health.mark_down("searxng", "x", cooldown_s=0)
    monkeypatch.setattr(search, "_fetch", lambda params: DATA)
    search.search("q")
    assert health.snapshot()["searxng"]["ok"]


def test_an_empty_query_is_not_searched(monkeypatch):
    monkeypatch.setattr(search, "_fetch", lambda params: pytest.fail("made a request"))
    assert "empty" in search.search("   ")
