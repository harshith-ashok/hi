"""Claude-tier-style model selection for the auto-router: haiku/sonnet/opus
map to configured Ollama models (hi/config.py), pulled on demand if not
already available, and cached so a tier isn't rebuilt (and re-warmed) on
every turn.
"""

import subprocess

from langchain_ollama import ChatOllama

from hi.config import HAIKU_MODEL, OPUS_MODEL, SONNET_MODEL

TIER_MODELS = {
    "haiku": HAIKU_MODEL,
    "sonnet": SONNET_MODEL,
    "opus": OPUS_MODEL,
}

_pulled: set[str] = set()
_model_cache: dict[str, ChatOllama] = {}


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
    if tier not in TIER_MODELS:
        raise ValueError(f"Unknown tier '{tier}'. Expected one of: {sorted(TIER_MODELS)}")
    if tier not in _model_cache:
        model_name = TIER_MODELS[tier]
        ensure_pulled(model_name)
        _model_cache[tier] = ChatOllama(model=model_name, temperature=0, keep_alive="30m")
    return _model_cache[tier]
