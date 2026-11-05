"""Reads ~/.hi/.env for user-configurable settings: the Obsidian vault path
and the Ollama model used by each persona. Missing file or missing keys fall
back to sensible defaults, so a fresh install works with no .env at all.
"""

import os
import re
from pathlib import Path

ENV_PATH = Path.home() / ".hi" / ".env"

DEFAULT_MODEL = "gpt-oss:120b-cloud"

_ESCAPE_RE = re.compile(r"\\(.)")


def _parse_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            value = _ESCAPE_RE.sub(r"\1", value)
        env[key] = value
    return env


# ~/.hi/.env wins; real environment variables (e.g. from Docker) are the fallback.
_env = {**os.environ, **_parse_env(ENV_PATH)}

# --- AI layer -----------------------------------------------------------
# Three ways to reach a model (see hi/llm.py for what each one does):
#   local       Ollama on this machine (OLLAMA_HOST)
#   tailscale   Ollama on another machine over your tailnet (TAILSCALE_OLLAMA_URL)
#   openrouter  OpenRouter's hosted API (OPENROUTER_API_KEY)
MODES = ("local", "tailscale", "openrouter")
AI_MODE = _env.get("AI_MODE") or "local"
if AI_MODE not in MODES:
    AI_MODE = "local"

OLLAMA_HOST = _env.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
TAILSCALE_OLLAMA_URL = _env.get("TAILSCALE_OLLAMA_URL") or ""
OPENROUTER_API_KEY = _env.get("OPENROUTER_API_KEY") or ""

# Model names differ per mode (Ollama tags vs OpenRouter slugs), so each mode
# keeps its own set in ~/.hi/.env under a prefix. The unprefixed names below
# (SONNET_MODEL, ...) are always the *active* mode's values — everything else
# in the codebase reads those and never needs to know about modes.
#
# Haiku runs on every router turn and sonnet on most answers; opus is the
# heaviest tier. Ollama defaults are cloud variants (a local 8B model measured
# 30-85s per call on this machine).
MODEL_ROLES = (
    "HAIKU_MODEL", "SONNET_MODEL", "OPUS_MODEL",
    "TERM_MODEL", "BUTLER_MODEL", "DOCS_MODEL", "WEB_MODEL", "VISION_MODEL",
)
_MODE_PREFIX = {"local": "", "tailscale": "TAILSCALE_", "openrouter": "OPENROUTER_"}
_OLLAMA_DEFAULTS = {
    "HAIKU_MODEL": "gpt-oss:20b-cloud",
    "SONNET_MODEL": DEFAULT_MODEL,
    "OPUS_MODEL": "nemotron-3-ultra:cloud",
    "TERM_MODEL": DEFAULT_MODEL,
    "BUTLER_MODEL": DEFAULT_MODEL,
    "DOCS_MODEL": DEFAULT_MODEL,
    "WEB_MODEL": "gpt-oss:20b-cloud",
    "VISION_MODEL": "gemma4:31b-cloud",
}
_OPENROUTER_DEFAULTS = {
    "HAIKU_MODEL": "openai/gpt-oss-20b",
    "SONNET_MODEL": "openai/gpt-oss-120b",
    "OPUS_MODEL": "anthropic/claude-sonnet-5.5",
    "TERM_MODEL": "openai/gpt-oss-120b",
    "BUTLER_MODEL": "openai/gpt-oss-120b",
    "DOCS_MODEL": "openai/gpt-oss-120b",
    "WEB_MODEL": "openai/gpt-oss-20b",
    "VISION_MODEL": "google/gemini-2.5-flash",
}


def env_key(role: str, mode: str) -> str:
    return _MODE_PREFIX[mode] + role


def model_for(role: str, mode: str | None = None) -> str:
    """`role`'s model name under `mode` (default: the active mode)."""
    mode = mode or AI_MODE
    defaults = _OPENROUTER_DEFAULTS if mode == "openrouter" else _OLLAMA_DEFAULTS
    return _env.get(env_key(role, mode)) or defaults[role]


