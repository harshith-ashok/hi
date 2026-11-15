"""Maps a tier ("haiku" / "sonnet" / "opus") to a ready chat model, with fallbacks.

Order tried for a tier: the active mode's model for that tier, then the lower tiers on the same
host (a missing big model degrades to a smaller one), then the same chain on the other configured
host (local <-> tailscale). A host that failed is skipped for a cooldown (hi/core/health.py).
Built models are cached per (tier, mode, model, host), so a config change builds a fresh client.
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel

import hi.config as config
from hi import llm
from hi.core.fallback import AllFailed, first_available
from hi.llm.reasoning import make_chat_model

log = logging.getLogger(__name__)

TIERS = ("haiku", "sonnet", "opus")
_ROLE = {"haiku": "HAIKU_MODEL", "sonnet": "SONNET_MODEL", "opus": "OPUS_MODEL"}


def tier_models(mode: str | None = None) -> dict[str, str]:
    """Live tier -> model name for `mode` (default: the active one), read fresh on every call so a
    `POST /config` change is visible without a restart."""
    if mode is None or mode == config.AI_MODE:
        return {"haiku": config.HAIKU_MODEL, "sonnet": config.SONNET_MODEL, "opus": config.OPUS_MODEL}
    return {tier: config.model_for(role, mode) for tier, role in _ROLE.items()}


def tier_chain(tier: str) -> list[str]:
    """`tier` followed by the cheaper tiers: opus -> sonnet -> haiku."""
    if tier not in TIERS:
        raise ValueError(f"Unknown tier '{tier}'. Expected one of: {sorted(TIERS)}")
    return list(reversed(TIERS[: TIERS.index(tier) + 1]))


_cache: dict[tuple, BaseChatModel] = {}


def available_models(host: str | None = None, mode: str | None = None) -> list[str]:
    """Models on the active (or given) provider. Raises OSError/ValueError."""
    return llm.list_models(mode=mode, host=host)


def ensure_pulled(model_name: str) -> None:
    llm.ensure_available(model_name)


def _build(tier: str, mode: str, reasoning: bool) -> BaseChatModel:
    """The first tier from `tier` downwards whose model is on `mode`'s host. Raises if none is."""
    last: Exception | None = None
    for candidate in tier_chain(tier):
        name = tier_models(mode)[candidate]
        key = (reasoning, candidate, mode, name, llm.signature(mode))
        if key in _cache:
            return _cache[key]
        try:
            llm.ensure_available(name, mode)
        except llm.ModelUnavailable as e:
            log.warning("%s (%s) unavailable, trying a lower tier: %s", candidate, name, e)
            last = e
            continue
        build = make_chat_model if reasoning else llm.build_chat_model
        _cache[key] = build(name, mode=mode, temperature=0, keep_alive=config.KEEP_ALIVE)
        return _cache[key]
    raise last or RuntimeError(f"No model available for tier '{tier}'")


def _resolve(tier: str, reasoning: bool) -> BaseChatModel:
    tier_chain(tier)  # validates the tier
    chain = [(f"ollama:{mode}", lambda mode=mode: _build(tier, mode, reasoning)) for mode in llm.configured_modes()]
    try:
        return first_available(chain)
    except AllFailed as e:
        raise RuntimeError(f"No model reachable. {e}") from e


def get_tier_model(tier: str) -> BaseChatModel:
    """The model for `tier`, with streamed reasoning where the model supports it."""
    return _resolve(tier, reasoning=True)


def get_tier_model_fast(tier: str) -> BaseChatModel:
    """Same tier, but WITHOUT reasoning, for quick judgment calls (classification, yes/no checks)
    where visible chain-of-thought only adds latency. A separate cached client."""
    return _resolve(tier, reasoning=False)


_fast_variant_cache: dict[tuple[str, str], BaseChatModel] = {}


def fast_variant(model: BaseChatModel) -> BaseChatModel:
    """A no-reasoning client for the model `model` already points at, for a caller that has a
    resolved persona model (not necessarily a tier) and needs one cheap judgment call."""
    name = llm.model_name(model)
    key = (name, llm.signature())
    if key not in _fast_variant_cache:
        _fast_variant_cache[key] = llm.build_chat_model(name, temperature=0, keep_alive=config.KEEP_ALIVE)
    return _fast_variant_cache[key]
