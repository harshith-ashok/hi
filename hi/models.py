"""Claude-tier-style model selection for the auto-router: haiku/sonnet/opus
map to configured Ollama models (hi/config.py), pulled on demand if not
already available, and cached so a tier isn't rebuilt (and re-warmed) on
every turn.
"""

import subprocess

from langchain_ollama import ChatOllama

import hi.config as config
from hi.chat_model import make_chat_model


def tier_models() -> dict[str, str]:
    """Live tier -> model-name mapping, read fresh from `hi.config` on
    every call rather than snapshotted once at import time — the
    `import hi.config as config` module-attribute-read pattern
    `hi/mcp_tools.py` already uses for the same reason (a `POST /config`
    change to e.g. SONNET_MODEL needs to be visible here without a
    restart). Kept as a function, not a module-level dict, specifically
    so it can never go stale the way the old `TIER_MODELS` constant did."""
    return {
        "haiku": config.HAIKU_MODEL,
        "sonnet": config.SONNET_MODEL,
        "opus": config.OPUS_MODEL,
    }


_pulled: set[str] = set()
# Keyed by (tier, model_name), not just tier — so a config change that
# points a tier at a different model naturally misses the cache and
# builds/warms the new model, instead of silently returning an already-
# cached instance of whatever model that tier used to mean. No separate
# "invalidate on config change" step needed; the key itself is what was
# stale before.
_model_cache: dict[tuple[str, str], ChatOllama] = {}
_fast_model_cache: dict[tuple[str, str], ChatOllama] = {}


def _is_pulled(model_name: str) -> bool:
    if model_name in _pulled:
        return True
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    names = {line.split()[0] for line in result.stdout.splitlines()[1:] if line.strip()}
    if model_name in names:
        _pulled.add(model_name)
        return True
    return False


def ensure_pulled(model_name: str) -> None:
    """Pull `model_name` if it isn't already available, printing progress
    live — a genuinely new local model can take minutes to download, so
    this must not fail silently or hang with no feedback."""
    if _is_pulled(model_name):
        return
    print(f"Pulling model '{model_name}'... this may take a while.")
    process = subprocess.Popen(
        ["ollama", "pull", model_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for line in process.stdout:
        print(line, end="", flush=True)
    process.wait()
    if process.returncode == 0:
        _pulled.add(model_name)
    else:
        raise RuntimeError(f"Failed to pull model '{model_name}' (exit {process.returncode}).")


def get_tier_model(tier: str) -> ChatOllama:
    """Resolve a tier ("haiku"/"sonnet"/"opus") to a cached ChatOllama
    instance, pulling its model first if needed."""
    models = tier_models()
    if tier not in models:
        raise ValueError(f"Unknown tier '{tier}'. Expected one of: {sorted(models)}")
    model_name = models[tier]
    key = (tier, model_name)
    if key not in _model_cache:
        ensure_pulled(model_name)
        _model_cache[key] = make_chat_model(model_name, temperature=0, keep_alive="30m")
    return _model_cache[key]


def get_tier_model_fast(tier: str) -> ChatOllama:
    """Same tier/model as `get_tier_model()`, but WITHOUT reasoning
    enabled — a separate cached instance, not a mutation of the shared
    one `get_tier_model()` returns.

    Real, measured motive: `chat_model.py`'s `make_chat_model()` turns on
    `reasoning=True` for any model that supports it (HAIKU_MODEL
    `gpt-oss:20b-cloud` does), which makes the model "think" through
    even a trivial classification/yes-no judgment before answering.
    Measured directly (not assumed) against `hi/orchestrator/complexity.py`'s
    `classify_with_plan()` — which runs on literally every single REPL
    turn before the real answer even starts — a plain reasoning-off
    call answering the identical prompt came back meaningfully faster
    than the reasoning-on default. Use this for a quick, cheap
    judgment call (classification, a one-line safety check) where the
    answer doesn't need visible chain-of-thought; keep using
    `get_tier_model()` for anything a user might actually want to see
    the model's real reasoning on.
    """
    models = tier_models()
    if tier not in models:
        raise ValueError(f"Unknown tier '{tier}'. Expected one of: {sorted(models)}")
    model_name = models[tier]
    key = (tier, model_name)
    if key not in _fast_model_cache:
        ensure_pulled(model_name)
        _fast_model_cache[key] = ChatOllama(model=model_name, temperature=0, keep_alive="30m")
    return _fast_model_cache[key]


_fast_variant_cache: dict[str, ChatOllama] = {}


def fast_variant(model: ChatOllama) -> ChatOllama:
    """A no-reasoning ChatOllama for the exact same model `model` already
    points at — for a caller that already has a resolved persona model
    (BUTLER_MODEL/TERM_MODEL/etc., not necessarily a haiku/sonnet/opus
    tier, so get_tier_model_fast()'s tier-keyed cache doesn't apply) and
    needs to make one cheap judgment call without paying reasoning's
    latency cost. Same motive and cache-by-resolved-name shape as
    get_tier_model_fast() — see its own docstring — just addressed by
    model name instead of tier label."""
    model_name = model.model
    if model_name not in _fast_variant_cache:
        _fast_variant_cache[model_name] = ChatOllama(model=model_name, temperature=0, keep_alive="30m")
    return _fast_variant_cache[model_name]