def apply_mode() -> None:
    """Point the unprefixed model globals at the active mode's values."""
    for role in MODEL_ROLES:
        globals()[role] = model_for(role)


apply_mode()

VAULT_PATH = Path(_env.get("VAULT_PATH", str(Path.home() / ".hi" / "vault")))
WHISPER_MODEL = _env.get("WHISPER_MODEL", "base.en")

# hi/perception/vision.py's ask_about_screen — a real vision-capable
# model, not a tier (haiku/sonnet/opus below are all text-only), per
# explicit request.

# Claude-tier-style model selection for the auto-router (hi/router.py): each
# turn picks a persona AND a tier, so a quick lookup doesn't burn the same
# model as a complex request. Cloud variants only (measured a local 8B model
# at 30-85s per call on this machine — CPU-only, no GPU acceleration — which
# is worse than Ollama Cloud's occasional cold-start latency, and HAIKU runs
# on every single router turn).
# Was qwen3.5:397b-cloud — confirmed live (TODO.md Phase 14) that this
# requires a subscription this account doesn't have (a real 402 at call
# time, exactly the silent-breakage BLOCKERS.md flagged as a risk, not
# just a theoretical one). nemotron-3-ultra:cloud is the largest model in
# the confirmed-usable set (BLOCKERS.md's own recommended swap-in),
# confirmed live and working.

# MCP (Model Context Protocol) server credentials (hi/mcp_tools.py). Both
# None if unset — the corresponding server is simply left out rather than
# failing, so `hi` works the same with or without them configured.
GITHUB_PERSONAL_ACCESS_TOKEN = _env.get("GITHUB_PERSONAL_ACCESS_TOKEN") or None
OBSIDIAN_REST_API_KEY = _env.get("OBSIDIAN_REST_API_KEY") or None
# n8n's own MCP server needs two values, not one credential — the
# instance's own URL (self-hosted, varies per user, unlike Obsidian's
# fixed loopback address) alongside its bearer token.
N8N_MCP_URL = _env.get("N8N_MCP_URL") or None
N8N_MCP_TOKEN = _env.get("N8N_MCP_TOKEN") or None

# hi/perception/diff_watch.py — an interval-based screenshot-diff watcher,
# a genuinely different privacy posture than every other perception tool
# (which are strictly one-shot, explicitly-asked-for). Off unless the user
# opts in explicitly; unset/anything else defaults to disabled.
DIFF_WATCH_ENABLED = _env.get("DIFF_WATCH_ENABLED", "").strip().lower() in ("1", "true", "yes")

# hi/suggest/engine.py's model-judgment enrichment (TODO.md Phase 14) — an
# extra real model call every suggestion cycle (default every 30min), on
# top of the always-on deterministic gates. Off by default for the same
# reason DIFF_WATCH_ENABLED is: a recurring background cloud-model cost the
# user should opt into explicitly, not one this project should incur
# silently just by existing.
SMART_SUGGESTIONS_ENABLED = _env.get("SMART_SUGGESTIONS_ENABLED", "").strip().lower() in ("1", "true", "yes")


def set_value(key: str, value: str) -> None:
    """Persist `key=value` to ~/.hi/.env and apply it to this process
    immediately (every consumer reads `config.<KEY>` live at call time).
    Model names are stored under the active mode's prefix; setting AI_MODE
    re-points every model global at the new mode's set."""
    from hi.env_file import write_env_var

    if key == "AI_MODE" and value not in MODES:
        raise ValueError(f"AI_MODE must be one of: {', '.join(MODES)}")
    stored_key = env_key(key, AI_MODE) if key in MODEL_ROLES else key
    write_env_var(stored_key, value, path=ENV_PATH)
    _env[stored_key] = value
    globals()[key] = Path(value) if key == "VAULT_PATH" else value
    if key == "AI_MODE":
        apply_mode()
