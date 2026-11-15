import pytest

import hi.config as config
from hi import llm
from hi.core import health
from hi.llm import registry


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    health.reset()
    registry._cache.clear()
    monkeypatch.setattr(config, "AI_MODE", "local")
    monkeypatch.setattr(config, "HAIKU_MODEL", "h-local")
    monkeypatch.setattr(config, "SONNET_MODEL", "s-local")
    monkeypatch.setattr(config, "OPUS_MODEL", "o-local")
    monkeypatch.setattr(config, "TAILSCALE_OLLAMA_URL", "100.1.1.1")
    monkeypatch.setattr(registry, "make_chat_model", lambda name, **kw: ("reasoning", name, kw["mode"]))
    monkeypatch.setattr(llm, "build_chat_model", lambda name, **kw: ("plain", name, kw["mode"]))
    yield
    health.reset()


def host_state(monkeypatch, *, missing=(), down=()):
    """Fake ensure_available: `down` modes are unreachable, `missing` is a set of (mode, model)."""
    def ensure(name, mode=None):
        if mode in down:
            raise RuntimeError(f"Can't reach Ollama ({mode})")
        if (mode, name) in missing:
            raise llm.ModelUnavailable(f"{name} missing")
    monkeypatch.setattr(llm, "ensure_available", ensure)


def test_tier_chain_degrades_to_cheaper_tiers():
    assert registry.tier_chain("opus") == ["opus", "sonnet", "haiku"]
    assert registry.tier_chain("haiku") == ["haiku"]
    with pytest.raises(ValueError):
        registry.tier_chain("mega")


def test_the_requested_tier_is_used_when_present(monkeypatch):
    host_state(monkeypatch)
    assert registry.get_tier_model("sonnet") == ("reasoning", "s-local", "local")
    assert registry.get_tier_model_fast("sonnet") == ("plain", "s-local", "local")


def test_a_missing_big_model_degrades_to_a_smaller_one_on_the_same_host(monkeypatch):
    host_state(monkeypatch, missing={("local", "o-local")})
    assert registry.get_tier_model("opus") == ("reasoning", "s-local", "local")


def test_an_unreachable_host_falls_back_to_the_other_host_with_its_own_model_names(monkeypatch):
    host_state(monkeypatch, down={"local"})
    model = registry.get_tier_model("sonnet")
    assert model[2] == "tailscale" and model[1] == config.model_for("SONNET_MODEL", "tailscale")
    assert not health.is_up("ollama:local")


def test_when_nothing_is_reachable_the_error_names_every_host(monkeypatch):
    host_state(monkeypatch, down={"local", "tailscale"})
    with pytest.raises(RuntimeError) as err:
        registry.get_tier_model("sonnet")
    assert "ollama:local" in str(err.value) and "ollama:tailscale" in str(err.value)


def test_tailscale_without_a_url_is_not_tried(monkeypatch):
    monkeypatch.setattr(config, "TAILSCALE_OLLAMA_URL", "")
    assert llm.configured_modes() == ["local"]


def test_built_clients_are_cached(monkeypatch):
    host_state(monkeypatch)
    calls = []
    monkeypatch.setattr(registry, "make_chat_model", lambda name, **kw: calls.append(name) or object())
    assert registry.get_tier_model("haiku") is registry.get_tier_model("haiku")
    assert calls == ["h-local"]
