import pytest

import hi.config as config
from hi import llm
from hi.llm import providers


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    providers._available.clear()
    providers._pulling.clear()
    monkeypatch.setattr(config, "TAILSCALE_OLLAMA_URL", "100.1.1.1")


def test_a_missing_local_model_starts_a_background_pull_and_does_not_block(monkeypatch):
    pulls = []
    monkeypatch.setattr(providers, "list_models", lambda mode=None, **kw: ["other"])
    monkeypatch.setattr(providers, "_start_pull", lambda name, mode, host: pulls.append((name, mode)) or True)
    with pytest.raises(llm.ModelUnavailable, match="downloading in the background"):
        llm.ensure_available("big", "local")
    assert pulls == [("big", "local")]


def test_a_missing_tailscale_model_is_never_pulled(monkeypatch):
    monkeypatch.setattr(providers, "list_models", lambda mode=None, **kw: [])
    monkeypatch.setattr(providers, "_start_pull", lambda *a: pytest.fail("must not pull on someone else's machine"))
    with pytest.raises(llm.ModelUnavailable, match="pull it there"):
        llm.ensure_available("big", "tailscale")


def test_an_unreachable_host_is_a_runtime_error_not_model_unavailable(monkeypatch):
    def down(mode=None, **kw):
        raise OSError("refused")

    monkeypatch.setattr(providers, "list_models", down)
    with pytest.raises(RuntimeError, match="Can't reach Ollama") as err:
        llm.ensure_available("m", "local")
    assert not isinstance(err.value, llm.ModelUnavailable)


def test_a_present_model_is_remembered(monkeypatch):
    calls = []
    monkeypatch.setattr(providers, "list_models", lambda mode=None, **kw: calls.append(1) or ["m"])
    llm.ensure_available("m", "local")
    llm.ensure_available("m", "local")
    assert calls == [1]


def test_the_same_pull_is_only_started_once(monkeypatch):
    started = []
    monkeypatch.setattr(providers.threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: started.append(kw["name"])})())
    assert providers._start_pull("big", "local", "http://h") is True
    assert providers._start_pull("big", "local", "http://h") is False
    assert started == ["pull-big"]


def test_chat_models_get_an_explicit_context_window(monkeypatch):
    seen = {}
    monkeypatch.setattr(providers, "ChatOllama", lambda **kw: seen.update(kw) or object())
    monkeypatch.setattr(config, "CONTEXT_TOKENS", 12345)
    providers.build_chat_model("m", mode="tailscale")
    assert seen["num_ctx"] == 12345
    providers.build_chat_model("m", mode="tailscale", num_ctx=999)  # a caller's own value wins
    assert seen["num_ctx"] == 999


def test_changing_the_context_window_changes_the_cache_signature(monkeypatch):
    before = providers.signature("tailscale")
    monkeypatch.setattr(config, "CONTEXT_TOKENS", config.CONTEXT_TOKENS + 1)
    assert providers.signature("tailscale") != before
